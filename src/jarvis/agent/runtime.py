"""`AgentRuntime`: o loop de raciocínio, e o ponto onde o raciocínio para.

```text
observe → contextualize → retrieve → (triage) → reason → decide → Decision
```

O que o runtime **faz**: lê contexto, recupera memória, avalia importância,
monta prompt, chama o `LLMProvider`, interpreta a resposta e devolve uma
`Decision`.

O que o runtime **não faz**, e não pode passar a fazer sem quebrar o
[ADR-0003](../../../docs/adr/0003-policy-engine-safety-authority.md): executar
Skill, chamar Tool Router, falar com MCP, gravar memória, emitir evento, tocar
banco ou arquivo. Não há caminho até nenhuma dessas coisas a partir daqui — o
único efeito externo de `handle()` é a chamada HTTP que o adapter de LLM faz.

Duas políticas de repetição, deliberadamente separadas:

- **transporte** (`LLMRetryPolicy`) — o provider falhou de forma transitória.
  Repete a mesma requisição, no máximo `max_attempts` vezes, e só quando o erro
  se declara `retryable`.
- **conteúdo** (`max_repair_attempts`) — o provider respondeu, mas a resposta
  não é uma `Decision`. Repete **uma** vez, com um pedido de correção anexado.
  Insistir mais que isso gasta quota para obter a mesma confusão.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from jarvis.agent.conversation import Conversation
from jarvis.agent.decision import Decision, DecisionType, new_decision_id, parse_decision
from jarvis.agent.errors import (
    InvalidDecisionError,
    LLMInvalidResponseError,
    LLMProviderError,
    LLMRateLimitError,
)
from jarvis.agent.importance import (
    DEFAULT_IMPORTANCE_WEIGHTS,
    ImportanceAssessment,
    ImportanceWeights,
    assess,
    should_reason,
)
from jarvis.agent.input import AgentInput, EventSummary, EventTrigger, UserMessage
from jarvis.agent.messages import LLMRequest, LLMResponse, StopReason, TokenUsage
from jarvis.agent.ports import LLMProvider
from jarvis.agent.prompt import Capability, PromptBuilder, ReasoningEnvelope
from jarvis.context.model import CurrentContext
from jarvis.memory.manager import MemoryManager
from jarvis.memory.retrieval import RetrievalQuery, RetrievalResult

logger = logging.getLogger(__name__)

REPAIR_HINT: Final = (
    "Sua resposta anterior não era um objeto JSON válido no schema pedido. "
    "Responda de novo com apenas o objeto JSON, sem cercas e sem texto em volta."
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True, kw_only=True)
class LLMRetryPolicy:
    """Duas tentativas por default, não cinco: a quota gratuita é escassa e
    insistir num provider fora do ar não melhora a resposta."""

    max_attempts: int = 2
    base_delay: float = 0.5
    backoff: float = 2.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError(f"max_attempts precisa ser >= 1, recebido {self.max_attempts}")
        if self.base_delay < 0:
            raise ValueError(f"base_delay não pode ser negativo, recebido {self.base_delay}")

    def delay_before(self, attempt: int, *, requested: float | None = None) -> float:
        """`requested` é o `Retry-After` do provider — respeitá-lo é mais barato
        e mais educado que o backoff cego."""
        if requested is not None:
            return max(requested, 0.0)
        return self.base_delay * (self.backoff ** (attempt - 1))


@dataclass(frozen=True, slots=True, kw_only=True)
class GenerationDefaults:
    """Parâmetros de geração resolvidos pelo composition root a partir de
    `Settings`. O runtime recebe valores, nunca a configuração inteira — é o que
    torna impossível um secret chegar ao prompt por descuido."""

    temperature: float = 0.2
    max_output_tokens: int = 1024
    timeout_seconds: float = 30.0


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentTurn:
    """O resultado de um turno: a decisão e o rastro de como se chegou nela."""

    decision: Decision
    consulted_llm: bool
    importance: ImportanceAssessment | None = None
    used_memory_ids: tuple[str, ...] = ()
    usage: TokenUsage | None = None
    latency_ms: float | None = None


class AgentRuntime:
    """Serviço de aplicação do Core. Não é port: implementação única."""

    def __init__(
        self,
        *,
        llm: LLMProvider,
        context_reader: Callable[[], CurrentContext],
        memory: MemoryManager,
        prompt_builder: PromptBuilder | None = None,
        weights: ImportanceWeights = DEFAULT_IMPORTANCE_WEIGHTS,
        importance_threshold: float = 0.45,
        retry: LLMRetryPolicy | None = None,
        generation: GenerationDefaults | None = None,
        max_repair_attempts: int = 1,
        clock: Callable[[], datetime] = _utc_now,
        new_id: Callable[[], str] = new_decision_id,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._llm = llm
        self._context_reader = context_reader
        self._memory = memory
        self._prompts = prompt_builder if prompt_builder is not None else PromptBuilder()
        self._weights = weights
        self._threshold = importance_threshold
        self._retry = retry if retry is not None else LLMRetryPolicy()
        self._generation = generation if generation is not None else GenerationDefaults()
        self._max_repair_attempts = max_repair_attempts
        self._clock = clock
        self._new_id = new_id
        self._sleep = sleep
        self._monotonic = monotonic

    def handle(
        self,
        agent_input: AgentInput,
        *,
        conversation: Conversation | None = None,
        recent_events: tuple[EventSummary, ...] = (),
        capabilities: tuple[Capability, ...] = (),
    ) -> AgentTurn:
        now = self._clock()
        correlation_id = _correlation_id(agent_input)
        causation_id = _causation_id(agent_input)

        logger.info(
            "agent.turn_started",
            extra={
                "correlation_id": correlation_id,
                "causation_id": causation_id,
                "input_kind": "user_message" if isinstance(agent_input, UserMessage) else "event",
            },
        )

        context = self._context_reader()
        memories = self._retrieve(agent_input)

        assessment = self._triage(agent_input, context=context, memories=memories, now=now)
        if assessment is not None and not should_reason(assessment, threshold=self._threshold):
            return self._silence(
                assessment,
                correlation_id=correlation_id,
                causation_id=causation_id,
                now=now,
                memories=memories,
            )

        envelope = ReasoningEnvelope(
            now=now,
            trigger=agent_input,
            context=context,
            memories=memories,
            recent_events=recent_events,
            conversation=conversation,
            capabilities=capabilities,
        )
        decision, response, latency_ms = self._reason(
            envelope, correlation_id=correlation_id, causation_id=causation_id, now=now
        )

        logger.info(
            "agent.decided",
            extra={
                "correlation_id": correlation_id,
                "causation_id": causation_id,
                "decision_id": decision.decision_id,
                "decision_type": decision.type.value,
                "consulted_llm": True,
                "memory_count": len(memories),
            },
        )
        return AgentTurn(
            decision=decision,
            consulted_llm=True,
            importance=assessment,
            used_memory_ids=_memory_ids(memories),
            usage=response.usage,
            latency_ms=latency_ms,
        )

    def _retrieve(self, agent_input: AgentInput) -> tuple[RetrievalResult, ...]:
        """Memória entra por retrieval, nunca por busca do modelo
        (`PHASE-4.md §9`). `record_access`/`reinforce` **não** são chamados
        aqui: "usar" uma memória só se define quando a decisão vira ação, o que
        é escopo da Fase 5 (`docs/phase-3-plan.md §12.4`)."""
        outcome = self._memory.retrieve(
            RetrievalQuery(
                text=agent_input.retrieval_text() or None,
                limit=self._prompts.budget.max_memories,
            )
        )
        return outcome.results

    def _triage(
        self,
        agent_input: AgentInput,
        *,
        context: CurrentContext,
        memories: tuple[RetrievalResult, ...],
        now: datetime,
    ) -> ImportanceAssessment | None:
        """Mensagem direta do usuário nunca é triada: falar com o agente é, por
        definição, relevante. Só evento passa pelo filtro."""
        if not isinstance(agent_input, EventTrigger):
            return None
        return assess(
            agent_input, context=context, memories=memories, now=now, weights=self._weights
        )

    def _silence(
        self,
        assessment: ImportanceAssessment,
        *,
        correlation_id: str,
        causation_id: str | None,
        now: datetime,
        memories: tuple[RetrievalResult, ...],
    ) -> AgentTurn:
        logger.info(
            "agent.triage_skipped",
            extra={
                "correlation_id": correlation_id,
                "importance": round(assessment.total, 3),
                "threshold": self._threshold,
                "reasons": list(assessment.reasons),
            },
        )
        decision = Decision(
            decision_id=self._new_id(),
            type=DecisionType.IGNORE,
            reason="below_importance_threshold",
            decided_at=now,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )
        return AgentTurn(
            decision=decision,
            consulted_llm=False,
            importance=assessment,
            used_memory_ids=_memory_ids(memories),
        )

    def _reason(
        self,
        envelope: ReasoningEnvelope,
        *,
        correlation_id: str,
        causation_id: str | None,
        now: datetime,
    ) -> tuple[Decision, LLMResponse, float]:
        repair_hint: str | None = None
        total_latency = 0.0

        for repair in range(self._max_repair_attempts + 1):
            request = self._prompts.build(
                envelope,
                temperature=self._generation.temperature,
                max_output_tokens=self._generation.max_output_tokens,
                timeout_seconds=self._generation.timeout_seconds,
                repair_hint=repair_hint,
            )
            response, latency_ms = self._call(request, correlation_id=correlation_id)
            total_latency += latency_ms

            if response.stop_reason is StopReason.BLOCKED:
                raise LLMInvalidResponseError("o provider bloqueou a resposta")

            try:
                decision = parse_decision(
                    response.text,
                    decision_id=self._new_id(),
                    correlation_id=correlation_id,
                    causation_id=causation_id,
                    decided_at=now,
                )
            except InvalidDecisionError as error:
                # A mensagem do erro nomeia o campo, nunca o conteúdo — o texto
                # do modelo pode ecoar payload de evento ou memória.
                logger.warning(
                    "agent.decision_invalid",
                    extra={
                        "correlation_id": correlation_id,
                        "error_type": type(error).__name__,
                        "response_chars": len(response.text),
                        "repair_attempt": repair,
                    },
                )
                if repair == self._max_repair_attempts:
                    raise
                repair_hint = REPAIR_HINT
                continue

            return decision, response, total_latency

        # Inalcançável: o laço ou devolve, ou relança no último reparo.
        raise LLMInvalidResponseError("nenhuma tentativa produziu decisão válida")

    def _call(self, request: LLMRequest, *, correlation_id: str) -> tuple[LLMResponse, float]:
        last_error: LLMProviderError | None = None

        for attempt in range(1, self._retry.max_attempts + 1):
            started = self._monotonic()
            try:
                response = self._llm.generate(request)
            except LLMProviderError as error:
                latency_ms = (self._monotonic() - started) * 1000
                logger.warning(
                    "agent.llm_failed",
                    extra={
                        "correlation_id": correlation_id,
                        "model": str(self._llm.model),
                        "attempt": attempt,
                        "latency_ms": round(latency_ms, 1),
                        "error_type": type(error).__name__,
                        "retryable": error.retryable,
                    },
                )
                last_error = error
                if not error.retryable or attempt == self._retry.max_attempts:
                    raise
                requested = error.retry_after if isinstance(error, LLMRateLimitError) else None
                delay = self._retry.delay_before(attempt, requested=requested)
                if delay:
                    self._sleep(delay)
                continue

            latency_ms = (self._monotonic() - started) * 1000
            logger.info(
                "agent.llm_called",
                extra={
                    "correlation_id": correlation_id,
                    "model": str(response.model),
                    "attempt": attempt,
                    "latency_ms": round(latency_ms, 1),
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                    "stop_reason": response.stop_reason.value,
                },
            )
            return response, latency_ms

        raise last_error if last_error is not None else LLMProviderError("chamada não realizada")


def _correlation_id(agent_input: AgentInput) -> str:
    return agent_input.correlation_id


def _causation_id(agent_input: AgentInput) -> str | None:
    """O evento que gerou a decisão é o gatilho; numa conversa, a cadeia é a
    própria conversa e não há evento pai."""
    return agent_input.causation_id if isinstance(agent_input, EventTrigger) else None


def _memory_ids(memories: tuple[RetrievalResult, ...]) -> tuple[str, ...]:
    return tuple(result.memory.memory.memory_id for result in memories)
