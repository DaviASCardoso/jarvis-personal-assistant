from jarvis.errors import DomainError, InfrastructureError, JarvisError
from jarvis.events.errors import (
    EventAppendError,
    EventReadError,
    EventStoreError,
    InvalidEventError,
)


def test_domain_errors_are_permanent() -> None:
    assert issubclass(InvalidEventError, DomainError)
    assert issubclass(DomainError, JarvisError)
    assert InvalidEventError.retryable is False


def test_store_errors_are_infrastructure_and_retryable() -> None:
    assert issubclass(EventStoreError, InfrastructureError)
    assert issubclass(EventAppendError, EventStoreError)
    assert issubclass(EventReadError, EventStoreError)

    assert EventAppendError.retryable is True
    assert EventReadError.retryable is True


def test_append_and_read_failures_are_distinguishable() -> None:
    assert not issubclass(EventAppendError, EventReadError)
    assert not issubclass(EventReadError, EventAppendError)
