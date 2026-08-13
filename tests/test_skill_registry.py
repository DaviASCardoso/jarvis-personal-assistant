"""O registry decide o que o modelo vê e o que o executor aceita.

O teste mais importante daqui não é sobre registro: é
`test_the_skill_name_pattern_matches_what_the_agent_can_propose`. Ele amarra dois
padrões que vivem em pacotes que não podem se importar, e cuja divergência
abriria um buraco silencioso entre "o agente propôs" e "o registry conhece".
"""

import pytest

from jarvis.agent.decision import ActionProposal
from jarvis.agent.errors import InvalidDecisionError
from jarvis.skills.errors import SkillRegistryError, UnknownSkillError
from jarvis.skills.registry import SkillRegistry
from jarvis.skills.skill import SkillDescriptor
from jarvis.tools.schema import FieldSpec, FieldType, ParameterSchema
from tests.action_doubles import make_descriptor, make_skill

VALID_NAMES = ["file.read", "system.status", "send_email", "a1", "a-b", "x.y_z-w"]
INVALID_NAMES = ["File.Read", "", ".leading", "trailing.", "com espaço", "a..b", "ação"]


class TestRegistration:
    def test_a_registered_skill_can_be_found(self) -> None:
        registry = SkillRegistry()
        skill = make_skill()

        registry.register(skill)

        assert registry.get("test.skill") is skill
        assert "test.skill" in registry
        assert len(registry) == 1

    def test_registering_the_same_name_twice_is_refused(self) -> None:
        registry = SkillRegistry()
        registry.register(make_skill())

        with pytest.raises(SkillRegistryError):
            registry.register(make_skill())

    def test_an_unknown_skill_raises(self) -> None:
        with pytest.raises(UnknownSkillError):
            SkillRegistry().get("nope")

    def test_find_returns_none_instead_of_raising(self) -> None:
        """O executor precisa transformar 'não existe' em negação auditada."""
        assert SkillRegistry().find("nope") is None

    def test_listing_is_sorted_and_returns_descriptors(self) -> None:
        registry = SkillRegistry()
        registry.register(make_skill(descriptor=make_descriptor(name="z.skill")))
        registry.register(make_skill(descriptor=make_descriptor(name="a.skill")))

        assert [item.name for item in registry.list()] == ["a.skill", "z.skill"]

    def test_required_tools_is_the_union_of_what_the_skills_declare(self) -> None:
        registry = SkillRegistry()
        registry.register(
            make_skill(descriptor=make_descriptor(name="one", required_tools=("fake:echo",)))
        )
        registry.register(
            make_skill(
                descriptor=make_descriptor(name="two", required_tools=("fake:echo", "fake:noop"))
            )
        )

        assert registry.required_tools() == frozenset({"fake:echo", "fake:noop"})


class TestDescriptorValidation:
    @pytest.mark.parametrize("name", VALID_NAMES)
    def test_valid_names_are_accepted(self, name: str) -> None:
        assert make_descriptor(name=name).name == name

    @pytest.mark.parametrize("name", INVALID_NAMES)
    def test_invalid_names_are_refused(self, name: str) -> None:
        with pytest.raises(SkillRegistryError):
            make_descriptor(name=name)

    @pytest.mark.parametrize("name", VALID_NAMES)
    def test_the_skill_name_pattern_matches_what_the_agent_can_propose(self, name: str) -> None:
        """`jarvis.skills` e `jarvis.agent` não se importam; os padrões precisam casar."""
        assert ActionProposal(skill=name).skill == name

    @pytest.mark.parametrize("name", INVALID_NAMES)
    def test_what_the_agent_refuses_the_registry_also_refuses(self, name: str) -> None:
        with pytest.raises(InvalidDecisionError):
            ActionProposal(skill=name)
        with pytest.raises(SkillRegistryError):
            make_descriptor(name=name)

    def test_an_empty_summary_is_refused(self) -> None:
        with pytest.raises(SkillRegistryError):
            make_descriptor(summary="   ")

    def test_a_malformed_capability_is_refused(self) -> None:
        with pytest.raises(SkillRegistryError):
            make_descriptor(capabilities=frozenset({"semverbo"}))

    def test_a_malformed_tool_id_is_refused(self) -> None:
        with pytest.raises(SkillRegistryError, match="tool_id"):
            make_descriptor(required_tools=("sem-backend",))

    def test_allowed_tools_is_the_ceiling_of_the_tool_access(self) -> None:
        descriptor = make_descriptor(required_tools=("fake:echo", "fake:noop"))

        assert descriptor.allowed_tools == frozenset({"fake:echo", "fake:noop"})


class TestCapabilitiesForTheEnvelope:
    def test_the_descriptor_can_describe_its_own_schema(self) -> None:
        descriptor = SkillDescriptor(
            name="file.read",
            summary="Lê um arquivo.",
            parameters=ParameterSchema(
                fields={
                    "path": FieldSpec(type=FieldType.STRING, required=True),
                    "encoding": FieldSpec(type=FieldType.STRING),
                }
            ),
        )

        described = descriptor.parameters.describe()

        assert "path: string (obrigatório)" in described
        assert "encoding: string" in described

    def test_the_registry_never_returns_agent_types(self) -> None:
        """Traduzir para `Capability` é trabalho do composition root."""
        registry = SkillRegistry()
        registry.register(make_skill())

        assert all(isinstance(item, SkillDescriptor) for item in registry.list())
