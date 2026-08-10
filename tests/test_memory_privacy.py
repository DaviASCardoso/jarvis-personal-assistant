"""Nenhum conteúdo de memória pode aparecer em log, em nenhum caminho.

`PHASE-3.md §16`: memória guarda dado pessoal em potencial — "não registrar
conteúdo sensível em logs", "não colocar memória inteira em mensagens de erro".
Este arquivo planta valores reconhecíveis e assere a ausência deles em
**todos** os caminhos que emitem log: falha de embedding, falha de reembed,
consolidação, purge, consumo de evento (aplicado e recusado).
"""

import logging
from datetime import UTC, datetime, timedelta

import pytest

from jarvis.memory.adapters.event_consumer import MemoryEventConsumer
from jarvis.memory.adapters.sqlite_repository import IN_MEMORY_DATABASE, SqliteMemoryRepository
from jarvis.memory.embedding import EmbeddingModel
from jarvis.memory.errors import InvalidMemoryError
from jarvis.memory.manager import MemoryManager
from jarvis.memory.memory import MemoryOrigin, MemoryType, Provenance, content_fingerprint
from tests.factories import make_event, make_recorded_event
from tests.memory_doubles import (
    FailingEmbeddingProvider,
    FakeMemoryRepository,
    frozen_clock,
    make_embedding,
)

NOON = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
LATER = NOON + timedelta(hours=1)

# Conteúdo que só pode existir na memória do processo — nunca no log.
SECRET_CONTENT = "consulta com a Dra. Marina às 15h"
SECRET_SUBJECT_CONTENT = "prefere-remedio-x-para-enxaqueca"


@pytest.fixture(autouse=True)
def capture_everything(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.DEBUG, logger="jarvis.memory")
    return caplog


def assert_no_secret(caplog: pytest.LogCaptureFixture) -> None:
    assert SECRET_CONTENT not in caplog.text
    assert "Marina" not in caplog.text


def test_embedding_failure_logs_only_identity(caplog: pytest.LogCaptureFixture) -> None:
    manager = MemoryManager(
        repository=FakeMemoryRepository(),
        embeddings=FailingEmbeddingProvider(),
        clock=frozen_clock(NOON),
    )

    manager.remember(
        type=MemoryType.EPISODIC,
        content=SECRET_CONTENT,
        provenance=Provenance(origin=MemoryOrigin.USER),
    )

    assert "memory.embedding_failed" in caplog.text
    assert_no_secret(caplog)


def test_reembed_failure_logs_only_identity(caplog: pytest.LogCaptureFixture) -> None:
    repository = FakeMemoryRepository()
    manager = MemoryManager(repository=repository, clock=frozen_clock(NOON, LATER))
    stored = manager.remember(
        type=MemoryType.EPISODIC,
        content=SECRET_CONTENT,
        provenance=Provenance(origin=MemoryOrigin.USER),
        embed=False,
    )
    old_model = EmbeddingModel(provider="old", model="v1", dimensions=4)
    repository.replace_embedding(
        stored.memory.memory_id, make_embedding(model=old_model), moment=NOON
    )

    manager.reembed(embeddings=FailingEmbeddingProvider())

    assert "memory.reembed_failed" in caplog.text
    assert_no_secret(caplog)


def test_consolidation_logs_only_a_count(caplog: pytest.LogCaptureFixture) -> None:
    manager = MemoryManager(repository=FakeMemoryRepository(), clock=frozen_clock(NOON))
    for reference in ("evt-1", "evt-2", "evt-3"):
        manager.remember(
            type=MemoryType.EPISODIC,
            content=SECRET_CONTENT,
            provenance=Provenance(origin=MemoryOrigin.EVENT, reference=reference),
            subject="pattern.secret",
        )

    manager.consolidate()

    assert "memory.consolidated" in caplog.text
    assert_no_secret(caplog)


def test_purge_logs_only_the_memory_id(caplog: pytest.LogCaptureFixture) -> None:
    with SqliteMemoryRepository.open(IN_MEMORY_DATABASE, clock=lambda: NOON) as repository:
        manager = MemoryManager(repository=repository, clock=frozen_clock(NOON))
        stored = manager.remember(
            type=MemoryType.EPISODIC,
            content=SECRET_CONTENT,
            provenance=Provenance(origin=MemoryOrigin.USER),
        )

        manager.purge(stored.memory.memory_id)

    assert "memory.purged" in caplog.text
    assert_no_secret(caplog)


def test_applying_an_event_never_logs_its_payload(caplog: pytest.LogCaptureFixture) -> None:
    manager = MemoryManager(repository=FakeMemoryRepository(), clock=frozen_clock(NOON))
    consumer = MemoryEventConsumer(manager)

    consumer.handle(
        make_recorded_event(
            make_event(
                event_type="user.noted_fact",
                occurred_at=NOON,
                payload={"content": SECRET_CONTENT},
            ),
            recorded_at=NOON,
        )
    )

    assert "memory.event_applied" in caplog.text
    assert_no_secret(caplog)


def test_a_refused_payload_never_reaches_the_log(caplog: pytest.LogCaptureFixture) -> None:
    """O erro vira stack trace no bus: a mensagem não pode repetir o conteúdo."""
    manager = MemoryManager(repository=FakeMemoryRepository(), clock=frozen_clock(NOON))
    consumer = MemoryEventConsumer(manager)

    with pytest.raises(InvalidMemoryError) as exc_info:
        consumer.handle(
            make_recorded_event(
                make_event(
                    event_type="user.stated_preference",
                    occurred_at=NOON,
                    payload={"subject": "Not A Valid Slug", "content": SECRET_CONTENT},
                ),
                recorded_at=NOON,
            )
        )

    assert "Not A Valid Slug" not in str(exc_info.value)
    assert_no_secret(caplog)


def test_the_fingerprint_does_not_expose_the_content() -> None:
    fingerprint = content_fingerprint(SECRET_SUBJECT_CONTENT)

    assert SECRET_SUBJECT_CONTENT not in fingerprint
    assert len(fingerprint) == 64
