"""Skill `memory.forget`: esquecer uma memória por pedido do agente.

Core puro, mesmo desenho de `files.py`: o `tool_id` é uma constante de texto,
não importada de `jarvis.tools.adapters.reflection_backend` — uma Skill que
importasse um adapter viraria Core dependendo de Infrastructure.

Perfil de risco real, não decorativo (ADR-0034,
`docs/adr/0034-forget-memory-as-a-policy-gated-skill.md`): diferente de
`remember` (ADR-0018, fora do Policy Engine, aplicado direto pelo composition
root), esquecer é uma operação destrutiva sobre o que o agente vai saber
depois — por isso passa pelo mesmo vocabulário de `capability`/`risk`/`effect`
de qualquer Skill, negada por padrão como toda capacidade nova desde a Fase 8.
"""

from typing import Final

from jarvis.policy.vocabulary import ConfirmationRequirement, Effect, Idempotency, RiskLevel
from jarvis.skills.errors import SkillInputError
from jarvis.skills.skill import Skill, SkillDescriptor, SkillInvocation, SkillOutput
from jarvis.tools.schema import FieldSpec, FieldType, ParameterSchema
from jarvis.tools.tool import ToolId

FORGET_MEMORY: Final[ToolId] = "reflection:forget_memory"

MAX_ID_LENGTH: Final = 100
MAX_REASON_LENGTH: Final = 500


def _require_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SkillInputError(f"{field_name} precisa ser texto não vazio")
    return value


class ForgetMemoryHandler:
    def execute(self, invocation: SkillInvocation) -> SkillOutput:
        memory_id = _require_text(invocation.parameters.get("memory_id"), field_name="memory_id")
        reason = _require_text(invocation.parameters.get("reason"), field_name="reason")

        result = invocation.tools.call(FORGET_MEMORY, {"memory_id": memory_id, "reason": reason})
        return SkillOutput(
            data={"memory_id": memory_id, **dict(result.data)},
            summary=f"Esqueci a memória {memory_id}.",
        )


def forget_memory_skill() -> Skill:
    return Skill(
        descriptor=SkillDescriptor(
            name="memory.forget",
            summary="Invalida uma memória pelo id — some do retrieval, sem apagar a evidência.",
            parameters=ParameterSchema(
                fields={
                    "memory_id": FieldSpec(
                        type=FieldType.STRING,
                        required=True,
                        max_length=MAX_ID_LENGTH,
                        description="Identificador da memória a esquecer.",
                    ),
                    "reason": FieldSpec(
                        type=FieldType.STRING,
                        required=True,
                        max_length=MAX_REASON_LENGTH,
                        description="Motivo do esquecimento.",
                    ),
                }
            ),
            capabilities=frozenset({"memory:forget"}),
            required_tools=(FORGET_MEMORY,),
            risk=RiskLevel.MEDIUM,
            effects=frozenset({Effect.WRITE}),
            # `conditional`: pedida pelo usuário executa; disparada por evento
            # pede confirmação — mesmo critério de `file.write` (ADR-0034).
            confirmation_requirement=ConfirmationRequirement.CONDITIONAL,
            # `MemoryRepository.invalidate` é idempotente por desenho: esquecer
            # o que já foi esquecido não muda nada, ao contrário de `file.write`.
            idempotency=Idempotency.SAFE,
        ),
        handler=ForgetMemoryHandler(),
    )
