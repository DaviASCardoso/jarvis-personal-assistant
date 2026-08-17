"""Carrega `ConditionalRule`s de um arquivo JSON.

Mesmo padrão de `tools/adapters/mcp_config.py`: ausência do arquivo é
"nenhuma regra configurada", não erro — um Jarvis sem `JARVIS_PROACTIVITY_RULES_PATH`
continua funcionando exatamente como antes da Fase 7.

Formato:

```json
[
  {
    "rule_id": "auto_ack_printer",
    "when": ["printer.job_completed"],
    "condition": {"op": "context_equals", "field": "availability", "value": "free"},
    "then": {"skill": "system.read_status", "parameters": {"topic": "$event.job_id"}}
  }
]
```

`memory_present`/`memory_equals` (Fase 9.3) usam `subject` em vez de `field`
ou `key` — ex. `{"op": "memory_present", "subject": "quiet_hours_preference"}`
— e só casam quando o composition root injeta um `MemoryPresence` (ver
`proactivity/adapters/memory_bridge.py`); sem ele, nunca casam.
"""

import json
from collections.abc import Mapping
from pathlib import Path

from jarvis.events.event import JsonValue
from jarvis.proactivity.conditions import ActionTemplate, Condition, ConditionalRule, ConditionOp
from jarvis.proactivity.errors import InvalidConditionError


def load_conditional_rules(path: Path) -> tuple[ConditionalRule, ...]:
    if not path.is_file():
        return ()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise InvalidConditionError(f"{path}: JSON inválido ({error.msg})") from error
    if not isinstance(raw, list):
        raise InvalidConditionError(f"{path}: esperava uma lista de regras")
    return tuple(_rule_from(item, source=path) for item in raw)


def _rule_from(item: object, *, source: Path) -> ConditionalRule:
    if not isinstance(item, Mapping):
        raise InvalidConditionError(f"{source}: cada regra precisa ser um objeto")

    rule_id = item.get("rule_id")
    when = item.get("when")
    condition_raw = item.get("condition")
    then_raw = item.get("then")
    enabled = item.get("enabled", True)

    if not isinstance(rule_id, str):
        raise InvalidConditionError(f"{source}: rule_id ausente ou inválido")
    if not isinstance(when, list) or not all(isinstance(entry, str) for entry in when):
        raise InvalidConditionError(f"{source}: when precisa ser uma lista de strings")
    if not isinstance(condition_raw, Mapping):
        raise InvalidConditionError(f"{source}: condition ausente ou inválida")
    if not isinstance(then_raw, Mapping):
        raise InvalidConditionError(f"{source}: then ausente ou inválido")
    if not isinstance(enabled, bool):
        raise InvalidConditionError(f"{source}: enabled precisa ser booleano")

    return ConditionalRule(
        rule_id=rule_id,
        when=frozenset(when),
        condition=_condition_from(condition_raw, source=source),
        then=_template_from(then_raw, source=source),
        enabled=enabled,
    )


def _condition_from(raw: Mapping[str, object], *, source: Path) -> Condition:
    op_name = raw.get("op")
    if not isinstance(op_name, str) or op_name not in set(ConditionOp):
        raise InvalidConditionError(f"{source}: op desconhecido {op_name!r}")
    op = ConditionOp(op_name)

    children_raw = raw.get("children")
    children = (
        tuple(_condition_from(child, source=source) for child in children_raw)
        if isinstance(children_raw, list)
        else ()
    )

    field_name = raw.get("field")
    key = raw.get("key")
    subject = raw.get("subject")
    return Condition(
        op=op,
        field=field_name if isinstance(field_name, str) else None,
        key=key if isinstance(key, str) else None,
        subject=subject if isinstance(subject, str) else None,
        value=_json_value(raw.get("value"), source=source),
        children=children,
    )


def _template_from(raw: Mapping[str, object], *, source: Path) -> ActionTemplate:
    skill = raw.get("skill")
    if not isinstance(skill, str):
        raise InvalidConditionError(f"{source}: then.skill ausente ou inválido")
    parameters = raw.get("parameters", {})
    if not isinstance(parameters, Mapping):
        raise InvalidConditionError(f"{source}: then.parameters precisa ser um objeto")
    resolved = {str(key): _json_value(value, source=source) for key, value in parameters.items()}
    return ActionTemplate(skill=skill, parameters=resolved)


def _json_value(value: object, *, source: Path) -> JsonValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise InvalidConditionError(f"{source}: value precisa ser um valor JSON simples")
