import logging

import pytest

from jarvis.events.bus import DeadLetter, EventBus, RetryPolicy
from jarvis.events.event import RecordedEvent
from tests.factories import make_event, make_recorded_event


class RecordingConsumer:
    def __init__(self, name: str = "recording") -> None:
        self.name = name
        self.received: list[RecordedEvent] = []

    def handle(self, event: RecordedEvent) -> None:
        self.received.append(event)


class FailingConsumer:
    def __init__(self, name: str = "failing", *, fail_times: int | None = None) -> None:
        self.name = name
        self.attempts = 0
        self._fail_times = fail_times

    def handle(self, event: RecordedEvent) -> None:
        self.attempts += 1
        if self._fail_times is None or self.attempts <= self._fail_times:
            raise RuntimeError("boom")


class Recorder:
    """Coleta dead letters e intervalos de sleep, para os testes não dormirem."""

    def __init__(self) -> None:
        self.dead_letters: list[DeadLetter] = []
        self.slept: list[float] = []

    def handle_dead_letter(self, dead_letter: DeadLetter) -> None:
        self.dead_letters.append(dead_letter)

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture
def bus(recorder: Recorder) -> EventBus:
    return EventBus(dead_letter_handler=recorder.handle_dead_letter, sleep=recorder.sleep)


class TestDispatch:
    def test_delivers_to_every_subscriber(self, bus: EventBus) -> None:
        first, second = RecordingConsumer("first"), RecordingConsumer("second")
        bus.subscribe(first)
        bus.subscribe(second)
        event = make_recorded_event()

        bus.publish(event)

        assert first.received == [event]
        assert second.received == [event]

    def test_delivers_in_subscription_order(self, bus: EventBus) -> None:
        order: list[str] = []

        class Ordered:
            def __init__(self, name: str) -> None:
                self.name = name

            def handle(self, event: RecordedEvent) -> None:
                order.append(self.name)

        bus.subscribe(Ordered("a"))
        bus.subscribe(Ordered("b"))
        bus.subscribe(Ordered("c"))

        bus.publish(make_recorded_event())

        assert order == ["a", "b", "c"]

    def test_publishing_without_subscribers_is_harmless(self, bus: EventBus) -> None:
        bus.publish(make_recorded_event())

    def test_filters_by_event_type(self, bus: EventBus) -> None:
        interested = RecordingConsumer("interested")
        catch_all = RecordingConsumer("catch-all")
        bus.subscribe(interested, event_types=["email.received"])
        bus.subscribe(catch_all)

        email = make_recorded_event(make_event(event_type="email.received"))
        meeting = make_recorded_event(make_event(event_type="calendar.meeting_starting"))
        bus.publish(email)
        bus.publish(meeting)

        assert interested.received == [email]
        assert catch_all.received == [email, meeting]


class TestFailureIsolation:
    def test_one_failing_consumer_does_not_block_the_others(self, bus: EventBus) -> None:
        failing = FailingConsumer()
        healthy = RecordingConsumer()
        bus.subscribe(failing)
        bus.subscribe(healthy)
        event = make_recorded_event()

        bus.publish(event)

        assert healthy.received == [event]

    def test_consumer_failure_does_not_propagate(self, bus: EventBus) -> None:
        bus.subscribe(FailingConsumer())

        bus.publish(make_recorded_event())  # não levanta


class TestRetry:
    def test_no_retry_by_default(self, bus: EventBus, recorder: Recorder) -> None:
        failing = FailingConsumer()
        bus.subscribe(failing)

        bus.publish(make_recorded_event())

        assert failing.attempts == 1
        assert recorder.slept == []

    def test_retries_up_to_max_attempts(self, bus: EventBus, recorder: Recorder) -> None:
        failing = FailingConsumer()
        bus.subscribe(failing, retry=RetryPolicy(max_attempts=3, delay=0.5))

        bus.publish(make_recorded_event())

        assert failing.attempts == 3
        # Dorme entre tentativas, não depois da última.
        assert recorder.slept == [0.5, 0.5]

    def test_stops_retrying_after_success(self, bus: EventBus, recorder: Recorder) -> None:
        flaky = FailingConsumer(fail_times=1)
        bus.subscribe(flaky, retry=RetryPolicy(max_attempts=3, delay=0.1))

        bus.publish(make_recorded_event())

        assert flaky.attempts == 2
        assert recorder.dead_letters == []

    @pytest.mark.parametrize(("max_attempts", "delay"), [(0, 0.0), (1, -1.0)])
    def test_invalid_policies_are_rejected(self, max_attempts: int, delay: float) -> None:
        with pytest.raises(ValueError, match=r"max_attempts|delay"):
            RetryPolicy(max_attempts=max_attempts, delay=delay)


class TestDeadLetter:
    def test_exhausted_attempts_produce_a_dead_letter(
        self, bus: EventBus, recorder: Recorder
    ) -> None:
        bus.subscribe(FailingConsumer("gmail-sync"), retry=RetryPolicy(max_attempts=2))
        event = make_recorded_event()

        bus.publish(event)

        assert len(recorder.dead_letters) == 1
        dead_letter = recorder.dead_letters[0]
        assert dead_letter.event == event
        assert dead_letter.consumer == "gmail-sync"
        assert dead_letter.attempts == 2
        assert isinstance(dead_letter.error, RuntimeError)

    def test_successful_delivery_produces_no_dead_letter(
        self, bus: EventBus, recorder: Recorder
    ) -> None:
        bus.subscribe(RecordingConsumer())

        bus.publish(make_recorded_event())

        assert recorder.dead_letters == []

    def test_default_handler_logs_the_failure(self, caplog: pytest.LogCaptureFixture) -> None:
        bus = EventBus()
        bus.subscribe(FailingConsumer("noisy"))

        with caplog.at_level(logging.WARNING, logger="jarvis.events.bus"):
            bus.publish(make_recorded_event())

        messages = [record.message for record in caplog.records]
        assert "event.consumer_failed" in messages
        assert "event.dead_letter" in messages
        assert any(record.levelno == logging.ERROR for record in caplog.records)
