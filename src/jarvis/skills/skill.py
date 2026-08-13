"""O modelo de domínio de Skill.

Uma Skill é "o que o Jarvis quer realizar"; uma Tool é "uma operação técnica que
pode ser executada" ([ADR-0005](../../../docs/adr/0005-skill-tool-mcp-distinction.md)).
A Skill é o lugar — o único — onde risco, permissão e política de confirmação são
declarados, mesmo quando ela compõe uma única Tool.

Duas ausências no `SkillHandler` valem mais que qualquer comentário sobre
segurança:

- ele **não** recebe o `PolicyEngine`, então não tem como se autorizar;
- ele **não** recebe o `ToolRouter`, e sim um `ToolAccess` já recortado para
  as ferramentas que a própria Skill declarou — que só é construído em
  `jarvis/execution`, depois de uma `PolicyApproval` consumida.

Nem Context nem Memory chegam aqui por busca: `architecture-contracts.md §3.6`
manda que cheguem como parâmetro explícito, e é por isso que `SkillInvocation`
não tem uma referência a nenhum dos dois.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final, Protocol

from jarvis.events.event import JsonValue
from jarvis.policy.vocabulary import (
    ConfirmationRequirement,
    Effect,
    Idempotency,
    InvalidPolicyVocabularyError,
    RiskLevel,
    require_capability,
)
from jarvis.skills.errors import SkillRegistryError
from jarvis.tools.access import ToolAccess
from jarvis.tools.errors import ToolInvalidInputError
from jarvis.tools.schema import ParameterSchema
from jarvis.tools.tool import ToolId, require_tool_id

MAX_SUMMARY_LENGTH: Final = 200
MAX_OUTPUT_SUMMARY_LENGTH: Final = 500

# Precisa aceitar exatamente o mesmo conjunto que `ActionProposal.skill` valida em
# `agent/decision.py` — um nome que o agente consegue propor mas o registry não
# consegue registrar seria um buraco silencioso entre as duas pontas. O padrão é
# duplicado, e não importado, porque `jarvis.skills` não pode depender de
# `jarvis.agent`; `tests/test_skill_registry.py` amarra os dois.
_NAME_PATTERN: Final = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")


def require_skill_name(value: str, *, field_name: str = "skill") -> str:
    if not _NAME_PATTERN.fullmatch(value):
        raise SkillRegistryError(f"{field_name} não casa com {_NAME_PATTERN.pattern}: {value!r}")
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class SkillDescriptor:
    """Tudo que se sabe sobre uma Skill sem executá-la.

    `risk`, `effects` e `confirmation_requirement` são **autodeclarações**. Elas
    entram na avaliação do Policy Engine como insumo e podem ser sobrepostas por
    ele — uma Skill que se declare inofensiva e esteja na denylist continua
    negada (`architecture-contracts.md §10.4`).
    """

    name: str
    summary: str
    parameters: ParameterSchema = field(default_factory=ParameterSchema)
    capabilities: frozenset[str] = frozenset()
    required_tools: tuple[ToolId, ...] = ()
    risk: RiskLevel = RiskLevel.LOW
    effects: frozenset[Effect] = frozenset()
    confirmation_requirement: ConfirmationRequirement = ConfirmationRequirement.CONDITIONAL
    idempotency: Idempotency = Idempotency.UNSAFE
    version: int = 1

    def __post_init__(self) -> None:
        overwrite = object.__setattr__

        overwrite(self, "name", require_skill_name(self.name))
        if not self.summary.strip():
            raise SkillRegistryError(f"{self.name}: summary não pode ser vazio")
        if len(self.summary) > MAX_SUMMARY_LENGTH:
            raise SkillRegistryError(f"{self.name}: summary excede {MAX_SUMMARY_LENGTH} caracteres")
        try:
            overwrite(
                self,
                "capabilities",
                frozenset(require_capability(item) for item in self.capabilities),
            )
        except InvalidPolicyVocabularyError as error:
            raise SkillRegistryError(f"{self.name}: {error}") from error
        try:
            overwrite(
                self, "required_tools", tuple(require_tool_id(item) for item in self.required_tools)
            )
        except ToolInvalidInputError as error:
            # Um descritor malformado é problema de registro, não de chamada de
            # tool: quem trata `SkillRegistryError` precisa ver este caso junto.
            raise SkillRegistryError(f"{self.name}: {error}") from error
        if self.version < 1:
            raise SkillRegistryError(f"{self.name}: version precisa ser >= 1")

    @property
    def allowed_tools(self) -> frozenset[ToolId]:
        """O teto do `ToolAccess` desta Skill — menor privilégio por execução."""
        return frozenset(self.required_tools)


@dataclass(frozen=True, slots=True, kw_only=True)
class SkillInvocation:
    """O que um handler recebe. Note o que **não** está aqui."""

    execution_id: str
    correlation_id: str
    parameters: Mapping[str, JsonValue]
    tools: ToolAccess
    now: datetime

    def __post_init__(self) -> None:
        if self.now.utcoffset() is None:
            raise SkillRegistryError("now precisa ser timezone-aware")
        object.__setattr__(self, "now", self.now.astimezone(UTC))


@dataclass(frozen=True, slots=True, kw_only=True)
class SkillOutput:
    """O que um handler devolve quando dá certo.

    `summary` é texto **seguro para o usuário**: uma frase sobre o que aconteceu,
    não o conteúdo do que foi lido ou escrito. `data` carrega o resultado
    estruturado e não vai para log nem para evento.
    """

    data: Mapping[str, JsonValue] = field(default_factory=dict)
    summary: str = ""

    def __post_init__(self) -> None:
        if len(self.summary) > MAX_OUTPUT_SUMMARY_LENGTH:
            object.__setattr__(self, "summary", f"{self.summary[:MAX_OUTPUT_SUMMARY_LENGTH]}…")


class SkillHandler(Protocol):
    def execute(self, invocation: SkillInvocation) -> SkillOutput: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class Skill:
    """Descritor + executor, o par que o registry guarda."""

    descriptor: SkillDescriptor
    handler: SkillHandler

    @property
    def name(self) -> str:
        return self.descriptor.name
