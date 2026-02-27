"""Retry helpers for ai_structured stage calls."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, Generic, Optional, TypeVar

from app.config import logger

T = TypeVar("T")


@dataclass
class RetryResult(Generic[T]):
    value: T
    attempts: int


class RetryExhaustedError(RuntimeError):
    """Raised when all retries are exhausted."""


async def run_with_retry(
    *,
    name: str,
    operation: Callable[[int], Awaitable[T]],
    max_attempts: int,
    base_backoff_seconds: float = 0.5,
) -> RetryResult[T]:
    last_exc: Optional[Exception] = None

    for attempt in range(1, max(1, max_attempts) + 1):
        try:
            value = await operation(attempt)
            return RetryResult(value=value, attempts=attempt)
        except Exception as exc:  # noqa: PERF203 - explicit retry control
            last_exc = exc
            if attempt >= max_attempts:
                break
            sleep_s = base_backoff_seconds * (2 ** (attempt - 1))
            logger.warning(
                "RETRY_STAGE name=%s attempt=%s/%s sleep=%.2fs error=%s",
                name,
                attempt,
                max_attempts,
                sleep_s,
                exc,
            )
            await asyncio.sleep(sleep_s)

    raise RetryExhaustedError(f"{name} exhausted after {max_attempts} attempts: {last_exc}")

