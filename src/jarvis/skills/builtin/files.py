"""Skills de arquivo: `file.read`, `file.write`, `file.list`.

Core puro. Nenhum destes módulos importa `pathlib`, `os` ou `platform` — o I/O
mora no `LocalToolBackend`, e o que uma Skill faz é validar a regra de negócio
dela e compor chamadas de Tool através do `ToolAccess` que recebeu.

Os `tool_id` são constantes de texto e não importados do adapter: uma Skill que
importasse `jarvis.tools.adapters` viraria Core dependendo de Infrastructure. Se
o nome divergir, o registry de tools não encontra a ferramenta e o Policy Engine
nega com `required_tool_unavailable` — falha visível, e antes de executar.

A diferença de risco entre elas é o que a fase existe para exercitar: leitura é
`low` e passa direto; escrita é `medium`, declara efeito `write` e exige
confirmação quando a ação foi disparada por um evento em vez de pedida pelo
usuário.
"""

from typing import Final

from jarvis.events.event import JsonValue
from jarvis.policy.vocabulary import ConfirmationRequirement, Effect, Idempotency, RiskLevel
from jarvis.skills.errors import SkillExecutionError, SkillInputError
from jarvis.skills.skill import Skill, SkillDescriptor, SkillInvocation, SkillOutput
from jarvis.tools.schema import FieldSpec, FieldType, ParameterSchema
from jarvis.tools.tool import ToolId

READ_TEXT: Final[ToolId] = "local:fs.read_text"
WRITE_TEXT: Final[ToolId] = "local:fs.write_text"
LIST_DIR: Final[ToolId] = "local:fs.list_dir"

MAX_PATH_LENGTH: Final = 300
MAX_CONTENT_LENGTH: Final = 100_000


def _require_workspace_path(value: JsonValue, *, field_name: str = "path") -> str:
    """Regra de negócio da Skill, distinta da validação de schema.

    O schema garante que é texto e cabe no limite; isto garante que faz sentido
    como caminho de workspace. O backend confere de novo, contra a raiz real —
    duas barreiras independentes, de propósito (`PHASE-5.md §33`).
    """
    if not isinstance(value, str) or not value.strip():
        raise SkillInputError(f"{field_name} precisa ser um caminho não vazio")
    if value.startswith(("/", "\\")) or ":" in value:
        raise SkillInputError(f"{field_name} precisa ser relativo ao workspace")
    if ".." in value.replace("\\", "/").split("/"):
        raise SkillInputError(f"{field_name} não pode conter '..'")
    return value


class ReadFileHandler:
    def execute(self, invocation: SkillInvocation) -> SkillOutput:
        path = _require_workspace_path(invocation.parameters.get("path"))
        result = invocation.tools.call(READ_TEXT, {"path": path})
        characters = result.data.get("characters", 0)
        return SkillOutput(
            data={"path": path, **dict(result.data)},
            # O resumo descreve; o conteúdo fica em `data`, que não vai para log
            # nem para evento.
            summary=f"Li {characters} caracteres de {path}.",
        )


class WriteFileHandler:
    def execute(self, invocation: SkillInvocation) -> SkillOutput:
        path = _require_workspace_path(invocation.parameters.get("path"))
        content = invocation.parameters.get("content")
        if not isinstance(content, str):
            raise SkillInputError("content precisa ser texto")
        append = bool(invocation.parameters.get("append", False))

        result = invocation.tools.call(
            WRITE_TEXT, {"path": path, "content": content, "append": append}
        )
        verb = "acrescentei" if append else "gravei"
        return SkillOutput(
            data={"path": path, **dict(result.data)},
            summary=f"{verb.capitalize()} {len(content)} caracteres em {path}.",
        )


class ListDirectoryHandler:
    def execute(self, invocation: SkillInvocation) -> SkillOutput:
        raw = invocation.parameters.get("path", ".")
        path = _require_workspace_path(raw if raw is not None else ".")
        result = invocation.tools.call(LIST_DIR, {"path": path})
        count = result.data.get("count", 0)
        entries = result.data.get("entries", ())
        if not isinstance(entries, list | tuple):  # pragma: no cover - o schema já garante
            raise SkillExecutionError("a tool devolveu entries num formato inesperado")
        return SkillOutput(
            data={"path": path, "entries": list(entries), "count": count},
            summary=f"{count} item(ns) em {path}.",
        )


def read_file_skill() -> Skill:
    return Skill(
        descriptor=SkillDescriptor(
            name="file.read",
            summary="Lê um arquivo de texto do workspace do Jarvis.",
            parameters=ParameterSchema(
                fields={
                    "path": FieldSpec(
                        type=FieldType.STRING,
                        required=True,
                        description="Caminho relativo ao workspace.",
                        max_length=MAX_PATH_LENGTH,
                    )
                }
            ),
            capabilities=frozenset({"file:read"}),
            required_tools=(READ_TEXT,),
            risk=RiskLevel.LOW,
            effects=frozenset({Effect.READ}),
            confirmation_requirement=ConfirmationRequirement.NEVER,
            idempotency=Idempotency.SAFE,
        ),
        handler=ReadFileHandler(),
    )


def write_file_skill() -> Skill:
    return Skill(
        descriptor=SkillDescriptor(
            name="file.write",
            summary="Grava ou acrescenta texto em um arquivo do workspace do Jarvis.",
            parameters=ParameterSchema(
                fields={
                    "path": FieldSpec(
                        type=FieldType.STRING,
                        required=True,
                        description="Caminho relativo ao workspace.",
                        max_length=MAX_PATH_LENGTH,
                    ),
                    "content": FieldSpec(
                        type=FieldType.STRING, required=True, max_length=MAX_CONTENT_LENGTH
                    ),
                    "append": FieldSpec(type=FieldType.BOOLEAN, default=False),
                }
            ),
            capabilities=frozenset({"file:write"}),
            required_tools=(WRITE_TEXT,),
            risk=RiskLevel.MEDIUM,
            effects=frozenset({Effect.WRITE}),
            # `conditional`: pedida pelo usuário executa; disparada por evento
            # pede confirmação. Ninguém está olhando quando o gatilho é um evento.
            confirmation_requirement=ConfirmationRequirement.CONDITIONAL,
            idempotency=Idempotency.UNSAFE,
        ),
        handler=WriteFileHandler(),
    )


def list_directory_skill() -> Skill:
    return Skill(
        descriptor=SkillDescriptor(
            name="file.list",
            summary="Lista os arquivos de um diretório do workspace do Jarvis.",
            parameters=ParameterSchema(
                fields={
                    "path": FieldSpec(
                        type=FieldType.STRING, max_length=MAX_PATH_LENGTH, default="."
                    )
                }
            ),
            capabilities=frozenset({"file:read"}),
            required_tools=(LIST_DIR,),
            risk=RiskLevel.LOW,
            effects=frozenset({Effect.READ}),
            confirmation_requirement=ConfirmationRequirement.NEVER,
            idempotency=Idempotency.SAFE,
        ),
        handler=ListDirectoryHandler(),
    )
