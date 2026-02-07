from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import Condition
from typing import Any, Callable, Deque, Dict, Iterable, Optional, Tuple

from caal.kernel.contracts import Event


@dataclass(frozen=True)
class EventEnvelope:
    seq: int
    event: Event


Subscriber = Callable[[EventEnvelope], None]


@dataclass
class EventBus:
    def __init__(self) -> None:
        self._subscribers: Dict[str, Subscriber] = {}

    def subscribe(self, key: str, callback: Subscriber) -> None:
        self._subscribers[key] = callback

    def unsubscribe(self, key: str) -> None:
        self._subscribers.pop(key, None)

    def publish(self, envelope: EventEnvelope) -> None:
        for callback in list(self._subscribers.values()):
            callback(envelope)

class SessionEventStream:
    def __init__(self, bus: EventBus, session_id: str) -> None:
        self._bus = bus
        self._queue: Dict[int, Event] = {}
        self._condition = Condition()
        self._closed = False
        self._session_id = session_id
        self._next_seq: Optional[int] = None
        self._key = f"stream-{id(self)}"

    def __enter__(self) -> "SessionEventStream":
        def _callback(envelope: EventEnvelope) -> None:
            if envelope.event.session_id != self._session_id:
                return
            with self._condition:
                self._queue[envelope.seq] = envelope.event
                if self._next_seq is None:
                    self._next_seq = envelope.seq
                self._condition.notify()

        self._bus.subscribe(self._key, _callback)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        self._bus.unsubscribe(self._key)

    def __iter__(self) -> Iterable[Event]:
        return self

    def __next__(self) -> Event:
        with self._condition:
            while (self._next_seq is None or self._next_seq not in self._queue) and not self._closed:
                self._condition.wait()
            if self._next_seq is not None and self._next_seq in self._queue:
                event = self._queue.pop(self._next_seq)
                self._next_seq += 1
                return event
            raise StopIteration
