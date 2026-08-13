"""Skill Registry: o catálogo do que o agente pode propor.

Registro **explícito**, feito pelo composition root. Não há varredura de módulos
nem entry points: descobrir capacidades importando código arbitrário é uma
superfície de ataque e uma fonte de efeito colateral em import, e nenhuma das
duas se paga num projeto pessoal com um punhado de Skills.

O registry serve às duas pontas da mesma garantia (`PHASE-5.md §26`): ele decide
o que o modelo **vê** (a lista de capacidades que vai no envelope) e o que o
executor **aceita** (um nome fora daqui vira negação auditada). Um nome inventado
não tem como virar execução em nenhum dos dois caminhos.

O registry não devolve tipos do Agent Runtime. Quem traduz `SkillDescriptor` em
`Capability` é o composition root — é o que mantém `jarvis.skills` sem
dependência de `jarvis.agent`.
"""

import logging
from collections.abc import Iterable

from jarvis.skills.errors import SkillRegistryError, UnknownSkillError
from jarvis.skills.skill import Skill, SkillDescriptor
from jarvis.tools.tool import ToolId

logger = logging.getLogger(__name__)


class SkillRegistry:
    """Serviço do Core. Não é port: implementação única."""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        name = skill.descriptor.name
        if name in self._skills:
            raise SkillRegistryError(f"skill já registrada: {name}")
        self._skills[name] = skill
        logger.debug(
            "skills.registered",
            extra={
                "skill": name,
                "risk": skill.descriptor.risk.value,
                "tool_count": len(skill.descriptor.required_tools),
            },
        )

    def register_all(self, skills: Iterable[Skill]) -> None:
        for skill in skills:
            self.register(skill)

    def get(self, name: str) -> Skill:
        skill = self._skills.get(name)
        if skill is None:
            raise UnknownSkillError(f"skill não registrada: {name}")
        return skill

    def find(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def list(self) -> tuple[SkillDescriptor, ...]:
        return tuple(self._skills[name].descriptor for name in sorted(self._skills))

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._skills))

    def required_tools(self) -> frozenset[ToolId]:
        """A união das ferramentas declaradas — o que o registry de Tools precisa ter."""
        return frozenset(
            tool_id
            for skill in self._skills.values()
            for tool_id in skill.descriptor.required_tools
        )

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._skills

    def __len__(self) -> int:
        return len(self._skills)
