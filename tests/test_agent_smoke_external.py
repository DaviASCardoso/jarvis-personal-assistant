"""Smoke test contra a API real do Gemini — **fora da suíte padrão**.

`addopts` em `pyproject.toml` inclui `-m "not external"`, então este arquivo não
roda em `uv run pytest` nem no CI. Rodar sob demanda:

```bash
uv run pytest -m external
```

Existe por um motivo específico que nenhum fake cobre: confirmar que o corpo
que montamos é aceito pelo serviço de verdade e que o formato de resposta
continua o que o adapter espera. Um contrato de API é a única coisa que muda
sem que nada neste repositório mude.
"""

import os
from datetime import UTC, datetime

import pytest

from jarvis.agent.adapters.gemini import GeminiLLMProvider
from jarvis.agent.decision import parse_decision
from jarvis.agent.input import UserMessage
from jarvis.agent.messages import ResponseFormat, StopReason
from jarvis.agent.prompt import PromptBuilder, ReasoningEnvelope
from jarvis.context.model import CurrentContext

pytestmark = [
    pytest.mark.external,
    pytest.mark.skipif(
        not os.environ.get("JARVIS_GEMINI_API_KEY"),
        reason="smoke test externo: exige JARVIS_GEMINI_API_KEY e rede",
    ),
]


def test_a_real_turn_produces_a_valid_decision() -> None:
    now = datetime.now(UTC)
    provider = GeminiLLMProvider(
        api_key=os.environ["JARVIS_GEMINI_API_KEY"],
        model=os.environ.get("JARVIS_GEMINI_MODEL", "gemini-2.0-flash"),
    )
    request = PromptBuilder().build(
        ReasoningEnvelope(
            now=now,
            trigger=UserMessage(text="me diga apenas olá", at=now, conversation_id="smoke"),
            context=CurrentContext(as_of=now),
        ),
        timeout_seconds=60.0,
    )
    assert request.response_format is ResponseFormat.JSON_OBJECT

    response = provider.generate(request)

    assert response.stop_reason is not StopReason.BLOCKED
    decision = parse_decision(
        response.text, decision_id="smoke", correlation_id="smoke", decided_at=now
    )
    assert decision.reason
