"""Agent Runtime: o núcleo de raciocínio do Jarvis.

API pública do componente. As implementações concretas de `LLMProvider` ficam em
`jarvis.agent.adapters` e são escolhidas pelo composition root, não importadas
por quem apenas usa o Core.

A regra que organiza tudo aqui: **o Agent Runtime propõe, nunca executa**. A
saída é uma `Decision` — dado inerte. Quem autoriza é o Policy Engine (Fase 5)
([ADR-0003](../../../docs/adr/0003-policy-engine-safety-authority.md)).

Documentação: [`docs/agent-runtime.md`](../../../docs/agent-runtime.md).
"""

from jarvis.agent.conversation import Conversation, ConversationTurn
from jarvis.agent.decision import (
    ActionProposal,
    Decision,
    DecisionType,
    MemoryProposal,
    new_decision_id,
    parse_decision,
)
from jarvis.agent.errors import (
    InvalidDecisionError,
    InvalidLLMRequestError,
    LLMAuthenticationError,
    LLMInvalidResponseError,
    LLMProviderError,
    LLMRateLimitError,
    LLMRequestRejectedError,
    LLMTimeoutError,
    PromptTooLargeError,
)
from jarvis.agent.importance import (
    DEFAULT_IMPORTANCE_WEIGHTS,
    ImportanceAssessment,
    ImportanceWeights,
    assess,
    should_reason,
)
from jarvis.agent.input import (
    ActionResultSummary,
    AgentInput,
    EventSummary,
    EventTrigger,
    UserMessage,
)
from jarvis.agent.messages import (
    LLMModel,
    LLMRequest,
    LLMResponse,
    Message,
    ResponseFormat,
    Role,
    StopReason,
    TokenUsage,
)
from jarvis.agent.ports import LLMProvider
from jarvis.agent.prompt import (
    DEFAULT_BUDGET,
    SYSTEM_INSTRUCTION,
    Capability,
    PromptBudget,
    PromptBuilder,
    ReasoningEnvelope,
)
from jarvis.agent.runtime import (
    AgentRuntime,
    AgentTurn,
    GenerationDefaults,
    LLMRetryPolicy,
)

__all__ = [
    "DEFAULT_BUDGET",
    "DEFAULT_IMPORTANCE_WEIGHTS",
    "SYSTEM_INSTRUCTION",
    "ActionProposal",
    "ActionResultSummary",
    "AgentInput",
    "AgentRuntime",
    "AgentTurn",
    "Capability",
    "Conversation",
    "ConversationTurn",
    "Decision",
    "DecisionType",
    "EventSummary",
    "EventTrigger",
    "GenerationDefaults",
    "ImportanceAssessment",
    "ImportanceWeights",
    "InvalidDecisionError",
    "InvalidLLMRequestError",
    "LLMAuthenticationError",
    "LLMInvalidResponseError",
    "LLMModel",
    "LLMProvider",
    "LLMProviderError",
    "LLMRateLimitError",
    "LLMRequest",
    "LLMRequestRejectedError",
    "LLMResponse",
    "LLMRetryPolicy",
    "LLMTimeoutError",
    "MemoryProposal",
    "Message",
    "PromptBudget",
    "PromptBuilder",
    "PromptTooLargeError",
    "ReasoningEnvelope",
    "ResponseFormat",
    "Role",
    "StopReason",
    "TokenUsage",
    "UserMessage",
    "assess",
    "new_decision_id",
    "parse_decision",
    "should_reason",
]
