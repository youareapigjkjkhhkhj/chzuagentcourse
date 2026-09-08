"""Shared retry logic - avoids duplication across text/vision services."""
from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")

MAX_RETRIES = 3
RETRY_BACKOFF = (1, 2, 4)

RETRYABLE_ERROR_TOKENS = (
    "429", "rate limit", "too many requests", "timeout", "timed out",
    "connection reset", "connection aborted", "service unavailable",
    "gateway timeout", "internal server error",
    "500", "502", "503", "504",
)


def is_retryable_error(error: Exception) -> bool:
    msg = str(error).lower()
    return any(t in msg for t in RETRYABLE_ERROR_TOKENS)


def with_retry(
    fn: Callable[[], T],
    is_retryable: Callable[[Exception], bool] = is_retryable_error,
) -> T:
    """Execute fn with exponential backoff on retryable errors."""
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES - 1 and is_retryable(e):
                time.sleep(RETRY_BACKOFF[attempt])
                continue
            raise
    raise last_err  # type: ignore
