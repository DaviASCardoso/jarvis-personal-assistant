"""Schemas de parâmetro: a validação que o LLM não pode fazer por nós.

`PHASE-5.md §27`: "O LLM não é confiável como validador. Validação deve ocorrer
em código." Este módulo é esse código, e é compartilhado por Skills e Tools de
propósito — um único motor de validação, um único formato de erro.

Por que um validador próprio em vez de `pydantic`, que já é dependência: o
problema real não é validar dados contra uma classe conhecida em tempo de
escrita, e sim contra um **JSON Schema descoberto em runtime**, anunciado por um
MCP Server que não controlamos. `pydantic` não resolve isso; `ParameterSchema` +
`from_json_schema` resolvem, em umas poucas dezenas de linhas e sem dependência
nova.

`json` aparece aqui por um motivo específico e não de serialização:
`parameters_fingerprint` precisa de uma forma canônica estável para derivar o
sha256 que atravessa política, aprovação e auditoria **no lugar** dos parâmetros.
"""

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Final, TypeGuard

from jarvis.events.event import JsonValue
from jarvis.tools.errors import ToolInvalidInputError

MAX_DESCRIBE_FIELDS: Final = 12


class FieldType(StrEnum):
    """Os tipos do JSON, mais `ANY`.

    `ANY` não é preguiça: é o que um schema externo sem `type` declarado
    honestamente significa. Fingir que um campo sem tipo é string produziria
    recusas erradas em tools de terceiros.
    """

    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    OBJECT = "object"
    ARRAY = "array"
    ANY = "any"


def _matches(value: JsonValue, expected: FieldType) -> bool:
    match expected:
        case FieldType.ANY:
            return True
        case FieldType.STRING:
            return isinstance(value, str)
        case FieldType.BOOLEAN:
            return isinstance(value, bool)
        case FieldType.INTEGER:
            # `bool` é subclasse de `int` em Python; True não é um inteiro aqui.
            return isinstance(value, int) and not isinstance(value, bool)
        case FieldType.NUMBER:
            return isinstance(value, int | float) and not isinstance(value, bool)
        case FieldType.OBJECT:
            return isinstance(value, Mapping)
        case FieldType.ARRAY:
            return isinstance(value, Sequence) and not isinstance(value, str)


@dataclass(frozen=True, slots=True, kw_only=True)
class FieldSpec:
    type: FieldType = FieldType.ANY
    required: bool = False
    description: str = ""
    enum: tuple[JsonValue, ...] | None = None
    minimum: float | None = None
    maximum: float | None = None
    max_length: int | None = None
    pattern: str | None = None
    default: JsonValue | None = None

    def __post_init__(self) -> None:
        if self.enum is not None and not self.enum:
            raise ToolInvalidInputError("enum não pode ser vazio")
        if self.minimum is not None and self.maximum is not None and self.maximum < self.minimum:
            raise ToolInvalidInputError("maximum não pode ser menor que minimum")
        if self.max_length is not None and self.max_length < 0:
            raise ToolInvalidInputError("max_length não pode ser negativo")
        if self.pattern is not None:
            try:
                re.compile(self.pattern)
            except re.error as error:
                raise ToolInvalidInputError(f"pattern inválido: {error.msg}") from error


@dataclass(frozen=True, slots=True, kw_only=True)
class ParameterSchema:
    """Contrato de entrada de uma Skill ou de uma Tool.

    `allow_unknown=False` por padrão: `PHASE-5.md §27` manda rejeitar campo
    desconhecido, e o default seguro é recusar o que não se sabe interpretar.
    Schemas traduzidos de MCP herdam o default do JSON Schema (permissivo),
    porque lá quem manda é o servidor.
    """

    fields: Mapping[str, FieldSpec] = field(default_factory=dict)
    allow_unknown: bool = False
    ignored_keywords: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "fields", MappingProxyType(dict(self.fields)))

    def validate(self, params: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
        """Devolve os parâmetros validados e congelados, ou recusa.

        Aplica defaults dos campos ausentes — o resultado é o que a Skill/Tool
        efetivamente recebe, não o que o chamador escreveu.
        """
        if not isinstance(params, Mapping):
            raise ToolInvalidInputError("parâmetros precisam ser um objeto")

        if not self.allow_unknown:
            unknown = sorted(set(params) - set(self.fields))
            if unknown:
                # Nomes de campo vêm do schema e do chamador; são seguros. Os
                # valores é que nunca aparecem.
                raise ToolInvalidInputError(f"campos desconhecidos: {', '.join(unknown)}")

        validated: dict[str, JsonValue] = {}
        for name, spec in self.fields.items():
            if name not in params:
                if spec.required:
                    raise ToolInvalidInputError(f"campo obrigatório ausente: {name}")
                if spec.default is not None:
                    validated[name] = spec.default
                continue
            validated[name] = _check(params[name], spec, name=name)

        if self.allow_unknown:
            for name, value in params.items():
                if name not in self.fields:
                    validated[name] = value

        return MappingProxyType(validated)

    def describe(self) -> str:
        """Linha curta para o envelope do LLM — nomes e tipos, nada de exemplos.

        Truncada em `MAX_DESCRIBE_FIELDS`: o orçamento de prompt é caro, e um
        schema gigante no envelope custa mais do que informa.
        """
        parts: list[str] = []
        for name, spec in list(self.fields.items())[:MAX_DESCRIBE_FIELDS]:
            piece = f"{name}: {spec.type.value}"
            if spec.required:
                piece += " (obrigatório)"
            if spec.enum is not None:
                piece += f" ∈ {{{', '.join(str(item) for item in spec.enum)}}}"
            parts.append(piece)
        if len(self.fields) > MAX_DESCRIBE_FIELDS:
            parts.append(f"… (+{len(self.fields) - MAX_DESCRIBE_FIELDS})")
        return "; ".join(parts)


def _check(value: JsonValue, spec: FieldSpec, *, name: str) -> JsonValue:
    if not _matches(value, spec.type):
        raise ToolInvalidInputError(
            f"{name} precisa ser {spec.type.value}, recebido {type(value).__name__}"
        )
    if spec.enum is not None and value not in spec.enum:
        raise ToolInvalidInputError(
            f"{name} precisa ser um de {', '.join(str(item) for item in spec.enum)}"
        )
    if isinstance(value, int | float) and not isinstance(value, bool):
        if spec.minimum is not None and value < spec.minimum:
            raise ToolInvalidInputError(f"{name} precisa ser >= {spec.minimum}")
        if spec.maximum is not None and value > spec.maximum:
            raise ToolInvalidInputError(f"{name} precisa ser <= {spec.maximum}")
    _check_length(value, spec, name=name)
    _check_pattern(value, spec, name=name)
    return value


def _check_length(value: JsonValue, spec: FieldSpec, *, name: str) -> None:
    if spec.max_length is None or not isinstance(value, str | Sequence):
        return
    if len(value) > spec.max_length:
        raise ToolInvalidInputError(f"{name} excede o tamanho máximo de {spec.max_length}")


def _check_pattern(value: JsonValue, spec: FieldSpec, *, name: str) -> None:
    if spec.pattern is None or not isinstance(value, str):
        return
    if re.compile(spec.pattern).fullmatch(value) is None:
        # A mensagem não repete o valor recusado: ele pode ter vindo de um
        # payload de evento.
        raise ToolInvalidInputError(f"{name} não casa com o padrão exigido")


def _canonical(value: JsonValue) -> object:
    """Converte para tipos que `json.dumps` entende.

    `Event.payload` congela `dict` em `MappingProxyType` e `list` em `tuple`; o
    primeiro não é serializável por `json` sem esta conversão.
    """
    if isinstance(value, Mapping):
        return {key: _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, str) or not isinstance(value, Sequence):
        return value
    return [_canonical(item) for item in value]


def parameters_fingerprint(params: Mapping[str, JsonValue]) -> str:
    """Impressão digital estável dos parâmetros.

    É **isto** — e nunca os parâmetros — que atravessa `PolicyRequest`,
    `PolicyVerdict`, `PolicyApproval` e os eventos de auditoria. Permite provar
    que a execução autorizada é a mesma que foi pedida, sem que o conteúdo
    precise circular por camadas que não têm nada que vê-lo.
    """
    try:
        payload = json.dumps(
            _canonical(params),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ToolInvalidInputError(
            f"parâmetros não são representáveis em JSON: {error}"
        ) from error
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_JSON_SCHEMA_TYPES: Final[Mapping[str, FieldType]] = {
    "string": FieldType.STRING,
    "integer": FieldType.INTEGER,
    "number": FieldType.NUMBER,
    "boolean": FieldType.BOOLEAN,
    "object": FieldType.OBJECT,
    "array": FieldType.ARRAY,
}

_SUPPORTED_FIELD_KEYWORDS: Final = frozenset(
    {"type", "enum", "minimum", "maximum", "maxLength", "pattern", "description", "default"}
)
_SUPPORTED_ROOT_KEYWORDS: Final = frozenset(
    {"type", "properties", "required", "additionalProperties", "description", "title"}
)


def from_json_schema(schema: Mapping[str, object]) -> ParameterSchema:
    """Traduz um JSON Schema anunciado por um MCP Server para `ParameterSchema`.

    Subconjunto **documentado e honesto**: o que não é entendido não é validado,
    e o nome da palavra-chave ignorada vai para `ignored_keywords`, visível em
    `jarvis tools list`. Fingir ter validado `allOf` ou `$ref` seria pior que não
    validar, porque produziria confiança sem cobertura.
    """
    ignored: set[str] = set(schema) - _SUPPORTED_ROOT_KEYWORDS
    raw_properties = schema.get("properties")
    properties: Mapping[str, object] = raw_properties if isinstance(raw_properties, Mapping) else {}
    raw_required = schema.get("required")
    required = (
        {name for name in raw_required if isinstance(name, str)}
        if isinstance(raw_required, Sequence) and not isinstance(raw_required, str)
        else set()
    )

    fields: dict[str, FieldSpec] = {}
    for name, raw in properties.items():
        if not isinstance(name, str) or not isinstance(raw, Mapping):
            continue
        fields[name] = _field_from_json_schema(raw, required=name in required, ignored=ignored)

    return ParameterSchema(
        fields=fields,
        # Ausente ou `true` significa permissivo em JSON Schema, e quem manda no
        # contrato de uma tool externa é o servidor que a expõe.
        allow_unknown=schema.get("additionalProperties") is not False,
        ignored_keywords=tuple(sorted(ignored)),
    )


def _field_from_json_schema(
    raw: Mapping[str, object], *, required: bool, ignored: set[str]
) -> FieldSpec:
    ignored.update(set(raw) - _SUPPORTED_FIELD_KEYWORDS)
    description = raw.get("description")
    max_length = raw.get("maxLength")
    return FieldSpec(
        type=_type_from_json_schema(raw.get("type"), ignored=ignored),
        required=required,
        description=description if isinstance(description, str) else "",
        enum=_enum_from_json_schema(raw.get("enum")),
        minimum=_number(raw.get("minimum")),
        maximum=_number(raw.get("maximum")),
        max_length=max_length
        if isinstance(max_length, int) and not isinstance(max_length, bool)
        else None,
        pattern=_pattern(raw.get("pattern")),
    )


def _type_from_json_schema(raw: object, *, ignored: set[str]) -> FieldType:
    if isinstance(raw, str):
        if raw in _JSON_SCHEMA_TYPES:
            return _JSON_SCHEMA_TYPES[raw]
        ignored.add(f"type={raw}")
        return FieldType.ANY
    if isinstance(raw, Sequence):
        # União (`["string", "null"]`): validar só o primeiro tipo suportado
        # produziria recusa de um `null` legítimo, então a união vira ANY.
        ignored.add("type[]")
    return FieldType.ANY


def _enum_from_json_schema(raw: object) -> tuple[JsonValue, ...] | None:
    if not isinstance(raw, Sequence) or isinstance(raw, str) or not raw:
        return None
    return tuple(item for item in raw if _is_json_scalar(item))


def _is_json_scalar(value: object) -> TypeGuard[JsonValue]:
    return value is None or isinstance(value, str | bool | int | float)


def _number(raw: object) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    return float(raw)


def _pattern(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    try:
        re.compile(raw)
    except re.error:
        # Regex de um servidor externo não derruba a descoberta inteira.
        return None
    return raw
