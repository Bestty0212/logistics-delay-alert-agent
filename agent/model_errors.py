"""Provider-neutral helpers for classifying model API errors."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

RETRYABLE_STATUSES = frozenset({408, 429})


def is_retryable_status(status: int) -> bool:
    """Rate limits, request timeouts and server errors (5xx) are transient."""
    return status in RETRYABLE_STATUSES or status >= 500


def _seconds(raw: str) -> float | None:
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


def _seconds_until(http_date: str, now: datetime) -> float | None:
    try:
        when = parsedate_to_datetime(http_date)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - now).total_seconds())


def parse_retry_after(headers: Mapping[str, str] | None, now: datetime | None = None) -> float | None:
    """Seconds to wait from `retry-after-ms` or `retry-after` (seconds or HTTP date)."""
    if not headers:
        return None
    lowered = {str(k).lower(): str(v) for k, v in headers.items()}
    if "retry-after-ms" in lowered:
        millis = _seconds(lowered["retry-after-ms"])
        if millis is not None:
            return millis / 1000
    raw = lowered.get("retry-after")
    if raw is None:
        return None
    seconds = _seconds(raw)
    if seconds is not None:
        return seconds
    return _seconds_until(raw, now or datetime.now(timezone.utc))
