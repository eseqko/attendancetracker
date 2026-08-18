"""Hand-computed tests: day statuses, tier boundaries, metric assembly, CSV.

All fixtures are built inline with exact expected values — no other agents'
modules are involved.
"""

from __future__ import annotations

import io

import numpy as np
import pandas as pd
import pytest

from attendance_tracker import cohorts, export, metrics
from attendance_tracker.constants import Tier, Trend


def make_events(rows) -> pd.DataFrame:
    """rows: (student_id, date, period_or_None, code, category)."""
    return pd.DataFrame(
        {
            "student_id": pd.array([r[0] for r in rows], dtype="string"),
            "date": pd.to_datetime([r[1] for r in rows]),
            "period": pd.array([r[2] for r in rows], dtype="string"),
            "code": pd.array([r[3] for r in rows], dtype="string"),
            "category": pd.array([r[4] for r in rows], dtype="string"),
        }
    )


def make_students(ids, matched=None) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "student_id": pd.array(ids, dtype="string"),
            "match_key": pd.array(ids, dtype="string"),
            "name": pd.array([f"Student {sid}" for sid in ids], dtype="string"),
            "grade": pd.array(["07"] * len(ids), dtype="string"),
            "group": pd.array(["Resource"] * len(ids), dtype="string"),
        }
    )
    if matched is not None:
        frame["matched"] = matched
    return frame


# S1 over one school week: present, unexcused, tardy, excused, present.
DAILY_ROWS = [
    ("S1", "2025-09-08", None, "P", "present"),
    ("S1", "2025-09-09", None, "A", "absent_unexcused"),
    ("S1", "2025-09-10", None, "T", "tardy"),
    ("S1", "2025-09-11", None, "E", "absent_excused"),
    ("S1", "2025-09-12", None, "P", "present"),
]


def period_day(sid, date, codes):
    """One 7-period day; codes is a list of (code, category) per period."""
    return [
        (sid, date, str(period), code, category)
        for period, (code, category) in enumerate(codes, start=1)
    ]


def test_build_day_status_daily_events():
    day_status = metrics.build_day_status(make_events(DAILY_ROWS))
    assert len(day_status) == 5
    assert day_status["date"].is_monotonic_increasing
    assert day_status["periods_scheduled"].tolist() == [1, 1, 1, 1, 1]
    assert day_status["periods_absent"].tolist() == [0, 1, 0, 1, 0]
    assert day_status["periods_absent_excused"].tolist() == [0, 0, 0, 1, 0]
    assert day_status["periods_absent_unexcused"].tolist() == [0, 1, 0, 0, 0]
    assert day_status["periods_tardy"].tolist() == [0, 0, 1, 0, 0]
    assert day_status["is_absent_day"].tolist() == [False, True, False, True, False]
    assert day_status["is_partial_absence"].tolist() == [False] * 5
    assert day_status["is_tardy_day"].tolist() == [False, False, True, False, False]
    assert day_status["dominant_status"].tolist() == [
        "present",
        "absent_unexcused",
        "tardy",
        "absent_excused",
        "present",
    ]
    assert str(day_status["dominant_status"].dtype) == "string"
    assert str(day_status["student_id"].dtype) == "string"


def test_period_collapse_and_threshold():
    unexc = ("A", "absent_unexcused")
    pres = ("P", "present")
    rows = (
        # 3 of 7 absent -> partial at the default 0.5 threshold
        period_day("PC", "2025-09-08", [unexc, unexc, unexc, pres, pres, pres, pres])
        # 4 of 7 absent -> absent day
        + period_day("PC", "2025-09-09", [unexc] * 4 + [pres] * 3)
        # 2 of 7 absent -> partial even at threshold 0.3
        + period_day("PC", "2025-09-10", [unexc, unexc, pres, pres, pres, pres, pres])
    )
    events = make_events(rows)

    day_status = metrics.build_day_status(events)
    by_date = day_status.set_index(day_status["date"].dt.strftime("%Y-%m-%d"))
    assert by_date.loc["2025-09-08", "periods_scheduled"] == 7
    assert by_date.loc["2025-09-08", "periods_absent"] == 3
    assert not by_date.loc["2025-09-08", "is_absent_day"]
    assert by_date.loc["2025-09-08", "is_partial_absence"]
    assert by_date.loc["2025-09-08", "dominant_status"] == "partial"
    assert by_date.loc["2025-09-09", "is_absent_day"]
    assert not by_date.loc["2025-09-09", "is_partial_absence"]
    assert by_date.loc["2025-09-09", "dominant_status"] == "absent_unexcused"

    # A lower threshold turns 3/7 into a full absence but leaves 2/7 partial.
    loose = metrics.build_day_status(events, absent_day_threshold=0.3)
    loose_by_date = loose.set_index(loose["date"].dt.strftime("%Y-%m-%d"))
    assert loose_by_date.loc["2025-09-08", "is_absent_day"]
    assert loose_by_date.loc["2025-09-08", "dominant_status"] == "absent_unexcused"
    assert not loose_by_date.loc["2025-09-10", "is_absent_day"]
    assert loose_by_date.loc["2025-09-10", "is_partial_absence"]


def test_dominant_status_precedence():
    unexc = ("A", "absent_unexcused")
    exc = ("E", "absent_excused")
    tardy = ("T", "tardy")
    pres = ("P", "present")
    rows = (
        # tie 2 unexcused vs 2 excused (4/7 absent) -> unexcused wins the tie
        period_day("DM", "2025-09-08", [unexc, unexc, exc, exc, pres, pres, pres])
        # 1 unexcused vs 3 excused -> excused-dominant absent day
        + period_day("DM", "2025-09-09", [unexc, exc, exc, exc, pres, pres, pres])
        # 2 excused + 1 tardy (partial day) -> partial beats tardy
        + period_day("DM", "2025-09-10", [exc, exc, tardy, pres, pres, pres, pres])
        # tardy only
        + period_day("DM", "2025-09-11", [tardy, pres, pres, pres, pres, pres, pres])
        # all present
        + period_day("DM", "2025-09-12", [pres] * 7)
    )
    day_status = metrics.build_day_status(make_events(rows))
    assert day_status["dominant_status"].tolist() == [
        "absent_unexcused",
        "absent_excused",
        "partial",
        "tardy",
        "present",
    ]


def test_per_student_counts_and_overrides():
    rows = DAILY_ROWS + [
        ("S2", "2025-09-08", None, "P", "present"),
        ("S2", "2025-09-09", None, "P", "present"),
        ("S2", "2025-09-10", None, "P", "present"),
    ]
    day_status = metrics.build_day_status(make_events(rows))

    counts = metrics.per_student_counts(day_status).set_index("student_id")
    assert counts.loc["S1", "days_enrolled"] == 5
    assert counts.loc["S1", "days_absent"] == 2
    assert counts.loc["S1", "days_excused"] == 1
    assert counts.loc["S1", "days_unexcused"] == 1
    assert counts.loc["S1", "days_tardy"] == 1
    assert counts.loc["S2", "days_enrolled"] == 3
    assert counts.loc["S2", "days_absent"] == 0
    assert counts.loc["S2", "days_excused"] == 0
    assert counts.loc["S2", "days_unexcused"] == 0
    assert counts.loc["S2", "days_tardy"] == 0

    with_int = metrics.per_student_counts(day_status, enrolled_override=180)
    assert with_int.set_index("student_id")["days_enrolled"].tolist() == [180, 180]

    override = pd.Series([90], index=pd.Index(["S1"], name="student_id"))
    with_series = metrics.per_student_counts(
        day_status, enrolled_override=override
    ).set_index("student_id")
    assert with_series.loc["S1", "days_enrolled"] == 90
    assert pd.isna(with_series.loc["S2", "days_enrolled"])


TIER_CASES = [
    (8, 180, Tier.SATISFACTORY),  # 4.44%
    (9, 180, Tier.AT_RISK),  # exactly 5%
    (17, 180, Tier.AT_RISK),  # 9.44%
    (18, 180, Tier.CHRONIC),  # exactly 10%
    (35, 180, Tier.CHRONIC),  # 19.44%
    (36, 180, Tier.SEVERE),  # exactly 20%
]


def test_tier_boundaries_exact():
    for absent, enrolled, expected in TIER_CASES:
        assert metrics.tier_for(absent, enrolled) is expected, (absent, enrolled)

    series = metrics.tier_series(
        pd.Series([case[0] for case in TIER_CASES]),
        pd.Series([case[1] for case in TIER_CASES]),
    )
    assert series.tolist() == [case[2].value for case in TIER_CASES]
    assert str(series.dtype) == "string"

    # Missing inputs stay missing rather than defaulting to satisfactory.
    with_na = metrics.tier_series(pd.Series([np.nan, 9]), pd.Series([180, np.nan]))
    assert with_na.isna().all()


def test_tier_from_absence_pct_boundaries():
    pct = pd.Series([4.9, 5.0, 9.9, 10.0, 19.9, 20.0, 50.0, np.nan])
    tiers = metrics.tier_from_absence_pct(pct)
    assert tiers.tolist()[:-1] == [
        "satisfactory",
        "at_risk",
        "at_risk",
        "chronic",
        "chronic",
        "severe",
        "severe",
    ]
    assert pd.isna(tiers.iloc[-1])


def test_metrics_from_summary_pct_only():
    summary = pd.DataFrame(
        {
            "student_id": pd.array(["S1", "S2", "S3"], dtype="string"),
            "days_enrolled": [np.nan] * 3,
            "days_absent": [np.nan] * 3,
            "days_excused": [np.nan] * 3,
            "days_unexcused": [np.nan] * 3,
            "days_tardy": [np.nan] * 3,
            "attendance_rate": [0.95, 0.85, 0.75],
        }
    )
    students = make_students(["S1", "S2", "S3", "S4"])
    frame = metrics.metrics_from_summary(summary, students)

    assert list(frame.columns) == metrics.METRICS_COLUMNS
    assert len(frame) == 4
    by_id = frame.set_index("student_id")
    assert by_id["matched"].tolist() == [True, True, True, False]

    # Tiers from the pct implied by attendance_rate (5 / 15 / 25 percent).
    assert by_id.loc["S1", "tier"] == "at_risk"
    assert by_id.loc["S2", "tier"] == "chronic"
    assert by_id.loc["S3", "tier"] == "severe"
    assert pd.isna(by_id.loc["S4", "tier"])
    for sid, expected in [("S1", 5.0), ("S2", 15.0), ("S3", 25.0)]:
        assert abs(by_id.loc[sid, "absence_pct"] - expected) < 1e-9

    assert by_id.loc[["S1", "S2", "S3"], "trend"].tolist() == ["insufficient"] * 3
    assert pd.isna(by_id.loc["S4", "trend"])
    assert by_id["current_streak"].isna().all()
    assert by_id["max_streak"].isna().all()
    assert by_id["mon_fri_flag"].isna().all()
    assert by_id["worst_period"].isna().all()
    assert by_id["trend_slope_pp_per_week"].isna().all()


def test_metrics_from_summary_prefers_day_counts_over_pct():
    # 18/180 is exactly 10% -> chronic, even though the (inconsistent)
    # attendance_rate column would imply satisfactory.
    summary = pd.DataFrame(
        {
            "student_id": pd.array(["S1"], dtype="string"),
            "days_enrolled": [180.0],
            "days_absent": [18.0],
            "days_excused": [np.nan],
            "days_unexcused": [np.nan],
            "days_tardy": [2.0],
            "attendance_rate": [0.99],
        }
    )
    frame = metrics.metrics_from_summary(summary, make_students(["S1"]))
    assert frame.loc[0, "tier"] == "chronic"
    assert abs(frame.loc[0, "absence_pct"] - 10.0) < 1e-9


def test_metrics_from_events_keeps_unmatched_row():
    events = make_events(DAILY_ROWS)
    frame = metrics.metrics_from_events(events, make_students(["S1", "S2"]))
    assert list(frame.columns) == metrics.METRICS_COLUMNS
    assert len(frame) == 2
    by_id = frame.set_index("student_id")

    # Matched student: 2 absences of 5 days -> 40% -> severe.
    assert bool(by_id.loc["S1", "matched"])
    assert by_id.loc["S1", "days_enrolled"] == 5
    assert by_id.loc["S1", "days_absent"] == 2
    assert by_id.loc["S1", "days_excused"] == 1
    assert by_id.loc["S1", "days_unexcused"] == 1
    assert by_id.loc["S1", "days_tardy"] == 1
    assert abs(by_id.loc["S1", "attendance_rate"] - 0.6) < 1e-9
    assert abs(by_id.loc["S1", "absence_pct"] - 40.0) < 1e-9
    assert by_id.loc["S1", "tier"] == "severe"
    assert by_id.loc["S1", "trend"] == "insufficient"  # only one week of data
    assert by_id.loc["S1", "max_streak"] == 1
    assert by_id.loc["S1", "current_streak"] == 0
    assert not by_id.loc["S1", "mon_fri_flag"]  # only 2 absences (< min 5)
    assert pd.isna(by_id.loc["S1", "worst_period"])  # no period data

    # Unmatched student keeps a row with NA metrics.
    assert not bool(by_id.loc["S2", "matched"])
    for column in [
        "days_enrolled",
        "days_absent",
        "days_excused",
        "days_unexcused",
        "days_tardy",
        "attendance_rate",
        "absence_pct",
        "tier",
        "current_streak",
        "max_streak",
        "trend_slope_pp_per_week",
        "trend",
        "mon_fri_flag",
        "worst_period",
    ]:
        assert pd.isna(by_id.loc["S2", column]), column

    # An existing 'matched' column from joining is trusted as-is.
    trusted = metrics.metrics_from_events(
        events, make_students(["S1", "S2"], matched=[True, True])
    )
    assert trusted["matched"].tolist() == [True, True]


def test_csv_round_trips():
    simple = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    raw = export.frame_to_csv_bytes(simple)
    assert isinstance(raw, bytes)
    back = pd.read_csv(io.BytesIO(raw))
    assert back["a"].tolist() == [1, 2]
    assert back["b"].tolist() == ["x", "y"]

    frame = metrics.metrics_from_events(
        make_events(DAILY_ROWS), make_students(["S1", "S2"])
    )
    watchlist = pd.read_csv(io.BytesIO(export.watchlist_csv_bytes(frame)))
    assert list(watchlist.columns) == export.WATCHLIST_COLUMNS
    # Worst first: S1 (40%) then the unmatched student's empty row.
    assert watchlist["student_id"].tolist() == ["S1", "S2"]
    assert watchlist.loc[0, "absence_pct"] == 40.0
    assert watchlist.loc[0, "attendance_rate"] == 0.6
    assert watchlist.loc[0, "tier"] == "severe"
    assert pd.isna(watchlist.loc[1, "absence_pct"])


def test_student_summary_csv():
    events = make_events(DAILY_ROWS)
    frame = metrics.metrics_from_events(events, make_students(["S1"]))
    text = export.student_summary_csv_bytes(frame.iloc[0], events).decode("utf-8")

    assert "Student ID,S1" in text
    assert "Tier,severe" in text
    # Non-present history only, newest first; present days never appear.
    assert "2025-09-08" not in text and "2025-09-12" not in text
    assert text.index("2025-09-11") < text.index("2025-09-10") < text.index(
        "2025-09-09"
    )
    # Blank line separates the key/value block from the history table.
    assert "\n\ndate,period,code,category\n" in text


def test_is_exception_report():
    full = make_events(DAILY_ROWS)  # 3 of 5 events present-like (P, T, P)
    assert not metrics.is_exception_report(full)
    absences_only = full.loc[full["category"].isin(
        ["absent_unexcused", "absent_excused"]
    )]
    assert metrics.is_exception_report(absences_only)


def test_cohort_aggregates_hand_checked():
    # 10 school days; G1/G2 in grade 06, G3 in grade 07.
    days = pd.bdate_range("2025-09-08", "2025-09-19").strftime("%Y-%m-%d")
    assert len(days) == 10
    rows = []
    for sid, grade, absent_days in [
        ("G1", "06", set()),
        ("G2", "06", {"2025-09-09", "2025-09-10"}),
        ("G3", "07", {"2025-09-12"}),
    ]:
        for day in days:
            if day in absent_days:
                rows.append((sid, day, None, "A", "absent_unexcused", grade))
            else:
                rows.append((sid, day, None, "P", "present", grade))
    events = make_events([r[:5] for r in rows])
    events["grade"] = pd.array([r[5] for r in rows], dtype="string")

    baseline = cohorts.baseline_from_events(events)
    assert baseline.n_students == 3
    # rates: 1.0, 0.8, 0.9 -> mean 0.9
    assert abs(baseline.mean_attendance_rate - 0.9) < 1e-9
    assert baseline.tier_counts == {
        "satisfactory": 1,
        "at_risk": 0,
        "chronic": 1,  # 1/10 = exactly 10%
        "severe": 1,  # 2/10 = exactly 20%
    }
    by_grade = baseline.by_grade.set_index("grade")
    assert by_grade.loc["06", "n_students"] == 2
    assert abs(by_grade.loc["06", "mean_attendance_rate"] - 0.9) < 1e-9
    assert abs(by_grade.loc["06", "pct_chronic_or_worse"] - 50.0) < 1e-9
    assert abs(by_grade.loc["07", "pct_chronic_or_worse"] - 100.0) < 1e-9
    weekday = baseline.weekday_absence_rate.set_index("weekday")
    # Each weekday has 3 students x 2 weeks = 6 student-days; one absence
    # each fell on a Tue, a Wed, and a Fri -> 1/6, and Mondays stayed clean.
    assert abs(weekday.loc[1, "absence_rate"] - 1 / 6) < 1e-9
    assert abs(weekday.loc[4, "absence_rate"] - 1 / 6) < 1e-9
    assert abs(weekday.loc[0, "absence_rate"] - 0.0) < 1e-9

    # Caseload = G2 and G3, in different groups.
    students = make_students(["G2", "G3"])
    students["group"] = pd.array(["Alpha", "Beta"], dtype="string")
    frame = metrics.metrics_from_events(events, students)

    groups = cohorts.group_summary(frame, "group").set_index("group")
    assert groups.index.tolist() == ["Alpha", "Beta"]  # worst (0.8) first
    assert groups.loc["Alpha", "n_students"] == 1
    assert groups.loc["Alpha", "severe"] == 1
    assert groups.loc["Beta", "chronic"] == 1
    assert abs(groups.loc["Alpha", "mean_absence_pct"] - 20.0) < 1e-9
    assert abs(groups.loc["Beta", "pct_chronic_or_worse"] - 100.0) < 1e-9

    comparison = cohorts.caseload_vs_baseline(frame, baseline).set_index("cohort")
    assert comparison.loc["caseload", "n_students"] == 2
    assert abs(comparison.loc["caseload", "mean_attendance_rate"] - 0.85) < 1e-9
    assert abs(comparison.loc["caseload", "pct_chronic_or_worse"] - 100.0) < 1e-9
    assert comparison.loc["schoolwide", "n_students"] == 3
    assert abs(comparison.loc["schoolwide", "mean_attendance_rate"] - 0.9) < 1e-9
    assert abs(
        comparison.loc["schoolwide", "pct_chronic_or_worse"] - 200.0 / 3
    ) < 1e-9
