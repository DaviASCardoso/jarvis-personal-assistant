"""Skill Framework: as capacidades que o agente pode propor.

API pública do componente. Uma Skill declara risco, efeitos, capacidades
exigidas e ferramentas necessárias — e **nada disso a autoriza**. A decisão
pertence ao Policy Engine, e este pacote só toca `jarvis.policy.vocabulary`,
nunca o engine ([ADR-0003](../../../docs/adr/0003-policy-engine-safety-authority.md),
[ADR-0005](../../../docs/adr/0005-skill-tool-mcp-distinction.md)).

Documentação: [`docs/skills.md`](../../../docs/skills.md).
"""

from jarvis.skills.errors import (
    SkillError,
    SkillExecutionError,
    SkillInputError,
    SkillRegistryError,
    UnknownSkillError,
)
from jarvis.skills.registry import SkillRegistry
from jarvis.skills.skill import (
    Skill,
    SkillDescriptor,
    SkillHandler,
    SkillInvocation,
    SkillOutput,
    require_skill_name,
)

__all__ = [
    "Skill",
    "SkillDescriptor",
    "SkillError",
    "SkillExecutionError",
    "SkillHandler",
    "SkillInputError",
    "SkillInvocation",
    "SkillOutput",
    "SkillRegistry",
    "SkillRegistryError",
    "UnknownSkillError",
    "require_skill_name",
]
