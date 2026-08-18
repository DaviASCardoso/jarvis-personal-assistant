"""O catálogo inicial de Skills.

Nove locais desde a Fase 8, mais três de autorreflexão sobre o próprio estado
operacional do Jarvis (Fase 11.4-11.6). Nenhuma integração externa ainda —
Gmail, Calendar, Bambu Lab continuam fora do escopo. A arquitetura as suporta —
um MCP Server registrado em `mcp.json` expõe tools novas sem uma linha de
código no Core. As cinco de computador (Fase 8.2) seguem o mesmo critério:
nenhuma capacidade nova que a Fase 8.1 já não tivesse observado, nenhuma
automação de interface genérica (ver `docs/phase-8-plan.md`).

Nenhuma Skill genérica do tipo `execute_anything` (`PHASE-5.md §33`): cada uma
declara exatamente as ferramentas de que precisa, e o `ToolAccess` recusa o resto.
"""

from jarvis.skills.builtin.computer import (
    close_app_skill,
    focus_window_skill,
    list_processes_skill,
    open_app_skill,
    run_command_skill,
)
from jarvis.skills.builtin.files import list_directory_skill, read_file_skill, write_file_skill
from jarvis.skills.builtin.memory import forget_memory_skill
from jarvis.skills.builtin.system import system_status_skill
from jarvis.skills.registry import SkillRegistry
from jarvis.skills.skill import Skill


def builtin_skills() -> tuple[Skill, ...]:
    return (
        system_status_skill(),
        read_file_skill(),
        list_directory_skill(),
        write_file_skill(),
        list_processes_skill(),
        focus_window_skill(),
        open_app_skill(),
        close_app_skill(),
        run_command_skill(),
        forget_memory_skill(),
    )


def register_builtin_skills(registry: SkillRegistry) -> SkillRegistry:
    """Registro explícito, chamado pelo composition root.

    Sem varredura de módulos e sem entry points: descobrir capacidades importando
    código arbitrário é superfície de ataque e efeito colateral em import, e nada
    disso se paga com um catálogo deste tamanho.
    """
    registry.register_all(builtin_skills())
    return registry


__all__ = [
    "builtin_skills",
    "close_app_skill",
    "focus_window_skill",
    "forget_memory_skill",
    "list_directory_skill",
    "list_processes_skill",
    "open_app_skill",
    "read_file_skill",
    "register_builtin_skills",
    "run_command_skill",
    "system_status_skill",
    "write_file_skill",
]
