"""Skill `tasks.list_pending`: autorreflexão sobre tarefas em segundo plano.

Mesmo perfil de `system.status` (Fase 5): risco `none`, efeito só de
leitura, sem confirmação, idempotente — listar o que está pendente não
muda nada.
"""

from typing import Final

from jarvis.policy.vocabulary import ConfirmationRequirement, Effect, Idempotency, RiskLevel
from jarvis.skills.skill import Skill, SkillDescriptor, SkillInvocation, SkillOutput
from jarvis.tools.schema import ParameterSchema
from jarvis.tools.tool import ToolId

LIST_PENDING_TASKS: Final[ToolId] = "reflection:list_pending_tasks"


class ListPendingTasksHandler:
    def execute(self, invocation: SkillInvocation) -> SkillOutput:
        result = invocation.tools.call(LIST_PENDING_TASKS)
        return SkillOutput(data=dict(result.data), summary=result.message)


def list_pending_tasks_skill() -> Skill:
    return Skill(
        descriptor=SkillDescriptor(
            name="tasks.list_pending",
            summary="Lista tarefas em segundo plano pendentes, em repetição ou em execução.",
            parameters=ParameterSchema(),
            capabilities=frozenset({"tasks:read"}),
            required_tools=(LIST_PENDING_TASKS,),
            risk=RiskLevel.NONE,
            effects=frozenset({Effect.READ}),
            confirmation_requirement=ConfirmationRequirement.NEVER,
            idempotency=Idempotency.SAFE,
        ),
        handler=ListPendingTasksHandler(),
    )
