"""Testes de `load_conditional_rules` (Fase 7.6)."""

import json
from pathlib import Path

import pytest

from jarvis.proactivity.adapters.rules_config import load_conditional_rules
from jarvis.proactivity.conditions import ConditionOp
from jarvis.proactivity.errors import InvalidConditionError


def test_missing_file_returns_no_rules(tmp_path: Path) -> None:
    assert load_conditional_rules(tmp_path / "missing.json") == ()


def test_loads_a_simple_rule(tmp_path: Path) -> None:
    path = tmp_path / "rules.json"
    path.write_text(
        json.dumps(
            [
                {
                    "rule_id": "auto_ack",
                    "when": ["printer.job_completed"],
                    "condition": {"op": "always"},
                    "then": {
                        "skill": "system.read_status",
                        "parameters": {"topic": "$event.job_id"},
                    },
                }
            ]
        ),
        encoding="utf-8",
    )

    rules = load_conditional_rules(path)

    assert len(rules) == 1
    assert rules[0].rule_id == "auto_ack"
    assert rules[0].when == frozenset({"printer.job_completed"})
    assert rules[0].condition.op is ConditionOp.ALWAYS
    assert rules[0].then.skill == "system.read_status"
    assert dict(rules[0].then.parameters) == {"topic": "$event.job_id"}


def test_loads_a_nested_condition(tmp_path: Path) -> None:
    path = tmp_path / "rules.json"
    path.write_text(
        json.dumps(
            [
                {
                    "rule_id": "r1",
                    "when": ["demo.happened"],
                    "condition": {
                        "op": "and",
                        "children": [
                            {"op": "context_equals", "field": "availability", "value": "free"},
                            {"op": "payload_equals", "key": "x", "value": "y"},
                        ],
                    },
                    "then": {"skill": "test.skill"},
                }
            ]
        ),
        encoding="utf-8",
    )

    rules = load_conditional_rules(path)
    condition = rules[0].condition
    assert condition.op is ConditionOp.AND
    assert len(condition.children) == 2


def test_malformed_json_raises(tmp_path: Path) -> None:
    path = tmp_path / "rules.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(InvalidConditionError):
        load_conditional_rules(path)


def test_top_level_must_be_a_list(tmp_path: Path) -> None:
    path = tmp_path / "rules.json"
    path.write_text(json.dumps({"rule_id": "r1"}), encoding="utf-8")
    with pytest.raises(InvalidConditionError):
        load_conditional_rules(path)


def test_missing_rule_id_raises(tmp_path: Path) -> None:
    path = tmp_path / "rules.json"
    path.write_text(
        json.dumps([{"when": ["x"], "condition": {"op": "always"}, "then": {"skill": "s"}}]),
        encoding="utf-8",
    )
    with pytest.raises(InvalidConditionError):
        load_conditional_rules(path)


def test_unknown_operator_raises(tmp_path: Path) -> None:
    path = tmp_path / "rules.json"
    path.write_text(
        json.dumps(
            [
                {
                    "rule_id": "r1",
                    "when": ["x"],
                    "condition": {"op": "eval"},
                    "then": {"skill": "s"},
                }
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(InvalidConditionError):
        load_conditional_rules(path)


def test_loads_a_memory_present_condition(tmp_path: Path) -> None:
    """Fase 9.3: `subject` é o campo próprio de `memory_present`/`memory_equals`."""
    path = tmp_path / "rules.json"
    path.write_text(
        json.dumps(
            [
                {
                    "rule_id": "quiet_hours",
                    "when": ["notification.candidate"],
                    "condition": {"op": "memory_present", "subject": "quiet_hours_preference"},
                    "then": {"skill": "test.skill"},
                }
            ]
        ),
        encoding="utf-8",
    )

    rules = load_conditional_rules(path)

    assert rules[0].condition.op is ConditionOp.MEMORY_PRESENT
    assert rules[0].condition.subject == "quiet_hours_preference"


def test_missing_then_skill_raises(tmp_path: Path) -> None:
    path = tmp_path / "rules.json"
    path.write_text(
        json.dumps([{"rule_id": "r1", "when": ["x"], "condition": {"op": "always"}, "then": {}}]),
        encoding="utf-8",
    )
    with pytest.raises(InvalidConditionError):
        load_conditional_rules(path)
