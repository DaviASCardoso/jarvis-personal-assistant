"""As quatro Skills embutidas, contra o backend local de verdade.

Elas são Core puro: compõem chamadas de Tool e validam a regra de negócio delas.
O I/O mora no `LocalToolBackend`, e é por isso que o teste arquitetural
"nenhuma Skill importa `pathlib`" é verdadeiro.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from jarvis.policy.vocabulary import ConfirmationRequirement, Effect, Idempotency, RiskLevel
from jarvis.skills.builtin import builtin_skills, register_builtin_skills
from jarvis.skills.errors import SkillInputError
from jarvis.skills.registry import SkillRegistry
from jarvis.skills.skill import Skill, SkillInvocation, SkillOutput
from jarvis.tools.access import ToolAccess
from jarvis.tools.adapters.local_backend import LocalToolBackend
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.router import ToolRouter
from tests.action_doubles import counting_monotonic

NOON = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def run(skill: Skill, workspace: Path, **parameters: object) -> SkillOutput:
    backend = LocalToolBackend(root=workspace)
    registry = ToolRegistry()
    registry.register_backend(backend)
    registry.refresh()
    router = ToolRouter(registry=registry, monotonic=counting_monotonic())
    access = ToolAccess(
        router=router,
        execution_id="exec-1",
        correlation_id="corr-1",
        allowed=skill.descriptor.allowed_tools,
        idempotent=skill.descriptor.idempotency is Idempotency.SAFE,
    )
    validated = skill.descriptor.parameters.validate(parameters)  # type: ignore[arg-type]
    return skill.handler.execute(
        SkillInvocation(
            execution_id="exec-1",
            correlation_id="corr-1",
            parameters=validated,
            tools=access,
            now=NOON,
        )
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    return root


def by_name(name: str) -> Skill:
    return next(skill for skill in builtin_skills() if skill.name == name)


class TestCatalog:
    def test_the_four_skills_are_registered(self) -> None:
        registry = register_builtin_skills(SkillRegistry())

        assert set(registry.names()) == {
            "system.status",
            "file.read",
            "file.list",
            "file.write",
        }

    def test_reading_is_low_risk_and_never_asks(self) -> None:
        descriptor = by_name("file.read").descriptor

        assert descriptor.risk is RiskLevel.LOW
        assert descriptor.effects == frozenset({Effect.READ})
        assert descriptor.confirmation_requirement is ConfirmationRequirement.NEVER
        assert descriptor.idempotency is Idempotency.SAFE

    def test_writing_is_riskier_and_asks_when_proactive(self) -> None:
        descriptor = by_name("file.write").descriptor

        assert descriptor.risk is RiskLevel.MEDIUM
        assert descriptor.effects == frozenset({Effect.WRITE})
        assert descriptor.confirmation_requirement is ConfirmationRequirement.CONDITIONAL
        assert descriptor.idempotency is Idempotency.UNSAFE

    def test_every_skill_declares_exactly_the_tools_it_uses(self) -> None:
        for skill in builtin_skills():
            assert skill.descriptor.required_tools
            assert all(item.startswith("local:") for item in skill.descriptor.required_tools)

    def test_no_skill_is_a_generic_do_anything(self) -> None:
        """`PHASE-5.md §33`: nada de `execute_anything`."""
        for skill in builtin_skills():
            assert len(skill.descriptor.required_tools) == 1


class TestFileSkills:
    def test_writing_then_reading_round_trips(self, workspace: Path) -> None:
        run(by_name("file.write"), workspace, path="nota.txt", content="olá")

        output = run(by_name("file.read"), workspace, path="nota.txt")

        assert output.data["content"] == "olá"
        assert output.data["path"] == "nota.txt"

    def test_the_summary_describes_without_quoting_the_content(self, workspace: Path) -> None:
        secret = "consulta com a Dra. Marina"
        run(by_name("file.write"), workspace, path="diario.txt", content=secret)

        output = run(by_name("file.read"), workspace, path="diario.txt")

        assert secret not in output.summary
        assert "diario.txt" in output.summary

    def test_appending_is_supported(self, workspace: Path) -> None:
        run(by_name("file.write"), workspace, path="log.txt", content="a")
        output = run(by_name("file.write"), workspace, path="log.txt", content="b", append=True)

        assert (workspace / "log.txt").read_text(encoding="utf-8") == "ab"
        assert "acrescentei" in output.summary.lower()

    def test_listing_reports_the_entries(self, workspace: Path) -> None:
        (workspace / "a.txt").write_text("x", encoding="utf-8")

        output = run(by_name("file.list"), workspace, path=".")

        assert output.data["entries"] == ["a.txt"]
        assert output.data["count"] == 1


class TestBusinessRules:
    """Validação de negócio da Skill, distinta do schema e da raiz do backend."""

    @pytest.mark.parametrize("path", ["../fora.txt", "a/../../fora.txt"])
    def test_traversal_is_refused_by_the_skill(self, workspace: Path, path: str) -> None:
        with pytest.raises(SkillInputError, match=r"\.\."):
            run(by_name("file.read"), workspace, path=path)

    @pytest.mark.parametrize("path", ["/etc/passwd", "C:/Windows/win.ini"])
    def test_absolute_paths_are_refused_by_the_skill(self, workspace: Path, path: str) -> None:
        with pytest.raises(SkillInputError, match="relativo"):
            run(by_name("file.read"), workspace, path=path)

    def test_an_empty_path_is_refused(self, workspace: Path) -> None:
        with pytest.raises(SkillInputError):
            run(by_name("file.read"), workspace, path="   ")

    def test_the_refusal_happens_before_any_tool_call(self, workspace: Path) -> None:
        """A regra da Skill barra antes do backend; são barreiras independentes."""
        target = workspace.parent / "invadido.txt"

        with pytest.raises(SkillInputError):
            run(by_name("file.write"), workspace, path="../invadido.txt", content="x")

        assert not target.exists()


class TestSystemStatus:
    def test_it_reports_without_parameters(self, workspace: Path) -> None:
        output = run(by_name("system.status"), workspace)

        assert output.data["os"]
        assert output.summary
