"""Erros da camada de voz.

Segue a taxonomia compartilhada de
[`architecture-contracts.md §13`](../../../docs/architecture-contracts.md#13-error-contract):
violação de invariante do domínio é permanente, falha de adapter é transitória por
padrão, e falha declarada por serviço externo é `ProviderError`.

Dois erros de infraestrutura sobrescrevem `retryable` para `False`, e a distinção
importa para o loop: um dispositivo que não existe não passa a existir na segunda
tentativa, enquanto um estouro momentâneo de buffer passa.
"""

from typing import ClassVar

from jarvis.errors import DomainError, InfrastructureError, ProviderError


class VoiceError(DomainError):
    """Violação de uma invariante da camada de voz."""


class InvalidVoiceInputError(VoiceError):
    """Áudio, texto ou formato que o domínio de voz recusa."""


class VoiceSessionError(VoiceError):
    """Uso inválido de uma sessão (turno em sessão fechada, ordinal repetido)."""


class AudioError(InfrastructureError):
    """Falha no caminho de captura ou reprodução de áudio."""


class AudioDeviceError(AudioError):
    """Dispositivo ausente, ocupado, ou backend de áudio não instalado.

    Permanente de propósito: repetir não faz aparecer um microfone. É também o
    erro que o composition root levanta quando o extra `voice` não está
    instalado — com a instrução de instalação na mensagem, porque descobrir isso
    por `ImportError` seria hostil.
    """

    retryable: ClassVar[bool] = False


class AudioFormatError(AudioError):
    """Formato de áudio que este pipeline não processa."""

    retryable: ClassVar[bool] = False


class VoiceRepositoryError(InfrastructureError):
    """Falha na persistência de sessões de voz."""


class SpeechToTextError(ProviderError):
    """Falha declarada por um `SpeechToText`."""


class SttTimeoutError(SpeechToTextError):
    """O provider de transcrição não respondeu dentro do orçamento."""


class SttRateLimitError(SpeechToTextError):
    """Limite de requisições atingido; `retry_after` vem do provider quando há."""

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class SttAuthenticationError(SpeechToTextError):
    retryable: ClassVar[bool] = False


class SttRejectedError(SpeechToTextError):
    """O provider recusou a requisição (áudio grande demais, parâmetro inválido)."""

    retryable: ClassVar[bool] = False


class SttInvalidResponseError(SpeechToTextError):
    """A resposta não é interpretável como transcrição."""

    retryable: ClassVar[bool] = False


class TextToSpeechError(ProviderError):
    """Falha declarada por um `TextToSpeech`."""


class TtsTimeoutError(TextToSpeechError):
    pass


class TtsRateLimitError(TextToSpeechError):
    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class TtsAuthenticationError(TextToSpeechError):
    retryable: ClassVar[bool] = False


class TtsRejectedError(TextToSpeechError):
    """O provider recusou a requisição (voz inexistente, texto longo demais)."""

    retryable: ClassVar[bool] = False


class TtsInvalidResponseError(TextToSpeechError):
    retryable: ClassVar[bool] = False
