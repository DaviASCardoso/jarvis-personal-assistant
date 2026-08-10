"""Política de validade: TTL **por campo**, nunca um TTL global.

[contracts §6](../../../docs/architecture-contracts.md#6-context-contract) é
explícito: "localização expira em minutos; calendário expira no próximo poll". Um
TTL único para todo o `CurrentContext` marcaria como velho um dado que não é, e
como fresco um que já não vale.

Este módulo é o **único** lugar do sistema com constantes de TTL. Um campo sem
entrada é erro, não default silencioso: mapeamento incompleto é bug de quem
acrescentou o campo.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from types import MappingProxyType
from typing import Final

from jarvis.context.errors import InvalidContextError
from jarvis.context.model import ContextField


@dataclass(frozen=True, slots=True)
class TtlPolicy:
    ttl_by_field: Mapping[ContextField, timedelta | None]

    def ttl_for(self, field: ContextField) -> timedelta | None:
        """`None` significa "não expira por tempo", não "não configurado"."""
        if field not in self.ttl_by_field:
            raise InvalidContextError(f"nenhum TTL definido para o campo {field.value}")
        return self.ttl_by_field[field]


DEFAULT_TTL_POLICY: Final = TtlPolicy(
    ttl_by_field=MappingProxyType(
        {
            # O offset local muda só com viagem ou horário de verão.
            ContextField.UTC_OFFSET: timedelta(hours=12),
            # contracts §6: "localização expira em minutos".
            ContextField.PLACE: timedelta(minutes=15),
            # A identidade do dispositivo não envelhece sozinha.
            ContextField.DEVICE_ID: None,
            # Disponibilidade declarada vale por um turno de trabalho.
            ContextField.AVAILABILITY: timedelta(hours=4),
            # Atividade sem novo sinal vira suposição velha.
            ContextField.ACTIVITY: timedelta(hours=1),
            # contracts §6: "calendário expira no próximo poll".
            ContextField.NEXT_ENTRY_AT: timedelta(minutes=15),
            # Conversa sem novo sinal provavelmente terminou.
            ContextField.CONVERSATION: timedelta(minutes=30),
            # Uma tarefa aberta atravessa o dia.
            ContextField.TASK: timedelta(hours=12),
        }
    )
)
