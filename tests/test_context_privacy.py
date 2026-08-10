"""Nenhum valor de contexto pode aparecer em log, em nenhum caminho.

Contexto carrega dado pessoal em potencial, e log é o lugar mais fácil de vazá-lo
(`PHASE-2.md §11`). Este arquivo planta valores reconhecíveis e assere a ausência
deles em **todos** os caminhos que emitem log: merge, conflito, evento aplicado,
evento recusado, falha de provider, captura e expiração de snapshot.
"""

import logging
from datetime import UTC, datetime, timedelta

import pytest

from jarvis.context.aggregator import ContextAggregator
from jarvis.context.engine import ContextEngine
from jarvis.context.errors import InvalidContextError
from jarvis.context.model import ContextUpdate
from tests.context_doubles import (
    FailingProvider,
    FakeSnapshotRepository,
    StubProvider,
    frozen_clock,
    make_observation,
)
from tests.factories import make_event, make_recorded_event

NOON = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
LATER = NOON + timedelta(hours=1)

# Valores que só podem existir na memória do processo — nunca no log.
SECRET_PLACE = "casa-da-marina"
SECRET_DEVICE = "notebook-da-marina"
SECRET_ACTIVITY = "consulta-medica"


@pytest.fixture(autouse=True)
def capture_everything(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.DEBUG, logger="jarvis.context")
    return caplog


def assert_no_secrets(caplog: pytest.LogCaptureFixture) -> None:
    for secret in (SECRET_PLACE, SECRET_DEVICE, SECRET_ACTIVITY):
        assert secret not in caplog.text


def test_merge_and_conflict_never_log_values(caplog: pytest.LogCaptureFixture) -> None:
    aggregator = ContextAggregator(clock=frozen_clock(NOON))

    aggregator.apply(ContextUpdate(place=make_observation(SECRET_PLACE, observed_at=NOON)))
    conflicts = aggregator.apply(
        ContextUpdate(place=make_observation("work", observed_at=LATER, source="provider:other"))
    )

    assert len(conflicts) == 1
    assert "context.conflict" in caplog.text
    assert_no_secrets(caplog)


def test_provider_failure_logs_only_identity(caplog: pytest.LogCaptureFixture) -> None:
    aggregator = ContextAggregator(
        providers=[FailingProvider(name="location")], clock=frozen_clock(NOON)
    )

    aggregator.refresh()

    assert "context.provider_failed" in caplog.text
    assert_no_secrets(caplog)


def test_applying_an_event_never_logs_its_payload(caplog: pytest.LogCaptureFixture) -> None:
    aggregator = ContextAggregator(clock=frozen_clock(NOON))
    engine = ContextEngine(aggregator=aggregator, snapshots=FakeSnapshotRepository())

    engine.consumer.handle(
        make_recorded_event(
            make_event(
                event_type="user.activity_started",
                occurred_at=NOON,
                payload={"activity": SECRET_ACTIVITY},
            ),
            recorded_at=NOON,
        )
    )

    assert "context.event_applied" in caplog.text
    assert_no_secrets(caplog)


def test_a_refused_payload_never_reaches_the_log(caplog: pytest.LogCaptureFixture) -> None:
    """O erro vira stack trace no bus: a mensagem não pode repetir o valor."""
    aggregator = ContextAggregator(clock=frozen_clock(NOON))
    engine = ContextEngine(aggregator=aggregator, snapshots=FakeSnapshotRepository())

    with pytest.raises(InvalidContextError) as exc_info:
        engine.consumer.handle(
            make_recorded_event(
                make_event(
                    event_type="user.activity_started",
                    occurred_at=NOON,
                    payload={"activity": "Consulta com Dra. Marina"},
                ),
                recorded_at=NOON,
            )
        )

    assert "Marina" not in str(exc_info.value)
    assert_no_secrets(caplog)


def test_snapshot_capture_and_expiration_log_only_counts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    aggregator = ContextAggregator(
        providers=[
            StubProvider(
                ContextUpdate(
                    place=make_observation(SECRET_PLACE, observed_at=NOON),
                    device_id=make_observation(SECRET_DEVICE, observed_at=NOON),
                )
            )
        ],
        clock=frozen_clock(NOON),
    )
    engine = ContextEngine(
        aggregator=aggregator, snapshots=FakeSnapshotRepository(), clock=frozen_clock(NOON)
    )
    engine.refresh()

    captured = engine.capture_snapshot()
    engine.expire_before(LATER)

    assert captured is not None
    assert "context.snapshot_captured" in caplog.text
    assert "context.snapshots_expired" in caplog.text
    assert_no_secrets(caplog)


def test_the_fingerprint_does_not_expose_values() -> None:
    aggregator = ContextAggregator(clock=frozen_clock(NOON))
    aggregator.apply(ContextUpdate(place=make_observation(SECRET_PLACE, observed_at=NOON)))
    engine = ContextEngine(
        aggregator=aggregator, snapshots=FakeSnapshotRepository(), clock=frozen_clock(NOON)
    )

    captured = engine.capture_snapshot()

    assert captured is not None
    assert SECRET_PLACE not in captured.fingerprint()
