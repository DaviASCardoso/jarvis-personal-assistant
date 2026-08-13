"""O consumer projeta a resposta do usuário. Ele nunca executa nada.

Um consumer que disparasse a execução ao receber a confirmação seria um caminho
lateral até a Tool, acionado por evento e sem passar de novo pelo Policy Engine.
Estes testes fixam que ele só mexe em estado.
"""

from datetime import UTC, datetime, timedelta

import pytest

from jarvis.events.event import RecordedEvent
from jarvis.execution.consumer import ActionEventConsumer
from jarvis.execution.errors import InvalidActionEventError
from jarvis.execution.events import confirmation_event
from jarvis.execution.model import Actor, ExecutionStatus, PendingAction
from tests.action_doubles import InMemoryActionRepository

NOON = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
FINGERPRINT = "f" * 64


def make_pending(**changes: object) -> PendingAction:
    fields: dict[str, object] = {
        "execution_id": "exec-1",
        "skill": "file.write",
        "parameters": {"path": "nota.txt"},
        "parameters_fingerprint": FINGERPRINT,
        "actor": Actor.USER,
        "correlation_id": "corr-1",
        "status": ExecutionStatus.AWAITING_CONFIRMATION,
        "requested_at": NOON,
        "updated_at": NOON,
        "expires_at": NOON + timedelta(minutes=15),
    }
    fields.update(changes)
    return PendingAction(**fields)  # type: ignore[arg-type]


def answer(*, granted: bool, fingerprint: str = FINGERPRINT, reason: str = "") -> RecordedEvent:
    return RecordedEvent(
        confirmation_event(
            granted=granted,
            execution_id="exec-1",
            parameters_fingerprint=fingerprint,
            correlation_id="corr-1",
            occurred_at=NOON,
            reason=reason,
        ),
        NOON,
    )


def test_a_granted_confirmation_is_recorded() -> None:
    repository = InMemoryActionRepository()
    repository.put(make_pending())

    ActionEventConsumer(repository).handle(answer(granted=True))

    stored = repository.get("exec-1")
    assert stored is not None
    assert stored.is_confirmed
    # O status **não** muda: retomar é um passo separado, e ele reavalia política.
    assert stored.status is ExecutionStatus.AWAITING_CONFIRMATION


def test_a_denied_confirmation_rejects_the_action() -> None:
    repository = InMemoryActionRepository()
    repository.put(make_pending())

    ActionEventConsumer(repository).handle(answer(granted=False, reason="mudei de ideia"))

    stored = repository.get("exec-1")
    assert stored is not None
    assert stored.status is ExecutionStatus.REJECTED
    assert stored.reason == "mudei de ideia"


def test_a_confirmation_for_other_parameters_is_refused() -> None:
    """Confirmar 'apagar A' nunca autoriza 'apagar B'."""
    repository = InMemoryActionRepository()
    repository.put(make_pending())

    with pytest.raises(InvalidActionEventError, match="não corresponde"):
        ActionEventConsumer(repository).handle(answer(granted=True, fingerprint="b" * 64))

    stored = repository.get("exec-1")
    assert stored is not None
    assert not stored.is_confirmed


def test_an_unknown_execution_is_refused() -> None:
    with pytest.raises(InvalidActionEventError, match="não registrada"):
        ActionEventConsumer(InMemoryActionRepository()).handle(answer(granted=True))


def test_a_late_confirmation_is_ignored_not_an_error() -> None:
    """Responder depois da expiração é um fato tardio, não um payload inválido."""
    repository = InMemoryActionRepository()
    repository.put(make_pending(status=ExecutionStatus.EXPIRED))

    ActionEventConsumer(repository).handle(answer(granted=True))

    stored = repository.get("exec-1")
    assert stored is not None
    assert stored.status is ExecutionStatus.EXPIRED
    assert not stored.is_confirmed


def test_a_malformed_payload_is_refused_without_echoing_it() -> None:
    from jarvis.events.event import Event

    repository = InMemoryActionRepository()
    repository.put(make_pending())
    broken = RecordedEvent(
        Event(
            event_id="evt-1",
            event_type="action.confirmation_granted",
            source="jarvis-cli",
            occurred_at=NOON,
            payload={"conteudo_sensivel": "consulta com a Dra. Marina"},
        ),
        NOON,
    )

    with pytest.raises(InvalidActionEventError) as error:
        ActionEventConsumer(repository).handle(broken)

    assert "Marina" not in str(error.value)


def test_the_consumer_has_a_name_for_the_bus() -> None:
    assert ActionEventConsumer(InMemoryActionRepository()).name == "action-confirmations"
