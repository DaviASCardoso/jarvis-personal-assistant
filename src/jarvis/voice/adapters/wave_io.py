"""WAV entra e sai daqui, e de nenhum outro lugar.

Duas pontas precisam de container em vez de PCM cru: a Groq recebe um arquivo no
multipart, e o Google devolve `LINEAR16` já embrulhado em RIFF. O módulo `wave`
da biblioteca padrão resolve as duas, o que mantém a fase sem dependência de
codec.

**Nada é convertido em silêncio.** Um WAV estéreo, de 8 bits ou comprimido é
recusado com `AudioFormatError` em vez de reamostrado: conversão escondida é como
um pipeline de áudio começa a mentir sobre o que ouviu.
"""

import io
import wave

from jarvis.voice.audio import AudioFormat, PcmClip
from jarvis.voice.errors import AudioFormatError, InvalidVoiceInputError


def encode_wav(clip: PcmClip) -> bytes:
    """Embrulha o PCM num container RIFF."""
    buffer = io.BytesIO()
    try:
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(clip.format.channels)
            handle.setsampwidth(clip.format.sample_width)
            handle.setframerate(clip.format.sample_rate)
            handle.writeframes(clip.data)
    except (wave.Error, OSError, ValueError) as error:
        raise AudioFormatError("não foi possível gerar o WAV") from error
    return buffer.getvalue()


def decode_wav(data: bytes) -> PcmClip:
    """Lê um WAV e devolve o PCM, com o formato que o próprio arquivo declara."""
    try:
        with wave.open(io.BytesIO(data), "rb") as handle:
            channels = handle.getnchannels()
            width = handle.getsampwidth()
            rate = handle.getframerate()
            frames = handle.readframes(handle.getnframes())
    except (wave.Error, OSError, ValueError, EOFError) as error:
        raise AudioFormatError("o conteúdo não é um WAV legível") from error

    try:
        audio_format = AudioFormat(sample_rate=rate, channels=channels, sample_width=width)
        return PcmClip(data=frames, format=audio_format)
    except InvalidVoiceInputError as error:
        # A violação é do arquivo recebido, não de uma chamada interna — por isso
        # sobe como erro de infraestrutura, e com a razão preservada.
        raise AudioFormatError(f"WAV fora do formato suportado: {error}") from error
