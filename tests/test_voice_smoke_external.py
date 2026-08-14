"""Smoke test contra Groq e Google Cloud TTS reais.

**Fora da suíte padrão** (`addopts = -m 'not external'`). Roda sob demanda:

```bash
uv run pytest -m external
```

Exige `JARVIS_GROQ_API_KEY` e `JARVIS_GOOGLE_TTS_API_KEY`, rede e quota. Existe
pelo mesmo motivo do smoke do Gemini: os testes com `opener` provam que o adapter
monta o corpo certo e traduz o erro certo, mas não provam que o **contrato do
serviço** continua o que era. Só uma chamada real prova isso, e ela não pode
morar na suíte que precisa passar sem credencial.

Não há teste automatizado de microfone ou alto-falante: não há como testar um
dispositivo sem o dispositivo, e um duplo de PortAudio testaria o duplo. Essa
verificação é manual (`jarvis voice devices`, `jarvis voice say`).
"""

import os

import pytest

from jarvis.voice.adapters.google_tts import GoogleCloudTextToSpeech
from jarvis.voice.adapters.groq_stt import GroqSpeechToText
from jarvis.voice.audio import PcmClip
from tests.voice_doubles import pcm_tone

pytestmark = pytest.mark.external


def _key(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        pytest.skip(f"{name} não configurada")
    return value


def test_the_synthesis_service_still_returns_playable_audio() -> None:
    tts = GoogleCloudTextToSpeech(api_key=_key("JARVIS_GOOGLE_TTS_API_KEY"))

    clip = tts.synthesize("Teste de integração do Jarvis.", timeout_seconds=20.0)

    assert clip.duration_seconds > 0.5
    assert clip.format.sample_width == 2


def test_the_transcription_service_still_accepts_our_multipart() -> None:
    # Um tom puro não tem palavras: o que se verifica aqui é que a requisição é
    # aceita e a resposta tem a forma esperada, não o conteúdo transcrito.
    stt = GroqSpeechToText(api_key=_key("JARVIS_GROQ_API_KEY"))

    transcript = stt.transcribe(PcmClip(data=pcm_tone(1.0)), timeout_seconds=30.0)

    assert transcript.duration_seconds == pytest.approx(1.0, abs=0.05)


def test_a_round_trip_puts_words_back_where_they_started() -> None:
    """Sintetiza uma frase e a transcreve de volta.

    É o teste que prova que os dois adapters conversam: o WAV que o Google
    devolve precisa ser exatamente o que a Groq aceita, sem conversão no meio.
    """
    tts = GoogleCloudTextToSpeech(api_key=_key("JARVIS_GOOGLE_TTS_API_KEY"))
    stt = GroqSpeechToText(api_key=_key("JARVIS_GROQ_API_KEY"))

    spoken = tts.synthesize("Que horas são agora?", timeout_seconds=20.0)
    heard = stt.transcribe(spoken, language="pt", timeout_seconds=30.0)

    assert "horas" in heard.text.lower()
