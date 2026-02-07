from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetryDecision:
    should_retry: bool
    backoff_ms: int


@dataclass
class RetryPolicy:
    max_attempts: int = 2
    base_backoff_ms: int = 100

    def evaluate(self, attempt: int) -> RetryDecision:
        if attempt >= self.max_attempts:
            return RetryDecision(should_retry=False, backoff_ms=0)
        return RetryDecision(
            should_retry=True,
            backoff_ms=self.base_backoff_ms * (2 ** (attempt - 1)),
        )
