"""Pattern metrics: streaks, day-of-week flags, trends, period skipping.

Hand-built fixtures with exact expected values, plus an integration pass over
the seeded synthetic generator (codes mapped to categories with a plain dict —
no other agents' modules).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from attendance_tracker import metrics

CODE_CATEGORIES = {
    "P": "present",
    "A": "absent_unexcused",
    "E": "absent_excused",
    "T": "tardy",
}


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


def daily_rows_for(sid, calendar, absent_dates):
    """One daily row per calendar day: unexcused-absent or present."""
    absent = set(absent_dates)
    rows = []
    for day in calendar:
        key = day.strftime("%Y-%m-%d") if hasattr(day, "strftime") else str(day)
        if key in absent:
            rows.append((sid, key, None, "A", "absent_unexcused"))
        else:
            rows.append((sid, key, None, "P", "present"))
    return rows


def test_compute_streaks_span_weekends():
    # Thu, Fri, [weekend], Mon, Tue, Wed — five school days.
    calendar_days = ["2025-09-11", "2025-09-12", "2025-09-15", "2025-09-16",
                     "2025-09-17"]
    rows = (
        # A: absent Fri + Mon -> ONE streak of 2 across the weekend gap.
        daily_rows_for("A", calendar_days, {"2025-09-12", "2025-09-15"})
        # B: lone absence Thu, then absent the last two days -> current run 2.
        + daily_rows_for("B", calendar_days,
                         {"2025-09-11", "2025-09-16", "2025-09-17"})
        # C: never absent.
        + daily_rows_for("C", calendar_days, set())
    )
    events = make_events(rows)
    calendar = metrics.events_calendar(events)
    assert len(calendar) == 5
    assert calendar.is_monotonic_increasing

    day_status = metrics.build_day_status(events)
    streaks = metrics.compute_streaks(day_status, calendar).set_index("student_id")

    assert streaks.loc["A", "max_streak"] == 2  # Fri->Mon is one run
    assert streaks.loc["A", "current_streak"] == 0  # attended the last day
    assert streaks.loc["B", "max_streak"] == 2
    assert streaks.loc["B", "current_streak"] == 2  # run ends on the last day
    assert streaks.loc["C", "max_streak"] == 0
    assert streaks.loc["C", "current_streak"] == 0
    assert str(streaks["max_streak"].dtype) == "Int64"


def test_weekday_rates_and_mon_fri_flags():
    calendar = pd.bdate_range("2025-09-01", "2025-09-26")  # 4 full Mon-Fri weeks
    assert len(calendar) == 20
    fridays = {"2025-09-05", "2025-09-12", "2025-09-19", "2025-09-26"}
    rows = (
        # FRI: all 4 Fridays plus one Monday -> 5 absences, flagged.
        daily_rows_for("FRI", calendar, fridays | {"2025-09-01"})
        # UNI: one full absent week -> 5 absences spread evenly, NOT flagged.
        + daily_rows_for("UNI", calendar, {"2025-09-08", "2025-09-09",
                                           "2025-09-10", "2025-09-11",
                                           "2025-09-12"})
        # TWO: two Friday absences -> pattern-like but under the minimum.
        + daily_rows_for("TWO", calendar, {"2025-09-05", "2025-09-19"})
    )
    day_status = metrics.build_day_status(make_events(rows))
    rates = metrics.weekday_rates(day_status)

    indexed = rates.set_index(["student_id", "weekday"])
    assert indexed.loc[("FRI", 4), "enrolled_days"] == 4
    assert indexed.loc[("FRI", 4), "absent_days"] == 4
    assert indexed.loc[("FRI", 4), "absence_rate"] == 1.0
    assert indexed.loc[("FRI", 0), "absence_rate"] == 0.25
    assert indexed.loc[("FRI", 2), "absent_days"] == 0
    assert indexed.loc[("UNI", 1), "absence_rate"] == 0.25

    flags = metrics.mon_fri_flags(rates)
    assert bool(flags.loc["FRI"])  # Friday skipper flagged
    assert not bool(flags.loc["UNI"])  # uniform absentee not flagged
    assert not bool(flags.loc["TWO"])  # min-absences guard suppresses


def test_weekly_rates_hand_checked():
    rows = daily_rows_for(
        "W1",
        ["2025-09-08", "2025-09-09", "2025-09-10", "2025-09-11", "2025-09-12",
         "2025-09-15", "2025-09-16", "2025-09-17", "2025-09-18"],
        {"2025-09-09"},
    )
    weekly = metrics.weekly_rates(metrics.build_day_status(make_events(rows)))
    assert len(weekly) == 2
    assert weekly.loc[0, "week"] == pd.Timestamp("2025-09-08")  # week starts Monday
    assert weekly.loc[0, "school_days"] == 5
    assert weekly.loc[0, "absent_days"] == 1
    assert abs(weekly.loc[0, "rate"] - 0.8) < 1e-9
    assert weekly.loc[1, "week"] == pd.Timestamp("2025-09-15")
    assert weekly.loc[1, "school_days"] == 4
    assert abs(weekly.loc[1, "rate"] - 1.0) < 1e-9


def weekly_frame(sid, rates):
    weeks = pd.date_range("2025-09-08", periods=len(rates), freq="7D")
    return pd.DataFrame(
        {
            "student_id": pd.array([sid] * len(rates), dtype="string"),
            "week": weeks,
            "school_days": 5,
            "absent_days": 0,
            "rate": rates,
        }
    )


def test_compute_trends_classification():
    weekly = pd.concat(
        [
            weekly_frame("DECL", [1.0, 0.97, 0.94, 0.91, 0.88, 0.85]),
            weekly_frame("IMPR", [0.85, 0.88, 0.91, 0.94, 0.97, 1.0]),
            weekly_frame("FLAT", [0.9] * 6),
            weekly_frame("SHORT", [1.0, 0.97, 0.94]),  # 3 weeks < min 4
        ],
        ignore_index=True,
    )
    trends = metrics.compute_trends(weekly).set_index("student_id")

    assert trends.loc["DECL", "trend"] == "declining"
    assert abs(trends.loc["DECL", "trend_slope_pp_per_week"] + 3.0) < 1e-8
    assert trends.loc["IMPR", "trend"] == "improving"
    assert abs(trends.loc["IMPR", "trend_slope_pp_per_week"] - 3.0) < 1e-8
    assert trends.loc["FLAT", "trend"] == "stable"
    assert abs(trends.loc["FLAT", "trend_slope_pp_per_week"]) < 1e-8
    assert trends.loc["SHORT", "trend"] == "insufficient"
    assert pd.isna(trends.loc["SHORT", "trend_slope_pp_per_week"])


def test_period_table_and_skips():
    days = pd.bdate_range("2025-09-08", "2025-09-19").strftime("%Y-%m-%d")
    assert len(days) == 10
    rows = []
    for day_index, day in enumerate(days):
        for period in range(1, 8):
            # PS skips period 5 (unexcused) on the first 4 days.
            if period == 5 and day_index < 4:
                rows.append(("PS", day, str(period), "A", "absent_unexcused"))
            else:
                rows.append(("PS", day, str(period), "P", "present"))
            # UNI is fully absent on the first 4 days (all periods).
            if day_index < 4:
                rows.append(("UNI", day, str(period), "A", "absent_unexcused"))
            else:
                rows.append(("UNI", day, str(period), "P", "present"))
    table = metrics.period_table(make_events(rows))

    indexed = table.set_index(["student_id", "period"])
    assert indexed.loc[("PS", "5"), "scheduled"] == 10
    assert indexed.loc[("PS", "5"), "unexcused_absent"] == 4
    assert abs(indexed.loc[("PS", "5"), "rate"] - 0.4) < 1e-9
    assert indexed.loc[("PS", "1"), "unexcused_absent"] == 0
    assert indexed.loc[("UNI", "3"), "unexcused_absent"] == 4

    skips = metrics.period_skips(table).set_index("student_id")
    assert skips.loc["PS", "worst_period"] == "5"
    assert bool(skips.loc["PS", "skip_flag"])
    assert not bool(skips.loc["UNI", "skip_flag"])  # uniform absence, no skip
    assert pd.isna(skips.loc["UNI", "worst_period"])


def test_generator_integration(demo_dataset):
    roster = demo_dataset["roster"]
    daily = demo_dataset["daily_events"]

    events = pd.DataFrame(
        {
            "student_id": daily["student_id"].astype("string"),
            "date": pd.to_datetime(daily["date"]),
            "period": pd.array([pd.NA] * len(daily), dtype="string"),
            "code": daily["code"].astype("string"),
            "category": daily["code"].map(CODE_CATEGORIES).astype("string"),
        }
    )
    assert not events["category"].isna().any()

    caseload = roster.loc[roster["on_caseload"]]
    students = pd.DataFrame(
        {
            "student_id": caseload["student_id"].astype("string"),
            "match_key": caseload["student_id"].astype("string"),
            "name": (caseload["last_name"] + ", " + caseload["first_name"]).astype(
                "string"
            ),
            "grade": caseload["grade"].astype("string"),
            "group": caseload["program"].astype("string"),
        }
    ).reset_index(drop=True)

    frame = metrics.metrics_from_events(events, students)
    assert frame["matched"].all()
    by_id = frame.set_index("student_id")
    profiles = caseload.set_index("student_id")["profile"]

    friday_skippers = profiles.index[profiles == "friday_skipper"].tolist()
    assert friday_skippers  # the demo caseload always includes some
    for sid in friday_skippers:
        assert bool(by_id.loc[sid, "mon_fri_flag"]), f"{sid} not flagged"

    chronic_students = profiles.index[profiles == "chronic"].tolist()
    assert chronic_students
    for sid in chronic_students:
        assert by_id.loc[sid, "tier"] in {"chronic", "severe"}, sid

    # Declining-profile students: full-year slope must be negative.
    day_status = metrics.build_day_status(events)
    weekly = metrics.weekly_rates(day_status)
    trends = metrics.compute_trends(weekly, window_weeks=99).set_index("student_id")
    decliners = profiles.index[profiles == "declining"].tolist()
    assert decliners
    for sid in decliners:
        assert trends.loc[sid, "trend_slope_pp_per_week"] < 0, sid
