from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol


class AsyncToolExecutor(Protocol):
    def dispatch(
        self,
        fn: Callable[[], Any],
        on_complete: Optional[Callable[[Any], None]] = None,
    ) -> None:
        ...


@dataclass
class InProcessThreadPoolExecutor:
    max_workers: int = 4

    def __post_init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=self.max_workers)

    def dispatch(
        self,
        fn: Callable[[], Any],
        on_complete: Optional[Callable[[Any], None]] = None,
    ) -> None:
        future: Future[Any] = self._executor.submit(fn)

        if on_complete:
            def _callback(fut: Future[Any]) -> None:
                on_complete(fut.result())

            future.add_done_callback(_callback)


class ImmediateExecutor:
    def dispatch(
        self,
        fn: Callable[[], Any],
        on_complete: Optional[Callable[[Any], None]] = None,
    ) -> None:
        result = fn()
        if on_complete:
            on_complete(result)
