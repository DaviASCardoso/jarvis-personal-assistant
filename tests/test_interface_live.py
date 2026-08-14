"""`LiveState`: a única estrutura compartilhada entre as threads do processo."""

import threading

from jarvis.interface.live import LiveState
from jarvis.interface.viewmodel import PanelSnapshot
from tests.interface_doubles import PANEL_NOW


def snapshot(revision: int = 0) -> PanelSnapshot:
    return PanelSnapshot(revision=revision, as_of=PANEL_NOW)


def test_nothing_published_yet_is_none_not_an_empty_snapshot() -> None:
    live = LiveState()

    assert live.current() is None
    assert live.revision == 0


def test_publishing_assigns_a_monotonic_revision() -> None:
    # A revisão é do `LiveState`, não de quem publica: assim o status da voz e o
    # snapshot completo nunca disputam o contador.
    live = LiveState()

    assert live.publish(snapshot(revision=99)) == 1
    assert live.publish(snapshot(revision=99)) == 2

    current = live.current()
    assert current is not None
    assert current.revision == 2


def test_wait_for_returns_immediately_when_there_is_already_something_newer() -> None:
    live = LiveState()
    live.publish(snapshot())

    assert live.wait_for(after=0, timeout=0.01) is not None


def test_wait_for_gives_up_when_nothing_new_arrives() -> None:
    live = LiveState()
    live.publish(snapshot())

    assert live.wait_for(after=1, timeout=0.01) is None


def test_a_waiter_is_woken_by_the_next_publication() -> None:
    live = LiveState()
    seen: list[int] = []

    def wait() -> None:
        received = live.wait_for(after=0, timeout=2.0)
        seen.append(received.revision if received is not None else -1)

    waiter = threading.Thread(target=wait)
    waiter.start()
    live.publish(snapshot())
    waiter.join(timeout=3)

    assert seen == [1]


def test_many_readers_and_one_writer_stay_consistent() -> None:
    live = LiveState()
    live.publish(snapshot())
    revisions: list[int] = []
    lock = threading.Lock()

    def read() -> None:
        for _ in range(50):
            current = live.current()
            if current is not None:
                with lock:
                    revisions.append(current.revision)

    readers = [threading.Thread(target=read) for _ in range(8)]
    for reader in readers:
        reader.start()
    for _ in range(50):
        live.publish(snapshot())
    for reader in readers:
        reader.join(timeout=5)

    assert revisions == sorted(revisions) or len(set(revisions)) > 1
    assert live.revision == 51
