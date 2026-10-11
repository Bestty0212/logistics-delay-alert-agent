"""Recursive checks that tool outputs never expose forbidden fields or values."""

from __future__ import annotations

import re

FORBIDDEN_KEYS = frozenset(
    {"late_label", "delivery_status", "order_status", "actual_days", "is_excluded"}
)

# Values of the forbidden columns, and words that would reveal why an order is excluded.
FORBIDDEN_VALUE_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"late delivery",
        r"shipping on time",
        r"advance shipping",
        r"shipping canceled",
        r"\bcancel",
        r"fraud",
        r"\bexcluded\b",
        r"suspected",
        r"pending_payment",
        r"on_hold",
        r"payment_review",
        r"\bclosed\b",
        r"\bprocessing\b",
    )
]


def find_forbidden(obj: object, path: str = "$") -> list[str]:
    """Return the paths of every forbidden key or value found anywhere in obj."""
    problems: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            child = f"{path}.{key}"
            if str(key) in FORBIDDEN_KEYS:
                problems.append(f"forbidden key at {child}")
            problems.extend(find_forbidden(value, child))
    elif isinstance(obj, (list, tuple)):
        for i, value in enumerate(obj):
            problems.extend(find_forbidden(value, f"{path}[{i}]"))
    elif isinstance(obj, str):
        for pattern in FORBIDDEN_VALUE_PATTERNS:
            if pattern.search(obj):
                problems.append(f"forbidden value at {path}: {pattern.pattern}")
    return problems
