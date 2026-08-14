"""O loop do agente: entrada + contexto + memória → `Decision`.

Cobre os casos essenciais do plano (§18.2): nenhuma ação, resposta simples,
ação proposta, decisão inválida, contexto vazio, memória relevante e
irrelevante, erro do LLM, timeout e provider indisponível — mais as duas
propriedades que a fase inteira existe para garantir: **nada é executado** e
**evento irrelevante não vira chamada ao modelo**.
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from jarvis.agent.decision import DecisionType
from jarvis.agent.errors import (
    InvalidDecisionError,
    LLMAuthenticationError,
    LLMInvalidResponseError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from jarvis.agent.input import AgentInput, EventSummary
from jarvis.agent.messages import LLMResponse, StopReason
from jarvis.agent.ports import LLMProvider
from jarvis.agent.prompt import Capability, PromptBuilder
from jarvis.agent.runtime import AgentRuntime, AgentTurn, GenerationDefaults, LLMRetryPolicy
from jarvis.context.model import CurrentContext
from jarvis.memory.adapters.hashing_embeddings import HashingEmbeddingProvider
from jarvis.memory.manager import MemoryManager
from jarvis.memory.memory import MemoryOrigin, MemoryType, Provenance
from jarvis.memory.ports import MemoryCriteria
from tests.agent_doubles import (
    NOON,
    STUB_MODEL,
    FailingLLMProvider,
    StubLLMProvider,
    decision_json,
    make_context,
    make_event_trigger,
    make_user_message,
)
from tests.memory_doubles import FakeMemoryRepository, frozen_clock


def empty_memory() -> MemoryManager:
    """Como o composition root monta: repositório + `EmbeddingProvider` local.

    O agente consulta memória por texto, e busca semântica exige embeddings —
    montar o manager sem eles aqui esconderia esse acoplamento em vez de
    exercê-lo.
    """
    return MemoryManager(
        repository=FakeMemoryRepository(),
        embeddings=HashingEmbeddingProvider(),
        clock=frozen_clock(NOON),
    )


class RecordingSleep:
    """Substitui o relógio de espera: nenhum teste dorme de verdade."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def build_runtime(
    llm: LLMProvider,
    *,
    context: CurrentContext | None = None,
    memory: MemoryManager | None = None,
    threshold: float = 0.45,
    retry: LLMRetryPolicy | None = None,
    sleep: RecordingSleep | None = None,
    max_repair_attempts: int = 1,
    ids: Sequence[str] = ("dec-1", "dec-2", "dec-3"),
) -> AgentRuntime:
    remaining = list(ids)

    def new_id() -> str:
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    return AgentRuntime(
        llm=llm,
        context_reader=lambda: context if context is not None else make_context(as_of=NOON),
        memory=memory if memory is not None else empty_memory(),
        importance_threshold=threshold,
        retry=retry if retry is not None else LLMRetryPolicy(),
        generation=GenerationDefaults(temperature=0.1, max_output_tokens=128, timeout_seconds=9.0),
        max_repair_attempts=max_repair_attempts,
        clock=frozen_clock(NOON),
        new_id=new_id,
        sleep=sleep if sleep is not None else RecordingSleep(),
        monotonic=lambda: 0.0,
    )


def memory_with(content: str, *, subject: str = "cafe.acucar") -> MemoryManager:
    manager = empty_memory()
    manager.remember(
        type=MemoryType.PREFERENCE,
        content=content,
        subject=subject,
        provenance=Provenance(origin=MemoryOrigin.USER),
    )
    return manager


def handle(
    runtime: AgentRuntime, agent_input: AgentInput | None = None, **kwargs: object
) -> AgentTurn:
    return runtime.handle(
        agent_input if agent_input is not None else make_user_message(),
        **kwargs,  # type: ignore[arg-type]
    )


# --- os desfechos ------------------------------------------------------------


def test_a_simple_answer_comes_back_as_notify() -> None:
    """Resposta de conversa é `notify` com `message` — o que distingue um alerta
    de uma réplica é o gatilho, não o tipo (D-6 do plano)."""
    llm = StubLLMProvider([decision_json(type="notify", message="são 12h")])

    turn = handle(build_runtime(llm))

    assert turn.decision.type is DecisionType.NOTIFY
    assert turn.decision.message == "são 12h"
    assert turn.consulted_llm


def test_no_action_is_a_valid_outcome() -> None:
    llm = StubLLMProvider([decision_json(type="ignore", reason="nada a responder", message=None)])

    turn = handle(build_runtime(llm))

    assert turn.decision.type is DecisionType.IGNORE


def test_a_proposed_action_is_returned_and_never_executed() -> None:
    """A garantia central da fase: `act` volta como dado inerte."""
    llm = StubLLMProvider(
        [
            decision_json(
                type="act",
                message=None,
                action={"skill": "send_notification", "parameters": {"text": "pronto"}},
            )
        ]
    )

    turn = handle(build_runtime(llm))

    assert turn.decision.proposes_action
    assert turn.decision.action is not None
    assert turn.decision.action.skill == "send_notification"
    assert not any(callable(getattr(turn.decision, name)) for name in ("action", "memory"))


def test_a_remember_decision_proposes_memory_without_writing_it() -> None:
    repository = FakeMemoryRepository()
    manager = MemoryManager(
        repository=repository, embeddings=HashingEmbeddingProvider(), clock=frozen_clock(NOON)
    )
    llm = StubLLMProvider(
        [
            decision_json(
                type="remember",
                message=None,
                memory={"type": "preference", "content": "prefere café sem açúcar"},
            )
        ]
    )

    turn = handle(build_runtime(llm, memory=manager))

    assert turn.decision.memory is not None
    assert turn.decision.memory.content == "prefere café sem açúcar"
    assert repository.search(MemoryCriteria()) == [], "o runtime não grava memória nesta fase"


# --- contexto e memória ------------------------------------------------------


def test_an_empty_context_still_produces_a_decision() -> None:
    llm = StubLLMProvider()

    turn = handle(build_runtime(llm, context=CurrentContext(as_of=NOON)))

    assert turn.decision.type is DecisionType.NOTIFY


def test_relevant_memory_reaches_the_prompt_and_the_turn() -> None:
    manager = memory_with("prefere café sem açúcar")
    llm = StubLLMProvider()

    turn = handle(
        build_runtime(llm, memory=manager),
        make_user_message(text="como eu gosto de café?"),
    )

    assert turn.used_memory_ids
    assert "café sem açúcar" in llm.requests[0].messages[0].content


def test_without_memory_the_turn_reports_none_used() -> None:
    turn = handle(build_runtime(StubLLMProvider()))

    assert turn.used_memory_ids == ()


def test_context_reaches_the_prompt() -> None:
    llm = StubLLMProvider()

    handle(build_runtime(llm, context=make_context(as_of=NOON, availability="busy")))

    assert '"availability"' in llm.requests[0].messages[0].content


# --- triagem -----------------------------------------------------------------


def test_an_unimportant_event_never_reaches_the_model() -> None:
    """O filtro determinístico existe para reduzir chamadas, não para
    documentá-las: se o LLM for chamado aqui, ele não serve para nada."""
    llm = StubLLMProvider()
    trigger = make_event_trigger(occurred_at=NOON - timedelta(days=2))

    turn = handle(
        build_runtime(llm, context=make_context(as_of=NOON, availability="busy"), threshold=0.9),
        trigger,
    )

    assert llm.calls == 0
    assert turn.consulted_llm is False
    assert turn.decision.type is DecisionType.IGNORE
    assert turn.decision.reason == "below_importance_threshold"


def test_an_important_event_does_reach_the_model() -> None:
    llm = StubLLMProvider()

    turn = handle(
        build_runtime(llm, context=make_context(as_of=NOON, availability="free"), threshold=0.1),
        make_event_trigger(),
    )

    assert llm.calls == 1
    assert turn.consulted_llm
    assert turn.importance is not None


def test_a_user_message_is_never_triaged() -> None:
    """Falar com o agente é, por definição, relevante."""
    llm = StubLLMProvider()

    turn = handle(
        build_runtime(llm, context=make_context(as_of=NOON, availability="busy"), threshold=0.99)
    )

    assert llm.calls == 1
    assert turn.importance is None


# --- correlação --------------------------------------------------------------


def test_an_event_trigger_propagates_correlation_and_causation() -> None:
    llm = StubLLMProvider()
    trigger = make_event_trigger(event_id="evt-42", correlation_id="corr-42")

    turn = handle(build_runtime(llm, threshold=0.0), trigger)

    assert turn.decision.correlation_id == "corr-42"
    assert turn.decision.causation_id == "evt-42"


def test_a_conversation_correlates_by_its_own_id() -> None:
    turn = handle(build_runtime(StubLLMProvider()), make_user_message(conversation_id="conv-7"))

    assert turn.decision.correlation_id == "conv-7"
    assert turn.decision.causation_id is None


def test_the_silent_path_also_carries_correlation() -> None:
    turn = handle(
        build_runtime(StubLLMProvider(), threshold=1.0),
        make_event_trigger(event_id="evt-9", correlation_id="corr-9"),
    )

    assert (turn.decision.correlation_id, turn.decision.causation_id) == ("corr-9", "evt-9")


# --- resposta inválida e reparo ----------------------------------------------


def test_a_malformed_response_triggers_one_repair_attempt() -> None:
    llm = StubLLMProvider(["desculpe, não entendi", decision_json(type="ignore", message=None)])

    turn = handle(build_runtime(llm))

    assert llm.calls == 2
    assert turn.decision.type is DecisionType.IGNORE
    assert "objeto JSON" in llm.requests[1].messages[-1].content


def test_a_second_malformed_response_gives_up() -> None:
    llm = StubLLMProvider(["lixo", "mais lixo"])

    with pytest.raises(InvalidDecisionError):
        handle(build_runtime(llm))

    assert llm.calls == 2


def test_repair_can_be_disabled() -> None:
    llm = StubLLMProvider(["lixo"])

    with pytest.raises(InvalidDecisionError):
        handle(build_runtime(llm, max_repair_attempts=0))

    assert llm.calls == 1


def test_a_blocked_response_is_an_invalid_response() -> None:
    blocked = LLMResponse(text="", stop_reason=StopReason.BLOCKED, model=STUB_MODEL)

    with pytest.raises(LLMInvalidResponseError):
        handle(build_runtime(StubLLMProvider([blocked])))


def _truncated() -> LLMResponse:
    """JSON cortado no meio de uma string, como o provider realmente devolve."""
    return LLMResponse(
        text='{"type":"notify","reason":"ok","message":"aguarde aguarde aguar',
        stop_reason=StopReason.MAX_TOKENS,
        model=STUB_MODEL,
    )


def test_a_truncated_response_is_repaired_by_asking_for_brevity() -> None:
    """Pedir formato a um JSON cortado bate na mesma parede: falta orçamento."""
    llm = StubLLMProvider([_truncated(), decision_json(type="ignore", message=None)])

    turn = handle(build_runtime(llm))

    assert llm.calls == 2
    assert turn.decision.type is DecisionType.IGNORE
    assert "cortada" in llm.requests[1].messages[-1].content
    assert "objeto JSON válido" not in llm.requests[1].messages[-1].content


def test_a_persistently_truncated_response_names_the_token_limit() -> None:
    """O erro precisa nomear a causa: "não é JSON válido" mandaria o usuário
    procurar defeito de formato onde só falta orçamento de saída."""
    llm = StubLLMProvider([_truncated(), _truncated()])

    with pytest.raises(LLMInvalidResponseError, match="cortada pelo limite de tokens"):
        handle(build_runtime(llm))

    assert llm.calls == 2


# --- falhas de provider ------------------------------------------------------


def test_a_transient_failure_is_retried_and_then_succeeds() -> None:
    llm = FailingLLMProvider(LLMProviderError("503"), fail_times=1)
    sleep = RecordingSleep()

    turn = handle(build_runtime(llm, retry=LLMRetryPolicy(max_attempts=2), sleep=sleep))

    assert llm.calls == 2
    assert sleep.delays == [0.5]
    assert turn.decision.type is DecisionType.NOTIFY


def test_a_timeout_exhausts_the_attempts_and_propagates() -> None:
    llm = FailingLLMProvider(LLMTimeoutError("estourou"))

    with pytest.raises(LLMTimeoutError):
        handle(build_runtime(llm, retry=LLMRetryPolicy(max_attempts=2)))

    assert llm.calls == 2


def test_a_permanent_failure_is_not_retried() -> None:
    """Insistir numa credencial inválida gasta quota sem chance de sucesso."""
    llm = FailingLLMProvider(LLMAuthenticationError("credencial recusada"))

    with pytest.raises(LLMAuthenticationError):
        handle(build_runtime(llm, retry=LLMRetryPolicy(max_attempts=3)))

    assert llm.calls == 1


def test_a_rate_limit_respects_the_wait_the_provider_asked_for() -> None:
    llm = FailingLLMProvider(LLMRateLimitError("429", retry_after=4.0), fail_times=1)
    sleep = RecordingSleep()

    handle(build_runtime(llm, retry=LLMRetryPolicy(max_attempts=2), sleep=sleep))

    assert sleep.delays == [4.0]


def test_backoff_grows_between_attempts() -> None:
    policy = LLMRetryPolicy(max_attempts=4, base_delay=0.5, backoff=2.0)

    assert [policy.delay_before(attempt) for attempt in (1, 2, 3)] == [0.5, 1.0, 2.0]


def test_a_retry_policy_needs_at_least_one_attempt() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        LLMRetryPolicy(max_attempts=0)


# --- observabilidade ---------------------------------------------------------


def test_the_turn_reports_usage_and_latency() -> None:
    turn = handle(build_runtime(StubLLMProvider()))

    assert turn.usage is not None
    assert turn.usage.input_tokens == 100
    assert turn.latency_ms == 0.0


def test_capabilities_and_recent_events_reach_the_prompt() -> None:
    llm = StubLLMProvider()
    summary = EventSummary(
        event_id="e-1", event_type="user.noted_fact", source="cli", occurred_at=NOON
    )

    handle(
        build_runtime(llm),
        recent_events=(summary,),
        capabilities=(Capability(name="send_notification", summary="avisa"),),
    )

    content = llm.requests[0].messages[0].content
    assert "user.noted_fact" in content
    assert "send_notification" in content


def test_the_runtime_uses_the_configured_generation_budget() -> None:
    llm = StubLLMProvider()

    handle(build_runtime(llm))

    request = llm.requests[0]
    assert (request.temperature, request.max_output_tokens, request.timeout_seconds) == (
        0.1,
        128,
        9.0,
    )


def test_a_custom_prompt_builder_is_honoured() -> None:
    llm = StubLLMProvider()
    runtime = AgentRuntime(
        llm=llm,
        context_reader=lambda: make_context(as_of=NOON),
        memory=empty_memory(),
        prompt_builder=PromptBuilder(system_instruction="instrução alternativa"),
        clock=frozen_clock(NOON),
    )

    runtime.handle(make_user_message())

    assert llm.requests[0].system == "instrução alternativa"


def test_decisions_are_stamped_with_the_injected_clock() -> None:
    turn = handle(build_runtime(StubLLMProvider()))

    assert turn.decision.decided_at == datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
