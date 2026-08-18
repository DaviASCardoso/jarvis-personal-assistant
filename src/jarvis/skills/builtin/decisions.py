"""Skill `decisions.recent`: autorreflexão sobre as próprias decisões.

Mesmo perfil de `tasks.list_pending`/`system.status`: risco `none`, efeito
só de leitura, sem confirmação, idempotente.
"""

from typing import Final

from jarvis.policy.vocabulary import ConfirmationRequirement, Effect, Idempotency, RiskLevel
from jarvis.skills.skill import Skill, SkillDescriptor, SkillInvocation, SkillOutput
from jarvis.tools.schema import FieldSpec, FieldType, ParameterSchema
from jarvis.tools.tool import ToolId

RECENT_DECISIONS: Final[ToolId] = "reflection:recent_decisions"

DEFAULT_LIMIT: Final = 10
MAX_LIMIT: Final = 50


class RecentDecisionsHandler:
    def execute(self, invocation: SkillInvocation) -> SkillOutput:
        limit = invocation.parameters.get("limit", DEFAULT_LIMIT)
        result = invocation.tools.call(RECENT_DECISIONS, {"limit": limit})
        return SkillOutput(data=dict(result.data), summary=result.message)


def recent_decisions_skill() -> Skill:
    return Skill(
        descriptor=SkillDescriptor(
            name="decisions.recent",
            summary="Lista as decisões mais recentes que o agente registrou.",
            parameters=ParameterSchema(
                fields={
                    "limit": FieldSpec(
                        type=FieldType.INTEGER,
                        required=False,
                        minimum=1,
                        maximum=MAX_LIMIT,
                        default=DEFAULT_LIMIT,
                        description="Quantidade máxima de decisões a listar.",
                    )
                }
            ),
            capabilities=frozenset({"decisions:read"}),
            required_tools=(RECENT_DECISIONS,),
            risk=RiskLevel.NONE,
            effects=frozenset({Effect.READ}),
            confirmation_requirement=ConfirmationRequirement.NEVER,
            idempotency=Idempotency.SAFE,
        ),
        handler=RecentDecisionsHandler(),
    )
