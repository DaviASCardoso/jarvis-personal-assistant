"""Validação de parâmetros: o que substitui a confiança no LLM.

Duas metades: o validador próprio (`ParameterSchema.validate`) e a tradução do
JSON Schema que um MCP Server anuncia (`from_json_schema`). A segunda tem uma
propriedade que vale mais que a cobertura: **o que ela não entende, ela declara
que não entendeu** — em vez de aceitar em silêncio e parecer validado.
"""

import pytest

from jarvis.events.event import JsonValue
from jarvis.tools.errors import ToolInvalidInputError
from jarvis.tools.schema import (
    FieldSpec,
    FieldType,
    ParameterSchema,
    from_json_schema,
    parameters_fingerprint,
)


class TestValidation:
    def test_a_required_field_must_be_present(self) -> None:
        schema = ParameterSchema(fields={"path": FieldSpec(type=FieldType.STRING, required=True)})

        with pytest.raises(ToolInvalidInputError, match="path"):
            schema.validate({})

    def test_unknown_fields_are_refused_by_default(self) -> None:
        schema = ParameterSchema(fields={"path": FieldSpec(type=FieldType.STRING)})

        with pytest.raises(ToolInvalidInputError, match="extra"):
            schema.validate({"path": "a.txt", "extra": 1})

    def test_unknown_fields_pass_through_when_allowed(self) -> None:
        schema = ParameterSchema(fields={}, allow_unknown=True)

        assert dict(schema.validate({"qualquer": 1})) == {"qualquer": 1}

    def test_types_are_checked(self) -> None:
        schema = ParameterSchema(fields={"count": FieldSpec(type=FieldType.INTEGER)})

        with pytest.raises(ToolInvalidInputError, match="integer"):
            schema.validate({"count": "dois"})

    def test_a_boolean_is_not_an_integer(self) -> None:
        """`bool` é subclasse de `int` em Python; aqui não pode ser."""
        schema = ParameterSchema(fields={"count": FieldSpec(type=FieldType.INTEGER)})

        with pytest.raises(ToolInvalidInputError):
            schema.validate({"count": True})

    def test_bounds_are_checked(self) -> None:
        schema = ParameterSchema(
            fields={"ratio": FieldSpec(type=FieldType.NUMBER, minimum=0.0, maximum=1.0)}
        )

        assert schema.validate({"ratio": 0.5})["ratio"] == 0.5
        with pytest.raises(ToolInvalidInputError):
            schema.validate({"ratio": 1.5})

    def test_enum_membership_is_checked(self) -> None:
        schema = ParameterSchema(fields={"mode": FieldSpec(type=FieldType.STRING, enum=("a", "b"))})

        with pytest.raises(ToolInvalidInputError):
            schema.validate({"mode": "c"})

    def test_max_length_applies_to_text_and_lists(self) -> None:
        schema = ParameterSchema(
            fields={
                "text": FieldSpec(type=FieldType.STRING, max_length=3),
                "items": FieldSpec(type=FieldType.ARRAY, max_length=2),
            }
        )

        with pytest.raises(ToolInvalidInputError):
            schema.validate({"text": "abcd", "items": []})
        with pytest.raises(ToolInvalidInputError):
            schema.validate({"text": "abc", "items": [1, 2, 3]})

    def test_a_pattern_is_enforced_without_echoing_the_value(self) -> None:
        schema = ParameterSchema(
            fields={"slug": FieldSpec(type=FieldType.STRING, pattern=r"[a-z]+")}
        )

        with pytest.raises(ToolInvalidInputError) as error:
            schema.validate({"slug": "SEGREDO-123"})

        assert "SEGREDO" not in str(error.value)

    def test_defaults_are_applied(self) -> None:
        schema = ParameterSchema(
            fields={"append": FieldSpec(type=FieldType.BOOLEAN, default=False)}
        )

        assert dict(schema.validate({})) == {"append": False}

    def test_validation_is_idempotent(self) -> None:
        """`resume` revalida o que já foi validado; o fingerprint não pode mudar."""
        schema = ParameterSchema(
            fields={
                "path": FieldSpec(type=FieldType.STRING, required=True),
                "append": FieldSpec(type=FieldType.BOOLEAN, default=False),
            }
        )

        once = schema.validate({"path": "a.txt"})
        twice = schema.validate(dict(once))

        assert dict(once) == dict(twice)
        assert parameters_fingerprint(once) == parameters_fingerprint(twice)

    def test_the_result_is_frozen(self) -> None:
        schema = ParameterSchema(fields={"path": FieldSpec(type=FieldType.STRING)})

        validated = schema.validate({"path": "a.txt"})

        with pytest.raises(TypeError):
            validated["path"] = "b.txt"  # type: ignore[index]

    def test_an_any_field_accepts_anything(self) -> None:
        schema = ParameterSchema(fields={"whatever": FieldSpec()})

        assert schema.validate({"whatever": [1, "dois", None]})


class TestFingerprint:
    def test_the_order_of_keys_does_not_change_the_fingerprint(self) -> None:
        assert parameters_fingerprint({"a": 1, "b": 2}) == parameters_fingerprint({"b": 2, "a": 1})

    def test_different_values_change_the_fingerprint(self) -> None:
        assert parameters_fingerprint({"a": 1}) != parameters_fingerprint({"a": 2})

    def test_the_fingerprint_does_not_contain_the_values(self) -> None:
        fingerprint = parameters_fingerprint({"to": "joao@example.com"})

        assert "joao" not in fingerprint
        assert len(fingerprint) == 64

    def test_nested_structures_are_supported(self) -> None:
        nested: dict[str, JsonValue] = {"outer": {"inner": [1, 2, {"deep": True}]}}

        assert parameters_fingerprint(nested) == parameters_fingerprint(nested)

    def test_a_non_json_value_is_refused(self) -> None:
        with pytest.raises(ToolInvalidInputError):
            parameters_fingerprint({"bad": float("nan")})


class TestJsonSchemaTranslation:
    def test_a_typical_mcp_schema_translates(self) -> None:
        schema = from_json_schema(
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "maxLength": 200, "description": "caminho"},
                    "count": {"type": "integer", "minimum": 1},
                },
                "required": ["path"],
                "additionalProperties": False,
            }
        )

        assert schema.fields["path"].type is FieldType.STRING
        assert schema.fields["path"].required is True
        assert schema.fields["path"].max_length == 200
        assert schema.fields["count"].minimum == 1.0
        assert schema.allow_unknown is False

    def test_json_schema_defaults_to_permissive(self) -> None:
        """Sem `additionalProperties: false`, quem manda é o servidor."""
        schema = from_json_schema({"type": "object", "properties": {}})

        assert schema.allow_unknown is True

    def test_unsupported_keywords_are_recorded_not_silently_ignored(self) -> None:
        schema = from_json_schema(
            {
                "type": "object",
                "properties": {"x": {"type": "string", "format": "email"}},
                "allOf": [],
            }
        )

        assert "allOf" in schema.ignored_keywords
        assert "format" in schema.ignored_keywords

    def test_a_union_type_becomes_any_and_is_recorded(self) -> None:
        schema = from_json_schema(
            {"type": "object", "properties": {"x": {"type": ["string", "null"]}}}
        )

        assert schema.fields["x"].type is FieldType.ANY
        assert "type[]" in schema.ignored_keywords

    def test_an_unknown_type_becomes_any(self) -> None:
        schema = from_json_schema({"type": "object", "properties": {"x": {"type": "geometry"}}})

        assert schema.fields["x"].type is FieldType.ANY
        assert "type=geometry" in schema.ignored_keywords

    def test_a_broken_regex_from_a_server_does_not_break_discovery(self) -> None:
        schema = from_json_schema(
            {"type": "object", "properties": {"x": {"type": "string", "pattern": "([a-"}}}
        )

        assert schema.fields["x"].pattern is None

    def test_a_schema_without_properties_is_empty_and_permissive(self) -> None:
        assert from_json_schema({}).fields == {}
