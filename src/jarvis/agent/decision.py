"""`Decision`: a saída do Agent Runtime, e o limite onde o raciocínio para.

Uma `Decision` é **dado inerte**. Não tem `execute()`, não tem callback, não
carrega referência a Skill, Tool ou MCP. É isso que torna estrutural — e não
apenas disciplinar — a regra do
[ADR-0003](../../../docs/adr/0003-policy-engine-safety-authority.md): o LLM
propõe, código determinístico autoriza. Uma `Decision.act` é uma proposta; quem
decide se ela acontece é o Policy Engine, que chega na Fase 5.

Os seis tipos são os do contrato
([`architecture-contracts.md §3.4`](../../../docs/architecture-contracts.md#34-agent-runtime)),
não uma escolha desta fase. Uma resposta de conversa é `notify` com `message`
preenchido: o que distingue um alerta proativo de uma réplica ao usuário é o
gatilho, não o tipo da decisão.

A interpretação da resposta do modelo acontece **aqui, no Core**, exigência da
decisão 2 do [ADR-0002](../../../docs/adr/0002-llm-provider-abstraction.md). Por
isso `json` é importado neste módulo: JSON é formato genérico de intercâmbio, não
formato de wire de um vendor. O adapter devolve texto; o significado é nosso.
"""

import json
import math
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from jarvis.agent.errors import InvalidDecisionError
from jarvis.events.event import JsonValue
from jarvis.memory.memory import MemoryType

MAX_REASON_LENGTH: Final = 500
MAX_MESSAGE_LENGTH: Final = 2000
MAX_CONTENT_LENGTH: Final = 2000
MAX_SKILL_LENGTH: Final = 64
# Fase 10.1: deliberação passo a passo, mais longa que `reason` (um rótulo
# curto) — mas ainda limitada, para não virar um segundo `message` disfarçado.
MAX_REASONING_LENGTH: Final = 1500

_SLUG_PATTERN: Final = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_FENCE_PATTERN: Final = re.compile(r"^\s*```(?:json)?\s*(?P<body>.*?)\s*```\s*$", re.DOTALL)


class DecisionType(StrEnum):
    IGNORE = "ignore"
    REMEMBER = "remember"
    NOTIFY = "notify"
    ASK = "ask"
    ACT = "act"
    ACT_AND_NOTIFY = "act_and_notify"


# Matriz de validação: por tipo, o que precisa existir e o que não pode existir.
# Tabela em vez de cadeia de `if`s porque é ela que o teste percorre — uma
# variante nova sem entrada aqui quebra o teste, não passa despercebida.
#
# `reasoning` (Fase 10.1) é obrigatório só em `act`/`act_and_notify` — é ali
# que "pensar antes de agir" importa de verdade. Nos demais tipos ele é
# aceito, mas nunca exigido nem proibido (não aparece em `_FORBIDDEN`).
_REQUIRED: Final[Mapping[DecisionType, frozenset[str]]] = {
    DecisionType.IGNORE: frozenset(),
    DecisionType.REMEMBER: frozenset({"memory"}),
    DecisionType.NOTIFY: frozenset({"message"}),
    DecisionType.ASK: frozenset({"message"}),
    DecisionType.ACT: frozenset({"action", "reasoning"}),
    DecisionType.ACT_AND_NOTIFY: frozenset({"action", "message", "reasoning"}),
}

_FORBIDDEN: Final[Mapping[DecisionType, frozenset[str]]] = {
    DecisionType.IGNORE: frozenset({"message", "memory", "action"}),
    DecisionType.REMEMBER: frozenset({"action"}),
    DecisionType.NOTIFY: frozenset({"action"}),
    DecisionType.ASK: frozenset({"action"}),
    DecisionType.ACT: frozenset({"message"}),
    DecisionType.ACT_AND_NOTIFY: frozenset(),
}


def new_decision_id() -> str:
    return str(uuid.uuid4())


def _require_text(value: object, *, field_name: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise InvalidDecisionError(
            f"{field_name} precisa ser texto, recebido {type(value).__name__}"
        )
    if not value.strip():
        raise InvalidDecisionError(f"{field_name} não pode ser vazio")
    if len(value) > max_length:
        raise InvalidDecisionError(f"{field_name} excede {max_length} caracteres: {len(value)}")
    return value


def _require_slug(value: object, *, field_name: str) -> str:
    text = _require_text(value, field_name=field_name, max_length=MAX_SKILL_LENGTH)
    if not _SLUG_PATTERN.fullmatch(text):
        # A mensagem não repete o valor recusado: ele vem do modelo, que pode
        # ter ecoado conteúdo de um evento.
        raise InvalidDecisionError(f"{field_name} não casa com {_SLUG_PATTERN.pattern}")
    return text


def _require_unit_interval(value: object, *, field_name: str) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise InvalidDecisionError(f"{field_name} precisa ser numérico")
    number = float(value)
    if math.isnan(number) or not 0.0 <= number <= 1.0:
        raise InvalidDecisionError(f"{field_name} precisa estar entre 0.0 e 1.0")
    return number


def _freeze_json(value: object, *, path: str) -> JsonValue:
    """Congela recursivamente um valor JSON — mesma garantia de `Event.payload`.

    Sem isto, `parameters` seria um dicionário mutável dentro de uma dataclass
    `frozen`: uma promessa de imutabilidade que o primeiro `params["x"] = 1`
    desmente.
    """
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise InvalidDecisionError(f"{path} não é representável em JSON")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise InvalidDecisionError(f"{path}: chave que não é string")
            frozen[key] = _freeze_json(item, path=f"{path}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, bytes | bytearray):
        raise InvalidDecisionError(f"{path}: bytes não são um tipo JSON")
    if isinstance(value, Sequence):
        return tuple(
            _freeze_json(item, path=f"{path}[{index}]") for index, item in enumerate(value)
        )
    raise InvalidDecisionError(f"{path}: {type(value).__name__} não é um tipo JSON")


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryProposal:
    """O que o agente acha que vale lembrar.

    Proposta, não escrita: nada é gravado nesta fase. Reusa `MemoryType` em vez
    de duplicar a taxonomia — os tipos de memória são do Memory System, e uma
    segunda enumeração divergiria na primeira mudança.
    """

    type: MemoryType
    content: str
    subject: str | None = None
    importance: float = 0.5
    confidence: float = 0.7

    def __post_init__(self) -> None:
        overwrite = object.__setattr__
        overwrite(
            self,
            "content",
            _require_text(self.content, field_name="memory.content", max_length=MAX_CONTENT_LENGTH),
        )
        if self.subject is not None:
            overwrite(self, "subject", _require_slug(self.subject, field_name="memory.subject"))
        overwrite(
            self,
            "importance",
            _require_unit_interval(self.importance, field_name="memory.importance"),
        )
        overwrite(
            self,
            "confidence",
            _require_unit_interval(self.confidence, field_name="memory.confidence"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ActionProposal:
    """Uma Skill que o agente gostaria de ver executada, e com quais parâmetros.

    `skill` é um nome, não uma referência: não existe registry para resolvê-lo
    nesta fase, e resolver aqui daria ao Agent Runtime um caminho até a execução
    que ele não pode ter. A validação é de forma — que o nome seja um slug e que
    os parâmetros sejam JSON. Validar contra o schema real da Skill é
    responsabilidade da Fase 5, depois do Policy Engine.
    """

    skill: str
    parameters: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        overwrite = object.__setattr__
        overwrite(self, "skill", _require_slug(self.skill, field_name="action.skill"))
        if not isinstance(self.parameters, Mapping):
            raise InvalidDecisionError("action.parameters precisa ser um objeto")
        frozen = _freeze_json(self.parameters, path="action.parameters")
        if not isinstance(frozen, Mapping):  # pragma: no cover - garantido acima
            raise InvalidDecisionError("action.parameters precisa ser um objeto")
        overwrite(self, "parameters", frozen)


@dataclass(frozen=True, slots=True, kw_only=True)
class Decision:
    """O juízo do agente sobre uma entrada. Nunca uma ordem de execução."""

    decision_id: str
    type: DecisionType
    reason: str
    decided_at: datetime
    correlation_id: str
    causation_id: str | None = None
    message: str | None = None
    memory: MemoryProposal | None = None
    action: ActionProposal | None = None
    reasoning: str | None = None

    def __post_init__(self) -> None:
        overwrite = object.__setattr__

        overwrite(
            self,
            "decision_id",
            _require_text(self.decision_id, field_name="decision_id", max_length=128),
        )
        overwrite(
            self,
            "correlation_id",
            _require_text(self.correlation_id, field_name="correlation_id", max_length=128),
        )
        if self.causation_id is not None:
            overwrite(
                self,
                "causation_id",
                _require_text(self.causation_id, field_name="causation_id", max_length=128),
            )
        overwrite(
            self,
            "reason",
            _require_text(self.reason, field_name="reason", max_length=MAX_REASON_LENGTH),
        )
        if self.message is not None:
            overwrite(
                self,
                "message",
                _require_text(self.message, field_name="message", max_length=MAX_MESSAGE_LENGTH),
            )
        if self.reasoning is not None:
            overwrite(
                self,
                "reasoning",
                _require_text(
                    self.reasoning, field_name="reasoning", max_length=MAX_REASONING_LENGTH
                ),
            )
        if self.decided_at.utcoffset() is None:
            raise InvalidDecisionError("decided_at precisa ser timezone-aware")
        overwrite(self, "decided_at", self.decided_at.astimezone(UTC))

        self._check_shape()

    def _check_shape(self) -> None:
        present = {
            name
            for name in ("message", "memory", "action", "reasoning")
            if getattr(self, name) is not None
        }
        missing = _REQUIRED[self.type] - present
        if missing:
            raise InvalidDecisionError(
                f"decisão {self.type.value} exige {', '.join(sorted(missing))}"
            )
        extra = _FORBIDDEN[self.type] & present
        if extra:
            raise InvalidDecisionError(
                f"decisão {self.type.value} não admite {', '.join(sorted(extra))}"
            )

    @property
    def proposes_action(self) -> bool:
        """As duas variantes que a Fase 5 vai submeter ao Policy Engine."""
        return self.type in (DecisionType.ACT, DecisionType.ACT_AND_NOTIFY)


def _strip_fence(text: str) -> str:
    match = _FENCE_PATTERN.match(text)
    return match.group("body") if match else text.strip()


def _loads_object(text: str) -> Mapping[str, object]:
    """Tolerância deliberada e limitada: cerca markdown e prosa em volta.

    Modelo instruído a responder só JSON às vezes embrulha em ``` ou prefacia
    com uma frase. Recuperar isso é barato e determinístico. O que **não** se
    faz é tentar consertar JSON malformado — aí a resposta é recusar e pedir
    reparo, não adivinhar.
    """
    stripped = _strip_fence(text)
    for candidate in _json_candidates(stripped):
        try:
            decoded: object = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, Mapping):
            return decoded
        raise InvalidDecisionError("resposta do modelo não é um objeto JSON")
    raise InvalidDecisionError("resposta do modelo não é JSON válido")


def _json_candidates(text: str) -> tuple[str, ...]:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return (text,)
    return (text, text[start : end + 1])


def _optional_mapping(payload: Mapping[str, object], key: str) -> Mapping[str, object] | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise InvalidDecisionError(f"{key} precisa ser um objeto")
    return value


def _memory_proposal(raw: Mapping[str, object]) -> MemoryProposal:
    type_name = raw.get("type")
    if not isinstance(type_name, str) or type_name not in set(MemoryType):
        raise InvalidDecisionError(
            f"memory.type precisa ser um de {sorted(item.value for item in MemoryType)}"
        )
    proposal: dict[str, object] = {
        "type": MemoryType(type_name),
        "content": raw.get("content"),
    }
    if raw.get("subject") is not None:
        proposal["subject"] = raw["subject"]
    if raw.get("importance") is not None:
        proposal["importance"] = raw["importance"]
    if raw.get("confidence") is not None:
        proposal["confidence"] = raw["confidence"]
    return MemoryProposal(**proposal)  # type: ignore[arg-type]


def _action_proposal(raw: Mapping[str, object]) -> ActionProposal:
    parameters = raw.get("parameters")
    if parameters is None:
        parameters = {}
    if not isinstance(parameters, Mapping):
        raise InvalidDecisionError("action.parameters precisa ser um objeto")
    return ActionProposal(
        skill=_require_slug(raw.get("skill"), field_name="action.skill"),
        parameters=parameters,
    )


def parse_decision(
    text: str,
    *,
    decision_id: str,
    correlation_id: str,
    decided_at: datetime,
    causation_id: str | None = None,
) -> Decision:
    """Interpreta a resposta do modelo como `Decision`, ou recusa.

    Identidade e correlação **não** vêm do modelo: são atribuídas por quem
    chamou. Deixar o modelo escolher `correlation_id` seria deixá-lo reescrever
    a cadeia de observabilidade — e inventar um `decision_id` que colidisse com
    outro.
    """
    payload = _loads_object(text)

    type_name = payload.get("type")
    if not isinstance(type_name, str) or type_name not in set(DecisionType):
        raise InvalidDecisionError(
            f"type precisa ser um de {sorted(item.value for item in DecisionType)}"
        )

    memory_raw = _optional_mapping(payload, "memory")
    action_raw = _optional_mapping(payload, "action")
    message = payload.get("message")
    reasoning = payload.get("reasoning")

    return Decision(
        decision_id=decision_id,
        type=DecisionType(type_name),
        reason=_require_text(
            payload.get("reason"), field_name="reason", max_length=MAX_REASON_LENGTH
        ),
        decided_at=decided_at,
        correlation_id=correlation_id,
        causation_id=causation_id,
        message=None
        if message is None
        else _require_text(message, field_name="message", max_length=MAX_MESSAGE_LENGTH),
        memory=None if memory_raw is None else _memory_proposal(memory_raw),
        action=None if action_raw is None else _action_proposal(action_raw),
        reasoning=None
        if reasoning is None
        else _require_text(reasoning, field_name="reasoning", max_length=MAX_REASONING_LENGTH),
    )
