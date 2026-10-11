"""Unit tests for risk rule v1: leakage, metrics, flags, and report text."""

from __future__ import annotations

from dataclasses import fields
from datetime import date

import pandas as pd
import pytest

from etl.risk import (
    ALLOWED_FEATURES,
    ConfusionMatrix,
    OrderFeatures,
    build_flag_rows,
    build_report,
    compute_metrics,
    compute_mode_late_rates,
    confusion_matrix,
    evaluate_rule_and_baselines,
    evaluation_orders,
    extract_order_features,
    flag_reason,
    flagged_modes,
    format_ci,
    format_pct,
    format_pct_with_ci,
    per_mode_table,
    predict_high_risk,
    predict_orders,
    safe_ratio,
    same_day_sentence,
    threshold_sensitivity,
    training_orders,
    wilson_interval,
)

RATES = {"First Class": 1.0, "Second Class": 0.8, "Same Day": 0.46, "Standard Class": 0.4}


def make_order(order_id: int, order_date: date, mode: str, late: bool | None, **extra) -> dict:
    row = {
        "order_id": order_id,
        "order_date": order_date,
        "shipping_mode": mode,
        "scheduled_days": 1,
        "order_state": "Texas",
        "payment_type": "DEBIT",
        "department_names": ["Fan Shop"],
        "is_excluded": late is None,
        "late_label": late,
    }
    row.update(extra)
    return row


def sample_orders() -> pd.DataFrame:
    return pd.DataFrame(
        [
            make_order(1, date(2016, 4, 1), "First Class", True),
            make_order(2, date(2016, 5, 1), "Standard Class", False),
            make_order(3, date(2016, 6, 30), "Standard Class", True),
            make_order(4, date(2016, 7, 1), "First Class", True),
            make_order(5, date(2016, 7, 2), "Standard Class", True),
            make_order(6, date(2016, 7, 3), "Standard Class", False),
            make_order(7, date(2016, 7, 4), "First Class", None),  # excluded
        ]
    )


# --- leakage (a): only allowed features -----------------------------------


def test_order_features_has_only_allowed_fields() -> None:
    assert {f.name for f in fields(OrderFeatures)} == {
        "shipping_mode",
        "scheduled_days",
        "order_state",
        "payment_type",
        "order_date",
        "department_names",
    }
    assert ALLOWED_FEATURES == {f.name for f in fields(OrderFeatures)}


@pytest.mark.parametrize(
    "forbidden",
    ["completed_on", "actual_days", "delivery_status", "order_status", "late_label",
     "customer_segment"],
)
def test_order_features_rejects_forbidden_fields(forbidden: str) -> None:
    with pytest.raises(TypeError):
        OrderFeatures(
            shipping_mode="First Class",
            scheduled_days=1,
            order_state="Texas",
            payment_type="DEBIT",
            order_date=date(2016, 7, 1),
            department_names=("Fan Shop",),
            **{forbidden: "x"},
        )


def test_predict_rejects_non_feature_input() -> None:
    with pytest.raises(TypeError):
        predict_high_risk({"shipping_mode": "First Class"}, RATES)  # type: ignore[arg-type]


# --- leakage (b): forbidden fields never change the prediction -------------


@pytest.mark.parametrize(
    ("field", "values"),
    [
        ("completed_on", [date(2016, 7, 2), date(2016, 7, 30), None]),
        ("actual_days", [0, 2, 6]),
        ("delivery_status", ["Late delivery", "Shipping on time", "Shipping canceled"]),
        ("order_status", ["COMPLETE", "CANCELED", "SUSPECTED_FRAUD"]),
        ("late_label", [True, False, None]),
    ],
)
@pytest.mark.parametrize("mode", ["First Class", "Standard Class"])
def test_forbidden_fields_do_not_change_prediction(field, values, mode) -> None:
    base = make_order(1, date(2016, 7, 1), mode, True)
    predictions = {
        predict_high_risk(extract_order_features({**base, field: v}), RATES)
        for v in values
    }
    assert len(predictions) == 1


# --- leakage (c): training rates use only order_date <= 2016-06-30 ---------


def test_training_rates_ignore_test_period_orders() -> None:
    orders = sample_orders()
    rates = compute_mode_late_rates(orders)
    # Training: First Class 1/1, Standard Class 1/2 (includes boundary 2016-06-30).
    assert rates == {"First Class": 1.0, "Standard Class": 0.5}

    flipped = orders.copy()
    july = flipped["order_date"] >= date(2016, 7, 1)
    flipped.loc[july & ~flipped["is_excluded"], "late_label"] = False
    flipped.loc[july, "shipping_mode"] = "Same Day"
    assert compute_mode_late_rates(flipped) == rates


def test_training_rates_ignore_excluded_orders() -> None:
    orders = pd.DataFrame(
        [
            make_order(1, date(2016, 4, 1), "Same Day", False),
            make_order(2, date(2016, 4, 2), "Same Day", None),
        ]
    )
    assert compute_mode_late_rates(orders) == {"Same Day": 0.0}


def test_training_and_evaluation_split() -> None:
    orders = sample_orders()
    assert training_orders(orders)["order_id"].tolist() == [1, 2, 3]
    assert evaluation_orders(orders)["order_id"].tolist() == [4, 5, 6]


# --- rule ------------------------------------------------------------------


def test_flagged_modes_strictly_above_threshold() -> None:
    assert flagged_modes(RATES) == ["First Class", "Second Class"]
    assert flagged_modes(RATES, 0.45) == ["First Class", "Same Day", "Second Class"]
    assert flagged_modes({"X": 0.5}) == []


def test_predict_unseen_mode_not_flagged() -> None:
    features = extract_order_features(make_order(1, date(2016, 7, 1), "Drone", True))
    assert predict_high_risk(features, RATES) is False


def test_predict_orders_series() -> None:
    orders = sample_orders()
    assert predict_orders(orders, RATES).tolist() == [
        True, False, False, True, False, False, True,
    ]


# --- metrics ---------------------------------------------------------------


def test_confusion_and_metrics_known_answers() -> None:
    actual = [True, True, False, False, True]
    predicted = [True, False, True, False, True]
    assert confusion_matrix(actual, predicted) == ConfusionMatrix(tp=2, fp=1, fn=1, tn=1)
    m = compute_metrics(actual, predicted)
    assert m.precision == pytest.approx(2 / 3)
    assert m.recall == pytest.approx(2 / 3)
    assert m.accuracy == pytest.approx(3 / 5)


def test_zero_flagged_orders_no_division_by_zero() -> None:
    m = compute_metrics([True, False, True], [False, False, False])
    assert m.matrix == ConfusionMatrix(tp=0, fp=0, fn=2, tn=1)
    assert m.precision is None
    assert m.precision_ci is None
    assert m.recall == 0.0
    assert m.accuracy == pytest.approx(1 / 3)


def test_empty_input_metrics() -> None:
    m = compute_metrics([], [])
    assert m.precision is None and m.recall is None and m.accuracy is None


def test_safe_ratio() -> None:
    assert safe_ratio(1, 4) == 0.25
    assert safe_ratio(1, 0) is None


def test_wilson_interval_known_values() -> None:
    low, high = wilson_interval(50, 100)
    assert low == pytest.approx(0.4038, abs=1e-3)
    assert high == pytest.approx(0.5962, abs=1e-3)
    low, high = wilson_interval(10, 10)
    assert high == 1.0 and 0.69 < low < 0.73
    assert wilson_interval(0, 0) is None


def test_baselines() -> None:
    evaluated = evaluation_orders(sample_orders())
    results = evaluate_rule_and_baselines(evaluated, RATES)
    assert results["always_late"].matrix == ConfusionMatrix(tp=2, fp=1, fn=0, tn=0)
    assert results["never_late"].matrix == ConfusionMatrix(tp=0, fp=0, fn=2, tn=1)
    assert results["never_late"].precision is None
    assert results["rule_v1"].matrix == ConfusionMatrix(tp=1, fp=0, fn=1, tn=1)


def test_per_mode_table() -> None:
    evaluated = evaluation_orders(sample_orders())
    rows = per_mode_table(evaluated, RATES)
    assert rows == [
        {"shipping_mode": "First Class", "orders": 1, "late_rate": 1.0,
         "flagged": True, "missed_late": 0},
        {"shipping_mode": "Standard Class", "orders": 2, "late_rate": 0.5,
         "flagged": False, "missed_late": 1},
    ]


# --- flags -----------------------------------------------------------------


def test_excluded_orders_flagged_but_not_evaluated() -> None:
    orders = sample_orders()
    flag_rows = build_flag_rows(orders, RATES)
    flagged_ids = {order_id for order_id, _, _ in flag_rows}
    assert 7 in flagged_ids
    assert 7 not in evaluation_orders(orders)["order_id"].tolist()
    assert 7 not in training_orders(orders)["order_id"].tolist()


def test_build_flag_rows_dates_and_reason() -> None:
    rows = build_flag_rows(sample_orders(), RATES)
    assert rows[0] == (1, date(2016, 4, 1), flag_reason("First Class", 1.0))
    assert all(flag_date for _, flag_date, _ in rows)
    assert "First Class" in rows[0][2] and "100.0%" in rows[0][2]


# --- report ----------------------------------------------------------------


def test_format_helpers() -> None:
    assert format_pct(None) == "n/a"
    assert format_pct(0.5) == "50.0%"
    assert format_ci(None) == "n/a"
    assert format_ci((0.1, 0.2)) == "[10.0%, 20.0%]"
    assert format_pct_with_ci(None, None) == "n/a"
    assert format_pct_with_ci(0.5, (0.4, 0.6)) == "50.0% [40.0%, 60.0%]"


def test_same_day_sentence_when_result_changes() -> None:
    evaluated = evaluation_orders(sample_orders())
    sensitivity = threshold_sensitivity(evaluated, RATES)
    sentence = same_day_sentence({**RATES, "Same Day": 0.4598}, sensitivity)
    assert sentence == (
        "Same Day's training late rate (46.0%) is close to the 50% threshold, "
        "and the result changes at a 0.45 threshold; this is shown, not tuned."
    )


def test_threshold_sensitivity_flagged_modes() -> None:
    evaluated = evaluation_orders(sample_orders())
    results = threshold_sensitivity(evaluated, RATES)
    assert [r["threshold"] for r in results] == [0.45, 0.50, 0.55]
    assert "Same Day" in results[0]["flagged_modes"]
    assert results[1]["flagged_modes"] == results[2]["flagged_modes"]


def test_build_report_labels_in_sample_and_as_of() -> None:
    orders = sample_orders()
    training = training_orders(orders)
    evaluated = evaluation_orders(orders)
    report = build_report(
        train_count=len(training),
        test_count=len(evaluated),
        train_mode_counts=training["shipping_mode"].value_counts().to_dict(),
        mode_late_rates=RATES,
        in_sample=evaluate_rule_and_baselines(training, RATES),
        test_results=evaluate_rule_and_baselines(evaluated, RATES),
        mode_rows=per_mode_table(evaluated, RATES),
        sensitivity=threshold_sensitivity(evaluated, RATES),
        flags_written=3,
        excluded_flagged=1,
        last_order_date=date(2016, 7, 4),
    )
    assert "in-sample" in report
    assert "Only the July–August test period below is a real evaluation." in report
    assert "flag_date <= the simulated clock date" in report
    assert "## Limitations" in report
    assert "this is shown, not tuned" in report
