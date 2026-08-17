"""Os comandos e o wiring da Fase 7 no CLI: `tasks`, `decisions`, `info`, e os
`build_*` de proatividade.

Mesmas fixtures de `test_cli_action.py`. `proactivity_enabled=False` (o
default) precisa deixar o comportamento idêntico ao de antes da Fase 7 — é
o que a maioria destes testes prova.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jarvis import cli
from jarvis.cli import (
    ProactivityRuntime,
    _build_proactivity,
    build_condition_engine,
    build_context_engine,
    build_notification_manager,
    build_task_manager,
    build_trigger_engine,
    main,
    task_store_path,
)
from jarvis.config import Settings
from jarvis.context.adapters.sqlite_snapshots import SqliteContextSnapshotRepository
from jarvis.context.model import CurrentContext
from jarvis.events.adapters.sqlite_store import SqliteEventStore
from jarvis.execution.adapters.sqlite_actions import SqliteActionRepository
from jarvis.execution.model import ActionRequest
from jarvis.memory.adapters.sqlite_repository import SqliteMemoryRepository
from jarvis.notify.notification import Notification, NotificationPriority
from jarvis.skills.registry import SkillRegistry
from jarvis.tasks.adapters.sqlite_tasks import SqliteTaskRepository
from jarvis.tasks.manager import TaskManager
from tests.agent_doubles import StubLLMProvider, decision_json

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def isolated_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JARVIS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JARVIS_LOG_LEVEL", "CRITICAL")
    return data_dir


def _build(settings: Settings, *, tmp_path: Path) -> ProactivityRuntime:
    with (
        SqliteEventStore.open(tmp_path / "events.db") as store,
        SqliteActionRepository.open(tmp_path / "actions.db") as actions,
        SqliteTaskRepository.open(tmp_path / "tasks.db") as tasks,
        SqliteContextSnapshotRepository.open(tmp_path / "context.db") as snapshots,
        SqliteMemoryRepository.open(tmp_path / "memory.db") as memories,
    ):
        context = build_context_engine(settings, snapshots)
        return _build_proactivity(
            settings,
            store=store,
            actions=actions,
            tasks=tasks,
            context=context,
            memories=memories,
            skills=SkillRegistry(),
        )


class TestTasksCommand:
    def test_list_with_nothing_pending(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["tasks", "list"]) == 0
        assert "nenhuma tarefa pendente" in capsys.readouterr().out

    def test_run_due_with_nothing_due(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["tasks", "run-due"]) == 0
        assert "nenhuma tarefa devida" in capsys.readouterr().out

    def test_show_unknown_task_is_invalid_input(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["tasks", "show", "does-not-exist"]) == 2
        assert "não encontrada" in capsys.readouterr().err

    def test_cancel_unknown_task_reports_an_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["tasks", "cancel", "does-not-exist"]) == 2
        assert "erro" in capsys.readouterr().err

    def test_without_a_subcommand_prints_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["tasks"]) == 0
        assert "usage: jarvis tasks" in capsys.readouterr().out


class TestTasksRunDueClosesTheLoop:
    """Fase 9.1: o desfecho de uma tarefa liquidada volta a alimentar o
    Agent Runtime — o mesmo mecanismo que `agent ask --execute` já usa,
    agora também no caminho assíncrono do Background Task Manager."""

    def test_a_denied_task_produces_a_second_decision(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        settings = Settings()
        with SqliteTaskRepository.open(task_store_path(settings)) as repository:
            TaskManager(repository=repository).submit(
                ActionRequest(skill="not.a.real.skill", correlation_id="corr-task-1")
            )

        provider = StubLLMProvider([decision_json(type="notify", reason="a tarefa falhou, aviso")])
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)

        assert main(["tasks", "run-due"]) == 0
        capsys.readouterr()

        assert main(["decisions", "list", "--correlation-id", "corr-task-1"]) == 0
        out = capsys.readouterr().out
        assert "notify" in out
        assert "a tarefa falhou, aviso" in out
        assert len(provider.requests) == 1

    def test_a_succeeded_task_does_not_pay_for_a_second_call(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        settings = Settings()
        with SqliteTaskRepository.open(task_store_path(settings)) as repository:
            TaskManager(repository=repository).submit(
                ActionRequest(skill="system.status", correlation_id="corr-task-2")
            )

        provider = StubLLMProvider([decision_json(type="notify", message="não deveria aparecer")])
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)

        assert main(["tasks", "run-due"]) == 0
        capsys.readouterr()

        assert main(["decisions", "list", "--correlation-id", "corr-task-2"]) == 0
        out = capsys.readouterr().out
        assert "nenhuma decisão encontrada" in out
        assert provider.requests == []


class TestDecisionsCommand:
    def test_list_with_nothing_recorded(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["decisions", "list"]) == 0
        assert "nenhuma decisão encontrada" in capsys.readouterr().out


class TestInfoCommand:
    def test_shows_proactivity_and_notify_status(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["info"]) == 0
        out = capsys.readouterr().out
        assert "proactivity   enabled=não" in out
        assert "notify        silent=não" in out
        assert "task_store" in out


class TestBuildTriggerEngine:
    def test_empty_configuration_never_matches(self) -> None:
        engine = build_trigger_engine(Settings())
        assert engine.rules == ()

    def test_configured_types_produce_a_rule(self) -> None:
        settings = Settings(proactivity_trigger_event_types="printer.job_completed,email.received")
        engine = build_trigger_engine(settings)
        assert len(engine.rules) == 1
        assert engine.rules[0].event_types == frozenset({"printer.job_completed", "email.received"})


class TestBuildConditionEngine:
    def test_no_rules_path_means_no_rules(self) -> None:
        engine = build_condition_engine(Settings())
        assert engine.rules == ()

    def test_loads_rules_from_the_configured_path(self, tmp_path: Path) -> None:
        path = tmp_path / "rules.json"
        path.write_text(
            json.dumps(
                [
                    {
                        "rule_id": "r1",
                        "when": ["demo.happened"],
                        "condition": {"op": "always"},
                        "then": {"skill": "test.skill"},
                    }
                ]
            ),
            encoding="utf-8",
        )
        settings = Settings(proactivity_rules_path=path)
        engine = build_condition_engine(settings)
        assert len(engine.rules) == 1


class TestBuildNotificationManager:
    def test_silent_mode_is_wired_from_settings(self) -> None:
        manager = build_notification_manager(Settings(notify_silent_mode=True))
        outcome = manager.notify(
            Notification(
                notification_id="n1",
                subject="x",
                title="t",
                body="b",
                priority=NotificationPriority.NORMAL,
                correlation_id="c1",
                created_at=NOW,
            ),
            importance=1.0,
            context=CurrentContext(as_of=NOW),
        )
        assert outcome.delivered is False
        assert outcome.decision.suppressed_by == "silent_mode"


class TestBuildTaskManager:
    def test_wires_settings_into_the_manager(self, tmp_path: Path) -> None:
        with SqliteTaskRepository.open(tmp_path / "tasks.db") as repository:
            manager = build_task_manager(
                Settings(tasks_max_attempts=7, tasks_retry_base_delay_seconds=5.0),
                repository=repository,
            )
            assert manager is not None


class TestTriggerCallbackClosesTheLoop:
    """Fase 9.1, caminho proativo: uma ação submetida por `on_match` que não
    conclui também gera uma segunda decisão, exatamente como o caminho
    síncrono e o Background Task Manager (`TestTasksRunDueClosesTheLoop`)."""

    def test_a_denied_proactive_action_produces_a_second_decision_and_notifies(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from jarvis.decisions.query import project_decisions
        from jarvis.events.event import Event, RecordedEvent, new_event_id
        from jarvis.notify.manager import NotificationManager
        from jarvis.proactivity import InterruptionPolicy, InterruptionSettings
        from jarvis.proactivity.triggers import TriggerRule
        from tests.notify_doubles import FakeChannel

        settings = Settings(
            data_dir=tmp_path,
            proactivity_enabled=True,
            proactivity_execute_actions=True,
            proactivity_trigger_event_types="printer.job_completed",
            agent_importance_threshold=0.0,
        )
        provider = StubLLMProvider(
            [
                decision_json(type="act", message=None, action={"skill": "not.a.real.skill"}),
                decision_json(
                    type="notify", reason="a ação proativa falhou, aviso", message="ação falhou"
                ),
            ]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)

        with (
            SqliteEventStore.open(tmp_path / "events.db") as store,
            SqliteActionRepository.open(tmp_path / "actions.db") as actions,
            SqliteTaskRepository.open(tmp_path / "tasks.db") as tasks,
            SqliteContextSnapshotRepository.open(tmp_path / "context.db") as snapshots,
            SqliteMemoryRepository.open(tmp_path / "memory.db") as memories,
        ):
            context = build_context_engine(settings, snapshots)
            skills = SkillRegistry()
            proactivity = _build_proactivity(
                settings,
                store=store,
                actions=actions,
                tasks=tasks,
                context=context,
                memories=memories,
                skills=skills,
            )
            # Canal programável, limiar baixo de propósito: este teste prova
            # a entrega mecânica da segunda notificação (Fase 9.4: "→
            # notificação" fecha o loop de 9.1), não a calibração numérica do
            # Importance Engine — mesmo critério de
            # `test_full_reasoning_path_produces_decision_notification_and_action`.
            channel = FakeChannel()
            proactivity.notifications = NotificationManager(
                channels=[channel],
                interruption_policy=InterruptionPolicy(
                    InterruptionSettings(importance_threshold=0.0)
                ),
            )
            on_match = cli._make_trigger_callback(
                settings,
                store=store,
                context=context,
                memories=memories,
                skills=skills,
                actions=actions,
                proactivity=proactivity,
            )
            event = Event(
                event_id=new_event_id(),
                event_type="printer.job_completed",
                source="test",
                occurred_at=NOW,
                payload={},
            )
            recorded = RecordedEvent(event=event, recorded_at=NOW)
            rule = TriggerRule(trigger_id="t1", event_types=frozenset({event.event_type}))
            on_match(recorded, rule)

            records = project_decisions(store.read_latest(limit=20))

        assert len(records) == 2
        assert records[0].decision_type == "act"
        assert records[1].decision_type == "notify"
        assert len(channel.sent) == 1
        assert channel.sent[0].body == "ação falhou"
        assert records[1].reason == "a ação proativa falhou, aviso"
        assert len(provider.requests) == 2


class TestBuildProactivity:
    def test_disabled_by_default_subscribes_only_logging_and_confirmations(
        self, tmp_path: Path
    ) -> None:
        proactivity = _build(Settings(data_dir=tmp_path), tmp_path=tmp_path)
        assert len(proactivity.bus._subscriptions) == 2

    def test_enabled_with_a_trigger_adds_a_subscription(self, tmp_path: Path) -> None:
        settings = Settings(
            data_dir=tmp_path,
            proactivity_enabled=True,
            proactivity_trigger_event_types="demo.happened",
        )
        proactivity = _build(settings, tmp_path=tmp_path)
        assert len(proactivity.bus._subscriptions) == 3

    def test_enabled_without_any_trigger_or_rule_adds_nothing(self, tmp_path: Path) -> None:
        settings = Settings(data_dir=tmp_path, proactivity_enabled=True)
        proactivity = _build(settings, tmp_path=tmp_path)
        assert len(proactivity.bus._subscriptions) == 2
