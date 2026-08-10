from datetime import UTC, datetime, timedelta

from jarvis.context.model import (
    ActivityContext,
    CurrentContext,
    DeviceContext,
    EnvironmentContext,
    ScheduleContext,
    UserContext,
)
from jarvis.memory.adapters.context_bridge import context_to_query
from tests.context_doubles import make_observation

NOON = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


class TestActiveTextualFieldsBecomeTags:
    def test_a_fresh_field_becomes_a_field_value_tag(self) -> None:
        context = CurrentContext(
            as_of=NOON,
            environment=EnvironmentContext(
                place=make_observation("home", observed_at=NOON, ttl=timedelta(minutes=15))
            ),
        )

        query = context_to_query(context)

        assert query.criteria.tags == frozenset({"place:home"})

    def test_multiple_fresh_fields_all_become_tags(self) -> None:
        context = CurrentContext(
            as_of=NOON,
            user=UserContext(
                availability=make_observation("busy", observed_at=NOON, ttl=timedelta(hours=4))
            ),
            activity=ActivityContext(
                current=make_observation("working", observed_at=NOON, ttl=timedelta(hours=1))
            ),
        )

        query = context_to_query(context)

        assert query.criteria.tags == frozenset({"availability:busy", "activity:working"})


class TestExclusions:
    def test_a_stale_field_is_ignored(self) -> None:
        context = CurrentContext(
            as_of=NOON,
            environment=EnvironmentContext(
                place=make_observation(
                    "home", observed_at=NOON - timedelta(hours=1), ttl=timedelta(minutes=15)
                )
            ),
        )

        query = context_to_query(context)

        assert query.criteria.tags is None

    def test_an_absent_field_is_ignored(self) -> None:
        context = CurrentContext(as_of=NOON)

        query = context_to_query(context)

        assert query.criteria.tags is None

    def test_an_observed_absence_is_ignored(self) -> None:
        context = CurrentContext(
            as_of=NOON,
            activity=ActivityContext(current=make_observation(None, observed_at=NOON)),
        )

        query = context_to_query(context)

        assert query.criteria.tags is None

    def test_a_non_textual_field_never_becomes_a_tag(self) -> None:
        """`next_entry_at` é datetime: um valor exato que nunca se repete não filtra nada."""
        context = CurrentContext(
            as_of=NOON,
            schedule=ScheduleContext(
                next_entry_at=make_observation(
                    NOON + timedelta(hours=1), observed_at=NOON, ttl=timedelta(minutes=15)
                )
            ),
        )

        query = context_to_query(context)

        assert query.criteria.tags is None

    def test_technical_fields_never_become_tags(self) -> None:
        """`device_id`/`utc_offset` são identidade técnica, não estado do
        usuário: nenhuma memória algum dia teria essas tags, e como
        `MemoryCriteria.tags` exige todas presentes (AND), incluí-las
        zeraria `--from-context` na prática."""
        context = CurrentContext(
            as_of=NOON,
            environment=EnvironmentContext(
                utc_offset=make_observation("-03:00", observed_at=NOON, ttl=timedelta(hours=12))
            ),
            device=DeviceContext(device_id=make_observation("notebook", observed_at=NOON)),
        )

        query = context_to_query(context)

        assert query.criteria.tags is None


class TestQueryShape:
    def test_text_and_limit_pass_through(self) -> None:
        context = CurrentContext(as_of=NOON)

        query = context_to_query(context, text="o que eu costumo usar?", limit=5)

        assert query.text == "o que eu costumo usar?"
        assert query.limit == 5

    def test_defaults_to_a_structured_lookup_without_text(self) -> None:
        context = CurrentContext(as_of=NOON)

        query = context_to_query(context)

        assert query.text is None
        assert query.limit == 10

    def test_an_empty_context_produces_an_unfiltered_criteria(self) -> None:
        context = CurrentContext(as_of=NOON)

        query = context_to_query(context)

        assert query.criteria.types is None
        assert query.criteria.subject is None
        assert query.criteria.tags is None
