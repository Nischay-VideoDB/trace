"""Retry helpers (R2.7, R7.7)."""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import TypeVar

log = logging.getLogger("trace.retry")

T = TypeVar("T")


def retry_sync(
    fn: Callable[[], T],
    *,
    max_attempts: int = 4,
    base_delay: float = 1.0,
    multiplier: float = 2.0,
    min_gap: float | None = None,
    exc_types: tuple[type[BaseException], ...] = (Exception,),
) -> T:
    """Run fn with retries. Delay i = max(base_delay * multiplier^i, min_gap).

    R2.7: max_attempts=4, base_delay=1.0, multiplier=2.0 -> waits 1,2,4 between attempts.
    R7.7: min_gap=2.0 enforces gap floor.
    """
    last: BaseException | None = None
    for i in range(max_attempts):
        try:
            return fn()
        except exc_types as e:
            last = e
            if i == max_attempts - 1:
                break
            delay = base_delay * (multiplier ** i)
            if min_gap is not None:
                delay = max(delay, min_gap)
            log.warning("attempt %d/%d failed (%s); sleeping %.2fs", i + 1, max_attempts, e, delay)
            time.sleep(delay)
    assert last is not None
    raise last


async def retry_async(
    afn: Callable[[], "asyncio.Future[T] | asyncio.coroutines.CoroutineType[T, None, T]"],
    *,
    max_attempts: int = 4,
    base_delay: float = 1.0,
    multiplier: float = 2.0,
    min_gap: float | None = None,
    exc_types: tuple[type[BaseException], ...] = (Exception,),
) -> T:
    last: BaseException | None = None
    for i in range(max_attempts):
        try:
            return await afn()
        except exc_types as e:
            last = e
            if i == max_attempts - 1:
                break
            delay = base_delay * (multiplier ** i)
            if min_gap is not None:
                delay = max(delay, min_gap)
            log.warning("attempt %d/%d failed (%s); sleeping %.2fs", i + 1, max_attempts, e, delay)
            await asyncio.sleep(delay)
    assert last is not None
    raise last
