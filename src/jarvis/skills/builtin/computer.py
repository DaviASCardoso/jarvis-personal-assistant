"""Skills de computador: `computer.list_processes`, `computer.focus_window`,
`computer.open_app`, `computer.close_app`, `computer.run_command` (Fase 8.2).

Core puro, mesmo desenho de `files.py`: nenhum destes módulos importa `psutil`,
`ctypes` ou `subprocess` — isso mora só em `ComputerToolBackend`. O que muda
em relação a `files.py` é o leque de risco: de `none` (listar processos) a
`high` (fechar aplicativo, executar comando) — a primeira vez que o catálogo
embutido chega a `RiskLevel.HIGH`/`Effect.DESTRUCTIVE`/`Effect.PHYSICAL`.

Nenhuma das cinco capacidades (`computer:read`/`open`/`close`/`run`) está na
allowlist default de `JARVIS_POLICY_GRANTED_CAPABILITIES` — continuam negadas
assim que registradas, sem interruptor novo (ver ADR-0031 e `docs/adr/0003`).
"""

from typing import Final

from jarvis.policy.vocabulary import ConfirmationRequirement, Effect, Idempotency, RiskLevel
from jarvis.skills.errors import SkillInputError
from jarvis.skills.skill import Skill, SkillDescriptor, SkillInvocation, SkillOutput
from jarvis.tools.schema import FieldSpec, FieldType, ParameterSchema
from jarvis.tools.tool import ToolId

LIST_PROCESSES: Final[ToolId] = "computer:list_processes"
FOCUS_WINDOW: Final[ToolId] = "computer:focus_window"
OPEN_APP: Final[ToolId] = "computer:open_app"
CLOSE_APP: Final[ToolId] = "computer:close_app"
RUN_COMMAND: Final[ToolId] = "computer:run_command"

MAX_NAME_LENGTH: Final = 100


def _require_name(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SkillInputError(f"{field_name} precisa ser um texto não vazio")
    return value


class ListProcessesHandler:
    def execute(self, invocation: SkillInvocation) -> SkillOutput:
        result = invocation.tools.call(LIST_PROCESSES)
        return SkillOutput(data=dict(result.data), summary=result.message)


class FocusWindowHandler:
    def execute(self, invocation: SkillInvocation) -> SkillOutput:
        application = _require_name(
            invocation.parameters.get("application"), field_name="application"
        )
        result = invocation.tools.call(FOCUS_WINDOW, {"application": application})
        return SkillOutput(data=dict(result.data), summary=result.message)


class OpenAppHandler:
    def execute(self, invocation: SkillInvocation) -> SkillOutput:
        name = _require_name(invocation.parameters.get("name"), field_name="name")
        result = invocation.tools.call(OPEN_APP, {"name": name})
        return SkillOutput(data=dict(result.data), summary=result.message)


class CloseAppHandler:
    def execute(self, invocation: SkillInvocation) -> SkillOutput:
        application = _require_name(
            invocation.parameters.get("application"), field_name="application"
        )
        result = invocation.tools.call(CLOSE_APP, {"application": application})
        return SkillOutput(data=dict(result.data), summary=result.message)


class RunCommandHandler:
    def execute(self, invocation: SkillInvocation) -> SkillOutput:
        name = _require_name(invocation.parameters.get("name"), field_name="name")
        result = invocation.tools.call(RUN_COMMAND, {"name": name})
        return SkillOutput(data=dict(result.data), summary=result.message)


def list_processes_skill() -> Skill:
    return Skill(
        descriptor=SkillDescriptor(
            name="computer.list_processes",
            summary="Lista os processos em execução no computador.",
            parameters=ParameterSchema(),
            capabilities=frozenset({"computer:read"}),
            required_tools=(LIST_PROCESSES,),
            risk=RiskLevel.NONE,
            effects=frozenset({Effect.READ}),
            confirmation_requirement=ConfirmationRequirement.NEVER,
            idempotency=Idempotency.SAFE,
        ),
        handler=ListProcessesHandler(),
    )


def focus_window_skill() -> Skill:
    return Skill(
        descriptor=SkillDescriptor(
            name="computer.focus_window",
            summary="Traz a janela de um aplicativo em execução para primeiro plano.",
            parameters=ParameterSchema(
                fields={
                    "application": FieldSpec(
                        type=FieldType.STRING,
                        required=True,
                        max_length=MAX_NAME_LENGTH,
                        description="Nome (ou parte do nome) do processo/aplicativo.",
                    )
                }
            ),
            capabilities=frozenset({"computer:read"}),
            required_tools=(FOCUS_WINDOW,),
            risk=RiskLevel.LOW,
            effects=frozenset({Effect.WRITE}),
            confirmation_requirement=ConfirmationRequirement.NEVER,
            idempotency=Idempotency.SAFE,
        ),
        handler=FocusWindowHandler(),
    )


def open_app_skill() -> Skill:
    return Skill(
        descriptor=SkillDescriptor(
            name="computer.open_app",
            summary="Abre um aplicativo cadastrado na allowlist de comandos.",
            parameters=ParameterSchema(
                fields={
                    "name": FieldSpec(
                        type=FieldType.STRING,
                        required=True,
                        max_length=MAX_NAME_LENGTH,
                        description="Nome cadastrado na allowlist de comandos.",
                    )
                }
            ),
            capabilities=frozenset({"computer:open"}),
            required_tools=(OPEN_APP,),
            risk=RiskLevel.MEDIUM,
            effects=frozenset({Effect.PHYSICAL}),
            confirmation_requirement=ConfirmationRequirement.CONDITIONAL,
            idempotency=Idempotency.UNSAFE,
        ),
        handler=OpenAppHandler(),
    )


def close_app_skill() -> Skill:
    return Skill(
        descriptor=SkillDescriptor(
            name="computer.close_app",
            summary="Encerra os processos em execução de um aplicativo.",
            parameters=ParameterSchema(
                fields={
                    "application": FieldSpec(
                        type=FieldType.STRING,
                        required=True,
                        max_length=MAX_NAME_LENGTH,
                        description="Nome (ou parte do nome) do processo/aplicativo.",
                    )
                }
            ),
            capabilities=frozenset({"computer:close"}),
            required_tools=(CLOSE_APP,),
            risk=RiskLevel.HIGH,
            effects=frozenset({Effect.DESTRUCTIVE}),
            confirmation_requirement=ConfirmationRequirement.ALWAYS,
            idempotency=Idempotency.UNSAFE,
        ),
        handler=CloseAppHandler(),
    )


def run_command_skill() -> Skill:
    return Skill(
        descriptor=SkillDescriptor(
            name="computer.run_command",
            summary="Executa um comando cadastrado na allowlist de comandos.",
            parameters=ParameterSchema(
                fields={
                    "name": FieldSpec(
                        type=FieldType.STRING,
                        required=True,
                        max_length=MAX_NAME_LENGTH,
                        description="Nome cadastrado na allowlist de comandos.",
                    )
                }
            ),
            capabilities=frozenset({"computer:run"}),
            required_tools=(RUN_COMMAND,),
            risk=RiskLevel.HIGH,
            effects=frozenset({Effect.DESTRUCTIVE}),
            confirmation_requirement=ConfirmationRequirement.ALWAYS,
            idempotency=Idempotency.UNSAFE,
        ),
        handler=RunCommandHandler(),
    )
