from jarvis.errors import DomainError, InfrastructureError
from jarvis.memory.errors import (
    EmbeddingProviderError,
    InvalidMemoryError,
    MemoryReadError,
    MemoryRepositoryError,
    MemoryWriteError,
)


def test_invalid_memory_error_is_a_permanent_domain_error() -> None:
    assert issubclass(InvalidMemoryError, DomainError)
    assert InvalidMemoryError("x").retryable is False


def test_embedding_provider_error_is_retryable_infrastructure() -> None:
    assert issubclass(EmbeddingProviderError, InfrastructureError)
    assert EmbeddingProviderError("x").retryable is True


def test_repository_errors_are_retryable_infrastructure() -> None:
    assert issubclass(MemoryRepositoryError, InfrastructureError)
    assert issubclass(MemoryWriteError, MemoryRepositoryError)
    assert issubclass(MemoryReadError, MemoryRepositoryError)
    assert MemoryWriteError("x").retryable is True
    assert MemoryReadError("x").retryable is True
