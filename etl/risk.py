"""Risk rule v1 (shipping-mode late rate), metrics, and report building."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields
from datetime import date

import pandas as pd

RULE_VERSION = "v1"
THRESHOLD = 0.50
SENSITIVITY_THRESHOLDS = (0.45, 0.50, 0.55)

TRAIN_START = date(2016, 4, 1)
TRAIN_END = date(2016, 6, 30)
TEST_START = date(2016, 7, 1)


@dataclass(frozen=True)
class OrderFeatures:
    """Only information known at order time (design doc section 6)."""

    shipping_mode: str
    scheduled_days: int
    order_state: str
    payment_type: str
    order_date: date
    department_names: tuple[str, ...]


ALLOWED_FEATURES = frozenset(f.name for f in fields(OrderFeatures))


@dataclass(frozen=True)
class ConfusionMatrix:
    tp: int
    fp: int
    fn: int
    tn: int


@dataclass(frozen=True)
class Metrics:
    matrix: ConfusionMatrix
    precision: float | None
    recall: float | None
    accuracy: float | None
    precision_ci: tuple[float, float] | None
    recall_ci: tuple[float, float] | None


def extract_order_features(row: Mapping) -> OrderFeatures:
    """Build OrderFeatures from a full order row, ignoring every other field."""
    return OrderFeatures(
        shipping_mode=row["shipping_mode"],
        scheduled_days=int(row["scheduled_days"]),
        order_state=row["order_state"],
        payment_type=row["payment_type"],
        order_date=row["order_date"],
        department_names=tuple(sorted(row["department_names"])),
    )


def compute_mode_late_rates(
    orders: pd.DataFrame,
    train_start: date = TRAIN_START,
    train_end: date = TRAIN_END,
) -> dict[str, float]:
    """Late rate per shipping_mode on non-excluded orders inside the training window."""
    training = training_orders(orders, train_start, train_end)
    rates = training.groupby("shipping_mode")["late_label"].mean()
    return {mode: float(rate) for mode, rate in rates.items()}


def training_orders(
    orders: pd.DataFrame,
    train_start: date = TRAIN_START,
    train_end: date = TRAIN_END,
) -> pd.DataFrame:
    mask = (
        ~orders["is_excluded"].astype(bool)
        & (orders["order_date"] >= train_start)
        & (orders["order_date"] <= train_end)
    )
    return orders.loc[mask]


def evaluation_orders(
    orders: pd.DataFrame, test_start: date = TEST_START
) -> pd.DataFrame:
    """Non-excluded orders in the test period (excluded orders are never evaluated)."""
    mask = ~orders["is_excluded"].astype(bool) & (orders["order_date"] >= test_start)
    return orders.loc[mask]


def flagged_modes(
    mode_late_rates: Mapping[str, float], threshold: float = THRESHOLD
) -> list[str]:
    return sorted(mode for mode, rate in mode_late_rates.items() if rate > threshold)


def predict_high_risk(
    order_features: OrderFeatures,
    mode_late_rates: Mapping[str, float],
    threshold: float = THRESHOLD,
) -> bool:
    """High risk when the shipping mode's training late rate is above threshold.

    Modes unseen in training are not flagged.
    """
    if not isinstance(order_features, OrderFeatures):
        raise TypeError("order_features must be an OrderFeatures instance")
    rate = mode_late_rates.get(order_features.shipping_mode)
    return rate is not None and rate > threshold


def predict_orders(
    orders: pd.DataFrame,
    mode_late_rates: Mapping[str, float],
    threshold: float = THRESHOLD,
) -> pd.Series:
    """Prediction per order row, using only extracted order-time features."""
    predictions = [
        predict_high_risk(extract_order_features(row), mode_late_rates, threshold)
        for row in orders.to_dict("records")
    ]
    return pd.Series(predictions, index=orders.index, dtype=bool)


def flag_reason(shipping_mode: str, rate: float) -> str:
    return (
        f"shipping_mode={shipping_mode}; training late rate {rate:.1%} "
        f"> {THRESHOLD:.0%}"
    )


def build_flag_rows(
    orders: pd.DataFrame,
    mode_late_rates: Mapping[str, float],
    threshold: float = THRESHOLD,
) -> list[tuple[int, date, str]]:
    """(order_id, flag_date, reason) for every high-risk order, excluded ones included."""
    predicted = predict_orders(orders, mode_late_rates, threshold)
    rows = []
    for row in orders.loc[predicted].to_dict("records"):
        mode = row["shipping_mode"]
        rows.append(
            (int(row["order_id"]), row["order_date"], flag_reason(mode, mode_late_rates[mode]))
        )
    return rows


def confusion_matrix(
    actual: Iterable[bool], predicted: Iterable[bool]
) -> ConfusionMatrix:
    tp = fp = fn = tn = 0
    for a, p in zip(actual, predicted, strict=True):
        if a and p:
            tp += 1
        elif p:
            fp += 1
        elif a:
            fn += 1
        else:
            tn += 1
    return ConfusionMatrix(tp=tp, fp=fp, fn=fn, tn=tn)


def safe_ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def wilson_interval(
    successes: int, n: int, z: float = 1.96
) -> tuple[float, float] | None:
    """95% Wilson score interval for a proportion; None when n == 0."""
    if n == 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def compute_metrics(actual: Iterable[bool], predicted: Iterable[bool]) -> Metrics:
    m = confusion_matrix(actual, predicted)
    total = m.tp + m.fp + m.fn + m.tn
    return Metrics(
        matrix=m,
        precision=safe_ratio(m.tp, m.tp + m.fp),
        recall=safe_ratio(m.tp, m.tp + m.fn),
        accuracy=safe_ratio(m.tp + m.tn, total),
        precision_ci=wilson_interval(m.tp, m.tp + m.fp),
        recall_ci=wilson_interval(m.tp, m.tp + m.fn),
    )


def evaluate_rule_and_baselines(
    evaluated: pd.DataFrame,
    mode_late_rates: Mapping[str, float],
    threshold: float = THRESHOLD,
) -> dict[str, Metrics]:
    """Metrics for rule v1, 'always late', and 'never late' on the given orders."""
    actual = evaluated["late_label"].astype(bool).tolist()
    predicted = predict_orders(evaluated, mode_late_rates, threshold).tolist()
    return {
        "rule_v1": compute_metrics(actual, predicted),
        "always_late": compute_metrics(actual, [True] * len(actual)),
        "never_late": compute_metrics(actual, [False] * len(actual)),
    }


def per_mode_table(
    evaluated: pd.DataFrame,
    mode_late_rates: Mapping[str, float],
    threshold: float = THRESHOLD,
) -> list[dict]:
    """Per shipping mode: orders, late rate, flagged, late orders missed by the rule."""
    predicted = predict_orders(evaluated, mode_late_rates, threshold)
    frame = evaluated.assign(predicted=predicted)
    rows = []
    for mode, group in sorted(frame.groupby("shipping_mode"), key=lambda kv: kv[0]):
        late = group["late_label"].astype(bool)
        rows.append(
            {
                "shipping_mode": mode,
                "orders": len(group),
                "late_rate": float(late.mean()),
                "flagged": bool(group["predicted"].any()),
                "missed_late": int((late & ~group["predicted"]).sum()),
            }
        )
    return rows


def threshold_sensitivity(
    evaluated: pd.DataFrame,
    mode_late_rates: Mapping[str, float],
    thresholds: Iterable[float] = SENSITIVITY_THRESHOLDS,
) -> list[dict]:
    """Report-only: flagged modes and test metrics at alternative thresholds."""
    actual = evaluated["late_label"].astype(bool).tolist()
    results = []
    for t in thresholds:
        predicted = predict_orders(evaluated, mode_late_rates, t).tolist()
        results.append(
            {
                "threshold": t,
                "flagged_modes": flagged_modes(mode_late_rates, t),
                "metrics": compute_metrics(actual, predicted),
            }
        )
    return results


def format_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def format_ci(ci: tuple[float, float] | None) -> str:
    return "n/a" if ci is None else f"[{ci[0]:.1%}, {ci[1]:.1%}]"


def format_pct_with_ci(value: float | None, ci: tuple[float, float] | None) -> str:
    if value is None:
        return "n/a"
    return f"{format_pct(value)} {format_ci(ci)}"


def _metrics_table(results: Mapping[str, Metrics]) -> list[str]:
    lines = [
        "| Predictor | TP | FP | FN | TN | Precision (95% CI) | Recall (95% CI) | Accuracy |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, m in results.items():
        c = m.matrix
        lines.append(
            f"| {name} | {c.tp} | {c.fp} | {c.fn} | {c.tn} | "
            f"{format_pct_with_ci(m.precision, m.precision_ci)} | "
            f"{format_pct_with_ci(m.recall, m.recall_ci)} | "
            f"{format_pct(m.accuracy)} |"
        )
    return lines


def same_day_sentence(
    mode_late_rates: Mapping[str, float], sensitivity: list[dict]
) -> str:
    rate = mode_late_rates.get("Same Day")
    if rate is None:
        return "Same Day does not appear in the training period."
    by_t = {round(r["threshold"], 2): r["flagged_modes"] for r in sensitivity}
    changes = by_t.get(0.45) != by_t.get(0.50)
    if changes:
        return (
            f"Same Day's training late rate ({rate:.1%}) is close to the 50% threshold, "
            "and the result changes at a 0.45 threshold; this is shown, not tuned."
        )
    return (
        f"Same Day's training late rate ({rate:.1%}) is close to the 50% threshold; "
        "the flagged modes do not change at a 0.45 threshold. This is shown, not tuned."
    )


def build_report(
    *,
    train_count: int,
    test_count: int,
    train_mode_counts: Mapping[str, int],
    mode_late_rates: Mapping[str, float],
    in_sample: Mapping[str, Metrics],
    test_results: Mapping[str, Metrics],
    mode_rows: list[dict],
    sensitivity: list[dict],
    flags_written: int,
    excluded_flagged: int,
    last_order_date: date,
) -> str:
    flagged = flagged_modes(mode_late_rates)
    lines = [
        f"# Risk rule {RULE_VERSION} evaluation (order level)",
        "",
        f"Rule {RULE_VERSION}: flag an order as high risk when its shipping mode's "
        f"training late rate is above {THRESHOLD:.2f}. Ground truth: `late_label`, "
        "non-excluded orders only.",
        "",
        "## Data split (non-excluded orders)",
        "",
        f"- Training period {TRAIN_START} to {TRAIN_END}: {train_count} orders",
        f"- Test period {TEST_START} to {last_order_date}: {test_count} orders",
        f"- Total: {train_count + test_count}",
        "",
        "## Training late rate per shipping mode",
        "",
        "| Shipping mode | Training orders | Late rate | Flagged |",
        "|---|---|---|---|",
    ]
    for mode in sorted(mode_late_rates):
        lines.append(
            f"| {mode} | {train_mode_counts.get(mode, 0)} | "
            f"{format_pct(mode_late_rates[mode])} | {'yes' if mode in flagged else 'no'} |"
        )
    lines += [
        "",
        f"Flagged modes: {', '.join(flagged) if flagged else 'none'}.",
        "",
        same_day_sentence(mode_late_rates, sensitivity),
        "",
        "## In-sample: training period (April–June)",
        "",
        "These numbers use the same orders the rates were computed from, so they are "
        "in-sample and optimistic. They are NOT an evaluation. Only the July–August "
        "test period below is a real evaluation.",
        "",
        *_metrics_table(in_sample),
        "",
        "## Test period evaluation (July–August) — the real evaluation",
        "",
        *_metrics_table(test_results),
        "",
        "## Test period by shipping mode",
        "",
        "| Shipping mode | Orders | Late rate | Flagged | Late orders missed |",
        "|---|---|---|---|---|",
    ]
    for r in mode_rows:
        lines.append(
            f"| {r['shipping_mode']} | {r['orders']} | {format_pct(r['late_rate'])} | "
            f"{'yes' if r['flagged'] else 'no'} | {r['missed_late']} |"
        )
    lines += [
        "",
        "## Threshold sensitivity (report only; the rule stays at 0.50)",
        "",
        "| Threshold | Flagged modes | Precision | Recall | Accuracy |",
        "|---|---|---|---|---|",
    ]
    for s in sensitivity:
        m = s["metrics"]
        lines.append(
            f"| {s['threshold']:.2f} | {', '.join(s['flagged_modes']) or 'none'} | "
            f"{format_pct(m.precision)} | {format_pct(m.recall)} | "
            f"{format_pct(m.accuracy)} |"
        )
    lines += [
        "",
        "## Flags written",
        "",
        f"- `risk_flags` rows with rule_version = '{RULE_VERSION}': {flags_written} "
        f"(of which {excluded_flagged} belong to excluded orders; they are flagged "
        "because exclusion is unknown at order time, but never evaluated).",
        "- Flags are written for all dates at once with flag_date = order_date. Any "
        "\"as of now\" reader must filter flag_date <= the simulated clock date.",
        "",
        "## Limitations",
        "",
        "This is one dataset covering about five months of 2016 US orders. The rule "
        "mirrors the dataset's scheduling pattern (for example, First Class always "
        "takes 2 days against a 1-day promise), so it reflects how the data was "
        "generated rather than real carrier behavior, and the results should not be "
        "read as real-world delivery performance. The test period is short and "
        "August is partial.",
        "",
    ]
    return "\n".join(lines)
