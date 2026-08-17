"""Trigger Engine: decide **se** um evento é candidato a virar raciocínio.

Uma pergunta mais grosseira e anterior à do Importance Engine (`agent/importance.py`):
o Trigger Engine não pesa urgência, relevância ou custo de interrupção — ele só
responde "este tipo de evento é algo que este Jarvis, configurado assim, sequer
considera fora de uma sessão interativa?". A allowlist vazia (nenhuma `TriggerRule`
registrada) nunca casa nada, e é o default: autonomia é opt-in em cada camada
(`docs/phase-7-plan.md §0`), e um Trigger Engine que casasse tudo por padrão
transformaria todo `jarvis events emit` em uma chamada ao LLM.

Este módulo **não conhece o Agent Runtime**. `TriggerEventConsumer` só afirma que
houve casamento e delega a um callback injetado pelo composition root — mesma
razão de `ActionEventConsumer` nunca executar a ação que a confirmação libera
(`execution/consumer.py`): o componente que decide "o que fazer com isto" é sempre
quem chama, nunca quem apenas detecta.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from jarvis.events.event import RecordedEvent
from jarvis.proactivity.errors import InvalidTriggerRuleError


@dataclass(frozen=True, slots=True, kw_only=True)
class TriggerRule:
    """Um tipo de evento que vale considerar para raciocínio proativo.

    Sem predicado sobre o payload nesta subfase — isso é o trabalho da 7.6
    (`ConditionalRule`), que decide *ação*, não *se vale a pena raciocinar*.
    """

    trigger_id: str
    event_types: frozenset[str]
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.trigger_id.strip():
            raise InvalidTriggerRuleError("trigger_id não pode ser vazio")
        if not self.event_types:
            raise InvalidTriggerRuleError(
                f"trigger {self.trigger_id!r} precisa declarar ao menos um event_type"
            )

    def matches(self, event_type: str) -> bool:
        return self.enabled and event_type in self.event_types


class TriggerEngine:
    """Casa eventos contra as regras registradas.

    Não decide o que fazer com o casamento — só afirma que houve um, e com qual
    regra. Primeira regra que casa vence; a ordem de registro é a ordem de
    prioridade, mesmo desenho de `EventBus._subscriptions`.
    """

    def __init__(self, rules: Sequence[TriggerRule] = ()) -> None:
        self._rules = tuple(rules)

    @property
    def rules(self) -> tuple[TriggerRule, ...]:
        return self._rules

    def match(self, recorded: RecordedEvent) -> TriggerRule | None:
        event_type = recorded.event.event_type
        for rule in self._rules:
            if rule.matches(event_type):
                return rule
        return None


class TriggerEventConsumer:
    """Ponte entre o Event Bus e o `TriggerEngine`.

    Implementa o protocolo `EventConsumer` (mesma forma de
    `MemoryEventConsumer`/`ActionEventConsumer`). Evento sem casamento é
    ignorado em silêncio — não é um erro, é o caso comum.
    """

    def __init__(
        self,
        engine: TriggerEngine,
        *,
        on_match: Callable[[RecordedEvent, TriggerRule], None],
        name: str = "proactivity-triggers",
    ) -> None:
        self._engine = engine
        self._on_match = on_match
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def handle(self, event: RecordedEvent) -> None:
        rule = self._engine.match(event)
        if rule is not None:
            self._on_match(event, rule)
