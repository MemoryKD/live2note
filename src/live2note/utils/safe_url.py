"""Safe URL logging utilities — prevent stream URL / token leakage in logs."""

from __future__ import annotations

from urllib.parse import urlparse


def safe_url(url: str, max_length: int = 80) -> str:
    """Return a safe-for-logging version of a URL.

    Short URLs are returned as-is (within *max_length*).
    Long URLs show ``scheme://netloc/path_prefix...`` with query
    parameters stripped.

    Never shows query parameters or fragments in truncated output.
    """
    if not url:
        return ""
    if len(url) <= max_length:
        return url
    try:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if len(base) > max_length:
            return base[:max_length - 3] + "..."
        return base[:max_length]
    except Exception:
        return url[:max_length - 3] + "..."


def safe_url_short(url: str) -> str:
    """Return a brief safe version — domain only, no path."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}/***"
    except Exception:
        return "***"


def safe_url_full(url: str) -> str:
    """Return the full URL. Only call when --show-stream-url is active."""
    return url or ""
