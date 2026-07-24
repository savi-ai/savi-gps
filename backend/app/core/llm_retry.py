"""Shared LLM retry helper for API providers."""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, TypeVar

from app.core.config import settings
from app.core.logger import logger

T = TypeVar("T")

_RETRYABLE_HINTS = (
    "throttl",
    "rate",
    "429",
    "503",
    "502",
    "504",
    "timeout",
    "temporarily",
    "too many requests",
    "service unavailable",
)


def is_retryable_llm_error(exc: BaseException) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(h in text for h in _RETRYABLE_HINTS)


async def with_llm_retries(
    operation: Callable[[], Awaitable[T]],
    *,
    max_retries: int | None = None,
    label: str = "llm",
) -> T:
    """Retry async LLM calls on transient failures. max_retries = retries after first try."""
    retries = settings.LLM_MAX_RETRIES if max_retries is None else max_retries
    retries = max(0, int(retries))
    attempt = 0
    while True:
        try:
            return await operation()
        except Exception as e:
            if attempt >= retries or not is_retryable_llm_error(e):
                raise
            delay = min(2**attempt, 8)
            logger.warning(
                "%s attempt %s failed (%s); retrying in %ss",
                label,
                attempt + 1,
                e,
                delay,
            )
            await asyncio.sleep(delay)
            attempt += 1
