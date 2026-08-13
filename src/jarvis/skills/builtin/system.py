"""Skill `system.status`: a capacidade mais inofensiva que existe.

Risco `none`, efeito só de leitura, sem confirmação, idempotente. Existe para dar
à fase um caso em que a política **permite** sem cerimônia — sem ele, todos os
testes de ponta a ponta passariam por confirmação, e o caminho `allow` direto
ficaria sem cobertura real.
"""

from typing import Final

from jarvis.policy.vocabulary import ConfirmationRequirement, Effect, Idempotency, RiskLevel
from jarvis.skills.skill import Skill, SkillDescriptor, SkillInvocation, SkillOutput
from jarvis.tools.schema import ParameterSchema
from jarvis.tools.tool import ToolId

SYSTEM_INFO: Final[ToolId] = "local:system.info"


class SystemStatusHandler:
    def execute(self, invocation: SkillInvocation) -> SkillOutput:
        result = invocation.tools.call(SYSTEM_INFO)
        return SkillOutput(data=dict(result.data), summary=result.message)


def system_status_skill() -> Skill:
    return Skill(
        descriptor=SkillDescriptor(
            name="system.status",
            summary="Informa o estado básico do sistema e do workspace do Jarvis.",
            parameters=ParameterSchema(),
            capabilities=frozenset({"system:read"}),
            required_tools=(SYSTEM_INFO,),
            risk=RiskLevel.NONE,
            effects=frozenset({Effect.READ}),
            confirmation_requirement=ConfirmationRequirement.NEVER,
            idempotency=Idempotency.SAFE,
        ),
        handler=SystemStatusHandler(),
    )
