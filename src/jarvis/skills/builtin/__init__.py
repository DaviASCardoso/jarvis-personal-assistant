"""O catálogo inicial de Skills.

Quatro, todas locais. A escolha não é por falta de ambição: são as únicas que dão
execução real de ponta a ponta **sem** integração externa, e integrações
específicas (Gmail, Calendar, Bambu Lab) estão explicitamente fora do escopo da
Fase 5. A arquitetura as suporta — um MCP Server registrado em `mcp.json` expõe
tools novas sem uma linha de código no Core.

Nenhuma Skill genérica do tipo `execute_anything` (`PHASE-5.md §33`): cada uma
declara exatamente as ferramentas de que precisa, e o `ToolAccess` recusa o resto.
"""

from jarvis.skills.builtin.files import list_directory_skill, read_file_skill, write_file_skill
from jarvis.skills.builtin.system import system_status_skill
from jarvis.skills.registry import SkillRegistry
from jarvis.skills.skill import Skill


def builtin_skills() -> tuple[Skill, ...]:
    return (
        system_status_skill(),
        read_file_skill(),
        list_directory_skill(),
        write_file_skill(),
    )


def register_builtin_skills(registry: SkillRegistry) -> SkillRegistry:
    """Registro explícito, chamado pelo composition root.

    Sem varredura de módulos e sem entry points: descobrir capacidades importando
    código arbitrário é superfície de ataque e efeito colateral em import, e nada
    disso se paga com quatro Skills.
    """
    registry.register_all(builtin_skills())
    return registry


__all__ = [
    "builtin_skills",
    "list_directory_skill",
    "read_file_skill",
    "register_builtin_skills",
    "system_status_skill",
    "write_file_skill",
]
