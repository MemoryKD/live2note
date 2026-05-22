"""Shared utilities for LLM providers."""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from live2note.logger import get_logger

log = get_logger("llm.utils")

_RETRYABLE_STATUSES = {429, 500, 502, 503}


def call_with_retry(
    fn: Callable[[], httpx.Response],
    max_attempts: int = 3,
    base_delay: float = 1.0,
) -> httpx.Response:
    """Call *fn* with exponential backoff on retryable HTTP errors.

    Raises the last exception if all attempts fail.
    """
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = fn()
            if resp.status_code in _RETRYABLE_STATUSES and attempt < max_attempts:
                delay = base_delay * (2 ** (attempt - 1))
                log.warning(
                    "HTTP %d (attempt %d/%d), retrying in %.1fs...",
                    resp.status_code, attempt, max_attempts, delay,
                )
                time.sleep(delay)
                continue
            resp.raise_for_status()
            return resp
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            last_exc = exc
            if attempt < max_attempts:
                delay = base_delay * (2 ** (attempt - 1))
                log.warning(
                    "Connection error (attempt %d/%d): %s, retrying in %.1fs...",
                    attempt, max_attempts, exc, delay,
                )
                time.sleep(delay)
            else:
                raise
    # Should not reach here, but just in case:
    raise last_exc  # type: ignore[misc]
