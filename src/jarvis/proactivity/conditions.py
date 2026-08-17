"""Conditional Triggers: "quando X acontecer e Y for verdadeiro, faça Z".

Linguagem de condição pequena e **fechada** — seis operadores, sem `eval`,
sem acesso a atributo livre. Regras vêm de um arquivo de configuração
(`adapters/rules_config.py`), e um arquivo de configuração que executasse
código seria uma porta para execução arbitrária disfarçada de dado.

Diferente do Trigger Engine (7.1, que decide *se* vale acionar o Agent
Runtime), este caminho **não passa pelo LLM**: `ConditionEngine.evaluate`
produz uma `ActionRequest` diretamente, com `actor=Actor.SYSTEM` — automação
determinística, não raciocínio. Quem a executa continua sendo
`ActionExecutor` (ADR-0016); este módulo só monta o pedido.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from enum import StrEnum

from jarvis.context.model import ContextField, CurrentContext, iter_fields
from jarvis.context.observation import Freshness
from jarvis.events.event import JsonValue, RecordedEvent
from jarvis.execution.model import ActionRequest, Actor
from jarvis.proactivity.errors import InvalidConditionError

_VALID_CONTEXT_FIELDS: frozenset[str] = frozenset(item.value for item in ContextField)


class ConditionOp(StrEnum):
    ALWAYS = "always"
    CONTEXT_EQUALS = "context_equals"
    CONTEXT_PRESENT = "context_present"
    PAYLOAD_EQUALS = "payload_equals"
    AND = "and"
    OR = "or"
    NOT = "not"


@dataclass(frozen=True, slots=True, kw_only=True)
class Condition:
    op: ConditionOp
    field: str | None = None
    key: str | None = None
    value: JsonValue = None
    children: tuple["Condition", ...] = ()

    def __post_init__(self) -> None:
        needs_field = self.op in (ConditionOp.CONTEXT_EQUALS, ConditionOp.CONTEXT_PRESENT)
        if needs_field and (not self.field or self.field not in _VALID_CONTEXT_FIELDS):
            raise InvalidConditionError(
                f"{self.op.value}: field precisa ser um campo de contexto válido"
            )
        if self.op is ConditionOp.PAYLOAD_EQUALS and not self.key:
            raise InvalidConditionError("payload_equals: key não pode ser vazio")
        if self.op in (ConditionOp.AND, ConditionOp.OR) and not self.children:
            raise InvalidConditionError(f"{self.op.value}: precisa de ao menos uma condição filha")
        if self.op is ConditionOp.NOT and len(self.children) != 1:
            raise InvalidConditionError("not: precisa de exatamente uma condição filha")


def always() -> Condition:
    return Condition(op=ConditionOp.ALWAYS)


def context_equals(field_name: str, value: JsonValue) -> Condition:
    return Condition(op=ConditionOp.CONTEXT_EQUALS, field=field_name, value=value)


def context_present(field_name: str) -> Condition:
    return Condition(op=ConditionOp.CONTEXT_PRESENT, field=field_name)


def payload_equals(key: str, value: JsonValue) -> Condition:
    return Condition(op=ConditionOp.PAYLOAD_EQUALS, key=key, value=value)


def and_(*children: Condition) -> Condition:
    return Condition(op=ConditionOp.AND, children=children)


def or_(*children: Condition) -> Condition:
    return Condition(op=ConditionOp.OR, children=children)


def not_(child: Condition) -> Condition:
    return Condition(op=ConditionOp.NOT, children=(child,))


def _context_value(context: CurrentContext, field_name: str) -> JsonValue:
    """O valor observado e **fresco** de um campo, ou `None` se ausente/vencido.

    Mesmo critério de `agent/importance.py::_label`: um dado vencido não vale
    como estado atual.
    """
    for candidate, observation in iter_fields(context):
        if candidate.value != field_name:
            continue
        if observation is None or observation.freshness(context.as_of) is Freshness.STALE:
            return None
        value = observation.value
        return value if value is None or isinstance(value, str | int | float | bool) else str(value)
    return None


def evaluate_condition(
    condition: Condition, *, event: RecordedEvent, context: CurrentContext
) -> bool:
    op = condition.op
    if op is ConditionOp.ALWAYS:
        return True
    if op is ConditionOp.CONTEXT_EQUALS:
        assert condition.field is not None  # garantido por __post_init__
        return _context_value(context, condition.field) == condition.value
    if op is ConditionOp.CONTEXT_PRESENT:
        assert condition.field is not None
        return _context_value(context, condition.field) is not None
    if op is ConditionOp.PAYLOAD_EQUALS:
        assert condition.key is not None
        return event.event.payload.get(condition.key) == condition.value
    if op is ConditionOp.AND:
        return all(
            evaluate_condition(child, event=event, context=context) for child in condition.children
        )
    if op is ConditionOp.OR:
        return any(
            evaluate_condition(child, event=event, context=context) for child in condition.children
        )
    # NOT: única opção restante, garantida exaustiva por `ConditionOp` ter seis membros.
    return not evaluate_condition(condition.children[0], event=event, context=context)


@dataclass(frozen=True, slots=True, kw_only=True)
class ActionTemplate:
    """O que fazer quando a condição casa.

    `parameters` pode conter placeholders `"$event.<chave>"`, resolvidos
    contra o payload do evento no momento da avaliação — nunca em tempo de
    configuração, para que o mesmo template sirva qualquer ocorrência do
    tipo de evento.
    """

    skill: str
    parameters: Mapping[str, JsonValue] = dataclass_field(default_factory=dict)


def _resolve(value: JsonValue, *, event: RecordedEvent) -> JsonValue:
    if isinstance(value, str) and value.startswith("$event."):
        return event.event.payload.get(value.removeprefix("$event."))
    if isinstance(value, Mapping):
        return {key: _resolve(item, event=event) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str):
        return [_resolve(item, event=event) for item in value]
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class ConditionalRule:
    rule_id: str
    when: frozenset[str]
    condition: Condition
    then: ActionTemplate
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise InvalidConditionError("rule_id não pode ser vazio")
        if not self.when:
            raise InvalidConditionError(f"regra {self.rule_id!r} precisa declarar ao menos um when")

    def matches_type(self, event_type: str) -> bool:
        return self.enabled and event_type in self.when


class ConditionEngine:
    """Casa eventos contra as regras registradas e monta a `ActionRequest`.

    Primeira regra que casa **tipo e condição** vence — mesma ordem de
    prioridade do Trigger Engine (7.1).
    """

    def __init__(self, rules: Sequence[ConditionalRule] = ()) -> None:
        self._rules = tuple(rules)

    @property
    def rules(self) -> tuple[ConditionalRule, ...]:
        return self._rules

    def evaluate(self, recorded: RecordedEvent, *, context: CurrentContext) -> ActionRequest | None:
        event_type = recorded.event.event_type
        for rule in self._rules:
            if not rule.matches_type(event_type):
                continue
            if not evaluate_condition(rule.condition, event=recorded, context=context):
                continue
            resolved = _resolve(dict(rule.then.parameters), event=recorded)
            parameters = resolved if isinstance(resolved, Mapping) else {}
            return ActionRequest(
                skill=rule.then.skill,
                parameters=parameters,
                correlation_id=recorded.event.correlation_id or recorded.event.event_id,
                actor=Actor.SYSTEM,
                causation_id=recorded.event.event_id,
            )
        return None


class ConditionalTriggerConsumer:
    """Ponte entre o Event Bus e o `ConditionEngine`.

    Implementa `EventConsumer`. Não chama `ActionExecutor` — devolve a
    `ActionRequest` a um callback injetado, mesma disciplina de
    `TriggerEventConsumer` (7.1): o pacote nunca ganha acesso direto a uma
    Skill.
    """

    def __init__(
        self,
        engine: ConditionEngine,
        *,
        context_reader: Callable[[], CurrentContext],
        on_action: Callable[[ActionRequest], None],
        name: str = "proactivity-conditions",
    ) -> None:
        self._engine = engine
        self._context_reader = context_reader
        self._on_action = on_action
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def handle(self, event: RecordedEvent) -> None:
        request = self._engine.evaluate(event, context=self._context_reader())
        if request is not None:
            self._on_action(request)
