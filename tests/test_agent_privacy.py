"""Nada sensível pode sair pelo log, pela mensagem de erro ou pelo prompt.

Três fronteiras distintas, cada uma com um jeito diferente de vazar:

1. **credencial** — só existe no adapter e no composition root; não pode
   aparecer em log, erro, `repr` de `Settings` nem em nenhuma `LLMRequest`;
2. **conteúdo do usuário** (memória, payload, mensagem) — pode ir ao provider,
   porque é o objeto do raciocínio, mas **nunca** ao log;
3. **payload de eventos recentes** — não vai nem ao provider: só o gatilho
   justifica mandar conteúdo para fora do dispositivo.
"""

import logging

import pytest

from jarvis.agent.errors import LLMProviderError
from jarvis.agent.input import EventSummary
from jarvis.agent.ports import LLMProvider
from jarvis.agent.prompt import PromptBuilder, ReasoningEnvelope
from jarvis.agent.runtime import AgentRuntime, GenerationDefaults, LLMRetryPolicy
from jarvis.config import Settings
from jarvis.memory.adapters.hashing_embeddings import HashingEmbeddingProvider
from jarvis.memory.manager import MemoryManager
from jarvis.memory.memory import MemoryOrigin, MemoryType, Provenance
from tests.agent_doubles import (
    NOON,
    FailingLLMProvider,
    StubLLMProvider,
    decision_json,
    failing_opener,
    fake_opener,
    http_error,
    make_context,
    make_event_trigger,
    make_user_message,
)
from tests.memory_doubles import FakeMemoryRepository, frozen_clock

# Valores que só podem existir na memória do processo — nunca no log.
API_KEY = "AIza-CHAVE-SECRETA-NUNCA-LOGAR"
SECRET_CONTENT = "consulta com a Dra. Marina às 15h"
SECRET_PAYLOAD = "o extrato do banco fechou em 1234"


@pytest.fixture(autouse=True)
def capture_everything(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.DEBUG, logger="jarvis.agent")
    return caplog


def assert_nothing_leaked(caplog: pytest.LogCaptureFixture) -> None:
    assert API_KEY not in caplog.text
    assert SECRET_CONTENT not in caplog.text
    assert "Marina" not in caplog.text
    assert SECRET_PAYLOAD not in caplog.text


def memory_with_secret() -> MemoryManager:
    manager = MemoryManager(
        repository=FakeMemoryRepository(),
        embeddings=HashingEmbeddingProvider(),
        clock=frozen_clock(NOON),
    )
    manager.remember(
        type=MemoryType.EPISODIC,
        content=SECRET_CONTENT,
        provenance=Provenance(origin=MemoryOrigin.USER),
    )
    return manager


def build(llm: LLMProvider) -> AgentRuntime:
    return AgentRuntime(
        llm=llm,
        context_reader=lambda: make_context(as_of=NOON, availability="free"),
        memory=memory_with_secret(),
        importance_threshold=0.0,
        retry=LLMRetryPolicy(max_attempts=2),
        generation=GenerationDefaults(),
        clock=frozen_clock(NOON),
        sleep=lambda seconds: None,
        monotonic=lambda: 0.0,
    )


# --- credencial --------------------------------------------------------------


def test_settings_never_reveal_the_key_in_repr_or_str() -> None:
    settings = Settings(gemini_api_key=API_KEY)  # type: ignore[arg-type]

    assert API_KEY not in repr(settings)
    assert API_KEY not in str(settings)
    assert API_KEY not in str(settings.model_dump())
    assert settings.gemini_api_key is not None
    assert settings.gemini_api_key.get_secret_value() == API_KEY


def test_the_key_never_enters_the_prompt() -> None:
    """O runtime não recebe `Settings` — recebe valores já resolvidos. Este
    teste é o que torna essa decisão verificável."""
    llm = StubLLMProvider()

    build(llm).handle(make_user_message(text="oi"))

    request = llm.requests[0]
    whole = request.system + "".join(message.content for message in request.messages)
    assert API_KEY not in whole


def test_a_provider_failure_never_logs_the_key(caplog: pytest.LogCaptureFixture) -> None:
    from jarvis.agent.adapters.gemini import GeminiLLMProvider

    provider = GeminiLLMProvider(
        api_key=API_KEY, model="gemini-test", opener=failing_opener(http_error(500))
    )

    with pytest.raises(LLMProviderError):
        build(provider).handle(make_user_message())

    assert_nothing_leaked(caplog)


def test_a_successful_call_never_logs_the_key(caplog: pytest.LogCaptureFixture) -> None:
    from jarvis.agent.adapters.gemini import GeminiLLMProvider

    provider = GeminiLLMProvider(api_key=API_KEY, model="gemini-test", opener=fake_opener())

    build(provider).handle(make_user_message())

    assert "agent.llm_called" in caplog.text
    assert_nothing_leaked(caplog)


# --- conteúdo ----------------------------------------------------------------


def test_a_normal_turn_logs_identity_not_content(caplog: pytest.LogCaptureFixture) -> None:
    llm = StubLLMProvider([decision_json(type="notify", message=SECRET_CONTENT)])

    build(llm).handle(make_user_message(text=SECRET_CONTENT))

    assert "agent.decided" in caplog.text
    assert_nothing_leaked(caplog)


def test_an_event_payload_never_reaches_the_log(caplog: pytest.LogCaptureFixture) -> None:
    llm = StubLLMProvider()
    trigger = make_event_trigger(payload={"detail": SECRET_PAYLOAD})

    build(llm).handle(trigger)

    assert_nothing_leaked(caplog)


def test_a_skipped_event_logs_scores_not_content(caplog: pytest.LogCaptureFixture) -> None:
    runtime = AgentRuntime(
        llm=StubLLMProvider(),
        context_reader=lambda: make_context(as_of=NOON, availability="busy"),
        memory=memory_with_secret(),
        importance_threshold=1.0,
        clock=frozen_clock(NOON),
    )

    runtime.handle(make_event_trigger(payload={"detail": SECRET_PAYLOAD}))

    assert "agent.triage_skipped" in caplog.text
    assert_nothing_leaked(caplog)


def test_an_invalid_response_logs_its_size_not_its_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """O texto do modelo pode ecoar o payload que acabou de receber."""
    llm = StubLLMProvider([f"não entendi, mas {SECRET_CONTENT}", decision_json()])

    build(llm).handle(make_user_message())

    reported = next(record for record in caplog.records if record.msg == "agent.decision_invalid")
    assert hasattr(reported, "response_chars"), "o tamanho substitui o texto no log"
    assert_nothing_leaked(caplog)


def test_a_retry_logs_the_error_type_not_the_message_body(
    caplog: pytest.LogCaptureFixture,
) -> None:
    llm = FailingLLMProvider(LLMProviderError(f"falhou processando {SECRET_CONTENT}"), fail_times=1)

    build(llm).handle(make_user_message())

    assert "agent.llm_failed" in caplog.text
    assert_nothing_leaked(caplog)


def test_prompt_trimming_logs_counts_not_content(caplog: pytest.LogCaptureFixture) -> None:
    from jarvis.agent.conversation import Conversation, ConversationTurn
    from jarvis.agent.messages import Role
    from jarvis.agent.prompt import PromptBudget

    conversation = Conversation(conversation_id="c-1")
    for _ in range(4):
        conversation = conversation.append(
            ConversationTurn(role=Role.USER, text=f"{SECRET_CONTENT} {'x' * 300}", at=NOON)
        )

    PromptBuilder(budget=PromptBudget(max_envelope_chars=1200)).build(
        ReasoningEnvelope(
            now=NOON,
            trigger=make_user_message(),
            context=make_context(as_of=NOON),
            conversation=conversation,
        )
    )

    assert "agent.prompt_trimmed" in caplog.text
    assert_nothing_leaked(caplog)


# --- o que não sai do dispositivo -------------------------------------------


def test_recent_event_payloads_never_leave_the_device() -> None:
    """`EventSummary` não tem campo de payload — a garantia é do tipo, não da
    disciplina de quem monta o envelope."""
    assert "payload" not in EventSummary.__dataclass_fields__

    llm = StubLLMProvider()
    summary = EventSummary(
        event_id="e-1", event_type="user.noted_fact", source="cli", occurred_at=NOON
    )

    build(llm).handle(make_user_message(), recent_events=(summary,))

    assert SECRET_PAYLOAD not in llm.requests[0].messages[0].content
