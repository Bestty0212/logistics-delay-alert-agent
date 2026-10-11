"""Deterministic checks of one agent answer against its question spec and gold values."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from agent_tools.registry import TOOL_FUNCTIONS

DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
NUMBER_RE = re.compile(r"(?<![\d.])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")
PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")

RATE_TOLERANCE_POINTS = 1.0
RATE_TOLERANCE_FRACTION = 0.01

GLOBAL_FORBIDDEN = (r"\bguarantee", r"\b2026\b")

LEAK_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"late_label",
        r"delivery_status",
        r"order_status",
        r"actual_days",
        r"cancell?ed",
        r"fraud",
    )
)


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str = ""


class SpecError(Exception):
    """A question's checks refer to a gold value that does not exist."""


# --- numbers ------------------------------------------------------------------


def extract_numbers(text: str) -> list[float]:
    """Numbers in text after removing ISO dates; thousands separators are dropped."""
    without_dates = DATE_RE.sub(" ", text)
    return [float(m.replace(",", "")) for m in NUMBER_RE.findall(without_dates)]


def count_matches(numbers: list[float], count: int) -> bool:
    return any(n == count for n in numbers)


def rate_matches(numbers: list[float], rate: float) -> bool:
    """Accept a percentage within 1 point or a fraction (<= 1) within 0.01."""
    percent = rate * 100
    return any(
        abs(n - percent) <= RATE_TOLERANCE_POINTS
        or (n <= 1 and abs(n - rate) <= RATE_TOLERANCE_FRACTION)
        for n in numbers
    )


def gold_value(values: dict, name: str) -> object:
    if values.get(name) is None:
        raise SpecError(f"gold value '{name}' is missing")
    return values[name]


def check_numbers(answer: str, specs: list[dict], values: dict) -> Check:
    numbers = extract_numbers(answer)
    missing = []
    for spec in specs:
        expected = gold_value(values, spec["value"])
        ok = rate_matches(numbers, expected) if spec["kind"] == "rate" else count_matches(
            numbers, expected
        )
        if not ok:
            shown = f"{expected * 100:.1f}%" if spec["kind"] == "rate" else str(expected)
            missing.append(f"{spec['value']}={shown}")
    return Check("numbers", not missing, "missing " + ", ".join(missing) if missing else "")


# --- phrases ------------------------------------------------------------------


def fill_placeholders(pattern: str, values: dict, escape: bool = True) -> str:
    """Replace {name} with the gold value (letters/underscores only, so \\d{4} is kept)."""

    def value(match: re.Match) -> str:
        text = str(gold_value(values, match.group(1)))
        return re.escape(text) if escape else text

    return PLACEHOLDER_RE.sub(value, pattern)


def search(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.IGNORECASE) is not None


def check_required(answer: str, patterns: list[str], values: dict) -> Check:
    missing = [p for p in patterns if not search(fill_placeholders(p, values), answer)]
    return Check("required", not missing, "missing " + " | ".join(missing) if missing else "")


def check_forbidden(answer: str, patterns: list[str]) -> Check:
    found = [p for p in (*patterns, *GLOBAL_FORBIDDEN) if search(p, answer)]
    return Check("forbidden", not found, "found " + " | ".join(found) if found else "")


def check_dates(answer: str, allowed: list[str], values: dict) -> Check:
    allowed_dates = {fill_placeholders(p, values, escape=False) for p in allowed}
    extra = sorted(set(DATE_RE.findall(answer)) - allowed_dates)
    return Check("dates", not extra, "unexpected dates " + ", ".join(extra) if extra else "")


# --- tool trace -----------------------------------------------------------------


def argument_matches(actual: object, expected: object) -> bool:
    """None = must be absent; strings compare case-insensitively; others by value."""
    if expected is None:
        return actual is None
    if isinstance(expected, str):
        return isinstance(actual, str) and actual.strip().lower() == expected.lower()
    return actual is not None and str(actual) == str(expected)


def call_matches(call: dict, spec: dict, as_of: str) -> bool:
    names = spec["name"] if isinstance(spec["name"], list) else [spec["name"]]
    arguments = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
    if call.get("name") not in names:
        return False
    if not all(argument_matches(arguments.get(k), v) for k, v in spec.get("args", {}).items()):
        return False
    for key, minimum in spec.get("min_args", {}).items():
        value = arguments.get(key)
        if not isinstance(value, int) or value < minimum:
            return False
    return not spec.get("check_as_of", True) or arguments.get("as_of") == as_of


def check_tool_trace(spec: dict | None, tool_calls: list[dict], as_of: str) -> Check:
    unknown = sorted({str(c.get("name")) for c in tool_calls if c.get("name") not in TOOL_FUNCTIONS})
    if unknown:
        return Check("tool_trace", False, "unknown tools " + ", ".join(unknown))
    if spec is None:
        return Check("tool_trace", True)
    if any(call_matches(c, spec, as_of) for c in tool_calls):
        return Check("tool_trace", True)
    if spec.get("optional") and not tool_calls:
        return Check("tool_trace", True, "no tool called (allowed)")
    return Check("tool_trace", False, f"no call matching {json.dumps(spec, sort_keys=True)}")


# --- leaks ----------------------------------------------------------------------


def find_leaks(answer: str, tool_results: list[dict]) -> list[str]:
    """Forbidden field names or words in the answer or anywhere in the tool results."""
    sources = {"answer": answer, "tool results": json.dumps(tool_results, default=str)}
    return [
        f"{pattern.pattern} in {where}"
        for where, text in sources.items()
        for pattern in LEAK_PATTERNS
        if pattern.search(text)
    ]


def check_no_leak(answer: str, tool_results: list[dict]) -> Check:
    leaks = find_leaks(answer, tool_results)
    return Check("no_leak", not leaks, "; ".join(leaks))


# --- all checks -------------------------------------------------------------------


def evaluate_answer(
    question: dict, gold_values: dict, answer: str, tool_calls: list[dict], tool_results: list[dict]
) -> list[Check]:
    """Every check for one answer; the question passes only if all of them pass."""
    checks = question["checks"]
    values = {**gold_values, "as_of": question["as_of"]}
    results = []
    if checks.get("numbers"):
        results.append(check_numbers(answer, checks["numbers"], values))
    if checks.get("required"):
        results.append(check_required(answer, checks["required"], values))
    results.append(check_forbidden(answer, checks.get("forbidden", [])))
    if checks.get("dates_allowed"):
        results.append(check_dates(answer, checks["dates_allowed"], values))
    results.append(check_tool_trace(checks.get("tool"), tool_calls, question["as_of"]))
    results.append(check_no_leak(answer, tool_results))
    return results


def all_passed(checks: list[Check]) -> bool:
    return all(c.passed for c in checks)
