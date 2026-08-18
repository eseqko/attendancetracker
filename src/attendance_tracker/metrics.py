"""Per-student attendance metrics: day statuses, tiers, streaks, patterns.

Every function is a pure pandas/numpy transform over the canonical frames
produced by normalization and joining:

- ``events``: one row per attendance event — ``student_id`` (string), ``date``
  (datetime64 at midnight), ``period`` (string, ``pd.NA`` for daily rows),
  ``code`` (string), ``category`` (string, a ``Category.value``).
- ``summary``: one row per student with day totals (float, NaN where unknown)
  and/or ``attendance_rate`` (0..1).
- ``students``: the caseload roster — ``student_id``, ``name``, ``grade``,
  ``group`` (string), optional ``matched`` (bool).

Tier boundaries use integer cross-multiplication (``absent * 100 >= bound *
enrolled``) so boundary cases like 9/180 land exactly on their tier with no
floating-point drift.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .constants import (
    ABSENT_CATEGORIES,
    DEFAULT_ABSENT_DAY_THRESHOLD,
    DOW_FLAG_RATIO,
    EXCEPTION_REPORT_PRESENT_SHARE,
    MIN_ABSENCES_FOR_DOW_FLAG,
    PERIOD_SKIP_MIN_COUNT,
    PERIOD_SKIP_RATIO,
    PRESENT_LIKE_CATEGORIES,
    TREND_MIN_WEEKS,
    TREND_SLOPE_CUTOFF,
    TREND_WINDOW_WEEKS,
    Category,
    Tier,
    Trend,
)

#: Category *values* (plain strings) for vectorized membership tests — enum
#: members hash by name, so frozensets of members don't match value strings
#: stored in canonical frames.
_ABSENT_VALUES = frozenset(c.value for c in ABSENT_CATEGORIES)
_PRESENT_LIKE_VALUES = frozenset(c.value for c in PRESENT_LIKE_CATEGORIES)

#: dominant_status value for days with some but not enough absent periods.
PARTIAL_STATUS = "partial"

#: Metrics-frame columns, in output order.
METRICS_COLUMNS = [
    "student_id",
    "name",
    "grade",
    "group",
    "matched",
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
]

_COUNT_COLUMNS = [
    "days_enrolled",
    "days_absent",
    "days_excused",
    "days_unexcused",
    "days_tardy",
]


# ---------------------------------------------------------------------------
# Calendar / report character
# ---------------------------------------------------------------------------


def events_calendar(events: pd.DataFrame) -> pd.DatetimeIndex:
    """Sorted distinct dates across ALL students — the school-day calendar."""
    return pd.DatetimeIndex(events["date"].dropna().unique()).sort_values()


def is_exception_report(events: pd.DataFrame) -> bool:
    """True when almost no events are present-like (absences-only export)."""
    if not len(events):
        return True
    share = float(
        events["category"]
        .astype("string")
        .isin(_PRESENT_LIKE_VALUES)
        .fillna(False)
        .mean()
    )
    return share < EXCEPTION_REPORT_PRESENT_SHARE


# ---------------------------------------------------------------------------
# Day status
# ---------------------------------------------------------------------------


def _empty_day_status() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "student_id": pd.array([], dtype="string"),
            "date": pd.Series([], dtype="datetime64[ns]"),
            "periods_scheduled": pd.Series([], dtype="int64"),
            "periods_absent": pd.Series([], dtype="int64"),
            "periods_absent_excused": pd.Series([], dtype="int64"),
            "periods_absent_unexcused": pd.Series([], dtype="int64"),
            "periods_tardy": pd.Series([], dtype="int64"),
            "is_absent_day": pd.Series([], dtype="bool"),
            "is_partial_absence": pd.Series([], dtype="bool"),
            "is_tardy_day": pd.Series([], dtype="bool"),
            "dominant_status": pd.array([], dtype="string"),
        }
    )


def build_day_status(
    events: pd.DataFrame,
    absent_day_threshold: float = DEFAULT_ABSENT_DAY_THRESHOLD,
) -> pd.DataFrame:
    """Collapse events to one row per student per date.

    Daily rows (one event per day) get ``periods_scheduled == 1``; period rows
    are counted per day. A day is absent when the absent-period share reaches
    ``absent_day_threshold``.
    """
    if not len(events):
        return _empty_day_status()

    category = events["category"].astype("string")
    work = pd.DataFrame(
        {
            "student_id": events["student_id"].astype("string"),
            "date": events["date"],
            "scheduled": np.ones(len(events), dtype="int64"),
            "absent": category.isin(_ABSENT_VALUES).fillna(False).astype("int64"),
            "excused": (category == Category.ABSENT_EXCUSED.value)
            .fillna(False)
            .astype("int64"),
            "unexcused": (category == Category.ABSENT_UNEXCUSED.value)
            .fillna(False)
            .astype("int64"),
            "tardy": (category == Category.TARDY.value).fillna(False).astype("int64"),
        }
    )
    day = (
        work.groupby(["student_id", "date"], observed=True)
        .agg(
            periods_scheduled=("scheduled", "sum"),
            periods_absent=("absent", "sum"),
            periods_absent_excused=("excused", "sum"),
            periods_absent_unexcused=("unexcused", "sum"),
            periods_tardy=("tardy", "sum"),
        )
        .reset_index()
        .sort_values(["student_id", "date"], kind="mergesort")
        .reset_index(drop=True)
    )

    scheduled = day["periods_scheduled"].to_numpy(dtype="int64")
    absent = day["periods_absent"].to_numpy(dtype="int64")
    excused = day["periods_absent_excused"].to_numpy(dtype="int64")
    unexcused = day["periods_absent_unexcused"].to_numpy(dtype="int64")
    tardy = day["periods_tardy"].to_numpy(dtype="int64")

    is_absent_day = absent / scheduled >= absent_day_threshold
    is_partial = (absent > 0) & ~is_absent_day
    is_tardy_day = tardy > 0

    day["is_absent_day"] = is_absent_day
    day["is_partial_absence"] = is_partial
    day["is_tardy_day"] = is_tardy_day
    day["dominant_status"] = pd.array(
        np.select(
            [
                is_absent_day & (unexcused >= excused),
                is_absent_day,
                is_partial,
                is_tardy_day,
            ],
            [
                Category.ABSENT_UNEXCUSED.value,
                Category.ABSENT_EXCUSED.value,
                PARTIAL_STATUS,
                Category.TARDY.value,
            ],
            default=Category.PRESENT.value,
        ),
        dtype="string",
    )
    return day


def per_student_counts(
    day_status: pd.DataFrame,
    enrolled_override: int | pd.Series | None = None,
) -> pd.DataFrame:
    """Per-student day totals derived from a day-status frame.

    ``days_enrolled`` is the student's distinct dates unless an override is
    given: an int applied to every student, or a Series indexed by student_id.
    ``days_excused``/``days_unexcused`` split *absent days* by dominant_status.
    """
    grouped = day_status.groupby("student_id", observed=True)
    out = pd.DataFrame(
        {
            "days_enrolled": grouped["date"].nunique(),
            "days_absent": grouped["is_absent_day"].sum(),
            "days_tardy": grouped["is_tardy_day"].sum(),
        }
    )

    absent_days = day_status.loc[day_status["is_absent_day"].astype(bool)]
    dominant = absent_days["dominant_status"].astype("string")
    excused = (
        absent_days.loc[(dominant == Category.ABSENT_EXCUSED.value).fillna(False)]
        .groupby("student_id", observed=True)
        .size()
    )
    unexcused = (
        absent_days.loc[(dominant == Category.ABSENT_UNEXCUSED.value).fillna(False)]
        .groupby("student_id", observed=True)
        .size()
    )
    out["days_excused"] = excused.reindex(out.index).fillna(0)
    out["days_unexcused"] = unexcused.reindex(out.index).fillna(0)

    if enrolled_override is not None:
        if isinstance(enrolled_override, pd.Series):
            override = enrolled_override.copy()
            override.index = override.index.astype("string")
            out["days_enrolled"] = override.reindex(out.index)
        else:
            out["days_enrolled"] = int(enrolled_override)

    out = out.reset_index()
    out["student_id"] = out["student_id"].astype("string")
    for column in _COUNT_COLUMNS:
        out[column] = out[column].astype("Int64")
    return out[["student_id"] + _COUNT_COLUMNS]


# ---------------------------------------------------------------------------
# Tiers
# ---------------------------------------------------------------------------


def tier_for(days_absent: float, days_enrolled: float) -> Tier:
    """Tier for one student's day counts (assumes ``days_enrolled > 0``)."""
    if days_absent * 100 >= 20 * days_enrolled:
        return Tier.SEVERE
    if days_absent * 100 >= 10 * days_enrolled:
        return Tier.CHRONIC
    if days_absent * 100 >= 5 * days_enrolled:
        return Tier.AT_RISK
    return Tier.SATISFACTORY


def tier_series(days_absent: pd.Series, days_enrolled: pd.Series) -> pd.Series:
    """Vectorized tiers (Tier.value strings, string dtype).

    Boundary semantics are exact via cross-multiplication — no percentage
    division. Rows with missing (or non-positive) enrolled days get ``pd.NA``.
    """
    absent_series = pd.Series(days_absent)
    enrolled_series = pd.Series(days_enrolled)
    absent = pd.to_numeric(absent_series, errors="coerce").astype("float64").to_numpy()
    enrolled = (
        pd.to_numeric(enrolled_series, errors="coerce").astype("float64").to_numpy()
    )

    valid = ~np.isnan(absent) & ~np.isnan(enrolled) & (enrolled > 0)
    scaled = absent * 100.0
    values = np.select(
        [scaled >= 20.0 * enrolled, scaled >= 10.0 * enrolled, scaled >= 5.0 * enrolled],
        [Tier.SEVERE.value, Tier.CHRONIC.value, Tier.AT_RISK.value],
        default=Tier.SATISFACTORY.value,
    )
    result = pd.Series(
        pd.array(values, dtype="string"), index=absent_series.index, name="tier"
    )
    result[~valid] = pd.NA
    return result


def tier_from_absence_pct(absence_pct: pd.Series) -> pd.Series:
    """Tier fallback for pct-only summary reports (>=20 / >=10 / >=5)."""
    pct_series = pd.Series(absence_pct)
    pct = pd.to_numeric(pct_series, errors="coerce").astype("float64").to_numpy()
    values = np.select(
        [pct >= 20.0, pct >= 10.0, pct >= 5.0],
        [Tier.SEVERE.value, Tier.CHRONIC.value, Tier.AT_RISK.value],
        default=Tier.SATISFACTORY.value,
    )
    result = pd.Series(
        pd.array(values, dtype="string"), index=pct_series.index, name="tier"
    )
    result[np.isnan(pct)] = pd.NA
    return result


# ---------------------------------------------------------------------------
# Streaks
# ---------------------------------------------------------------------------


def compute_streaks(
    day_status: pd.DataFrame, calendar: pd.DatetimeIndex
) -> pd.DataFrame:
    """Longest and current runs of absent days in school-day index space.

    Adjacency is positional in the calendar, so weekends and breaks never
    interrupt a streak. ``current_streak`` is the length of the run ending on
    the LAST calendar day (0 when the student attended it).
    """
    n_days = len(calendar)
    students = day_status["student_id"].astype("string").drop_duplicates().tolist()
    positions_by_date = pd.Series(np.arange(n_days), index=pd.DatetimeIndex(calendar))

    current: dict[str, int] = {sid: 0 for sid in students}
    longest: dict[str, int] = {sid: 0 for sid in students}

    absent = day_status.loc[day_status["is_absent_day"].astype(bool)]
    for sid, group in absent.groupby("student_id", observed=True):
        mapped = group["date"].map(positions_by_date).dropna()
        positions = np.unique(mapped.to_numpy(dtype="int64"))
        if not len(positions):
            continue
        run_ids = positions - np.arange(len(positions))
        _, run_lengths = np.unique(run_ids, return_counts=True)
        longest[str(sid)] = int(run_lengths.max())
        if n_days and positions[-1] == n_days - 1:
            current[str(sid)] = int(run_lengths[-1])

    return pd.DataFrame(
        {
            "student_id": pd.array(students, dtype="string"),
            "current_streak": pd.array(
                [current[sid] for sid in students], dtype="Int64"
            ),
            "max_streak": pd.array([longest[sid] for sid in students], dtype="Int64"),
        }
    )


# ---------------------------------------------------------------------------
# Day-of-week patterns
# ---------------------------------------------------------------------------


def weekday_rates(day_status: pd.DataFrame) -> pd.DataFrame:
    """Per student x weekday (0=Mon..4=Fri): enrolled/absent days and rate."""
    if not len(day_status):
        return pd.DataFrame(
            {
                "student_id": pd.array([], dtype="string"),
                "weekday": pd.Series([], dtype="int64"),
                "enrolled_days": pd.Series([], dtype="int64"),
                "absent_days": pd.Series([], dtype="int64"),
                "absence_rate": pd.Series([], dtype="float64"),
            }
        )
    work = pd.DataFrame(
        {
            "student_id": day_status["student_id"].astype("string"),
            "weekday": day_status["date"].dt.weekday.astype("int64"),
            "is_absent_day": day_status["is_absent_day"].astype(bool),
        }
    )
    out = (
        work.groupby(["student_id", "weekday"], observed=True)
        .agg(
            enrolled_days=("is_absent_day", "size"),
            absent_days=("is_absent_day", "sum"),
        )
        .reset_index()
    )
    out["absence_rate"] = out["absent_days"] / out["enrolled_days"]
    return out


def mon_fri_flags(weekday_rates_frame: pd.DataFrame) -> pd.Series:
    """Boolean Series (index student_id): Monday/Friday absence pattern.

    Flag when Mon or Fri absence rate reaches ``DOW_FLAG_RATIO`` times the
    Tue-Thu mean rate and the student has at least
    ``MIN_ABSENCES_FOR_DOW_FLAG`` total absences. When the Tue-Thu mean is 0
    the ratio test degenerates, so the flag instead requires a positive
    Mon/Fri rate (plus the absence minimum).
    """
    if not len(weekday_rates_frame):
        return pd.Series(
            [],
            dtype=bool,
            name="mon_fri_flag",
            index=pd.Index([], dtype="string", name="student_id"),
        )
    rates = weekday_rates_frame.pivot_table(
        index="student_id", columns="weekday", values="absence_rate", aggfunc="mean"
    ).reindex(columns=range(5))
    monday = rates[0].fillna(0.0)
    friday = rates[4].fillna(0.0)
    midweek = rates[[1, 2, 3]].mean(axis=1).fillna(0.0)
    total_absences = (
        weekday_rates_frame.groupby("student_id", observed=True)["absent_days"]
        .sum()
        .reindex(rates.index)
        .fillna(0)
    )

    ratio_hit = (monday >= DOW_FLAG_RATIO * midweek) | (
        friday >= DOW_FLAG_RATIO * midweek
    )
    zero_mid_hit = (monday > 0) | (friday > 0)
    flagged = np.where(midweek > 0, ratio_hit, zero_mid_hit) & (
        total_absences >= MIN_ABSENCES_FOR_DOW_FLAG
    ).to_numpy()

    result = pd.Series(flagged, index=rates.index, name="mon_fri_flag", dtype=bool)
    result.index.name = "student_id"
    return result


# ---------------------------------------------------------------------------
# Weekly rates and trends
# ---------------------------------------------------------------------------


def weekly_rates(day_status: pd.DataFrame) -> pd.DataFrame:
    """Per student x week (week-start date): school days, absences, rate.

    Weeks with zero school days simply never appear (groupby only sees dates
    that exist). ``rate`` is the attendance rate: 1 - absent/school_days.
    """
    if not len(day_status):
        return pd.DataFrame(
            {
                "student_id": pd.array([], dtype="string"),
                "week": pd.Series([], dtype="datetime64[ns]"),
                "school_days": pd.Series([], dtype="int64"),
                "absent_days": pd.Series([], dtype="int64"),
                "rate": pd.Series([], dtype="float64"),
            }
        )
    work = pd.DataFrame(
        {
            "student_id": day_status["student_id"].astype("string"),
            "week": day_status["date"].dt.to_period("W").dt.start_time,
            "is_absent_day": day_status["is_absent_day"].astype(bool),
        }
    )
    out = (
        work.groupby(["student_id", "week"], observed=True)
        .agg(
            school_days=("is_absent_day", "size"),
            absent_days=("is_absent_day", "sum"),
        )
        .reset_index()
        .sort_values(["student_id", "week"], kind="mergesort")
        .reset_index(drop=True)
    )
    out = out.loc[out["school_days"] > 0].reset_index(drop=True)
    out["rate"] = 1 - out["absent_days"] / out["school_days"]
    return out


def compute_trends(
    weekly: pd.DataFrame,
    window_weeks: int = TREND_WINDOW_WEEKS,
    min_weeks: int = TREND_MIN_WEEKS,
) -> pd.DataFrame:
    """Least-squares slope of weekly attendance rate over the recent window.

    The slope comes from ``np.polyfit`` over the student's LAST
    ``window_weeks`` weeks (rate-units per week); ``trend_slope_pp_per_week``
    is that slope times 100. Students with fewer than ``min_weeks`` weeks get
    trend 'insufficient' and a NaN slope.
    """
    ids: list[str] = []
    slopes: list[float] = []
    trends: list[str] = []
    for sid, group in weekly.groupby("student_id", observed=True):
        rates = (
            group.sort_values("week")["rate"].to_numpy(dtype="float64")[-window_weeks:]
        )
        ids.append(str(sid))
        if len(rates) < min_weeks or len(rates) < 2:
            slopes.append(float("nan"))
            trends.append(Trend.INSUFFICIENT.value)
            continue
        slope = float(np.polyfit(np.arange(len(rates)), rates, 1)[0])
        slopes.append(slope * 100.0)
        if slope >= TREND_SLOPE_CUTOFF:
            trends.append(Trend.IMPROVING.value)
        elif slope <= -TREND_SLOPE_CUTOFF:
            trends.append(Trend.DECLINING.value)
        else:
            trends.append(Trend.STABLE.value)
    return pd.DataFrame(
        {
            "student_id": pd.array(ids, dtype="string"),
            "trend_slope_pp_per_week": pd.Series(slopes, dtype="float64"),
            "trend": pd.array(trends, dtype="string"),
        }
    )


# ---------------------------------------------------------------------------
# Period skipping
# ---------------------------------------------------------------------------


def _empty_period_table() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "student_id": pd.array([], dtype="string"),
            "period": pd.array([], dtype="string"),
            "scheduled": pd.Series([], dtype="int64"),
            "unexcused_absent": pd.Series([], dtype="int64"),
            "rate": pd.Series([], dtype="float64"),
        }
    )


def period_table(events: pd.DataFrame) -> pd.DataFrame:
    """Per student x period: scheduled count, unexcused misses, miss rate.

    Uses PERIOD rows only (period not NA); daily rows contribute nothing.
    """
    if "period" not in events.columns:
        return _empty_period_table()
    period_rows = events.loc[events["period"].notna()]
    if not len(period_rows):
        return _empty_period_table()

    category = period_rows["category"].astype("string")
    work = pd.DataFrame(
        {
            "student_id": period_rows["student_id"].astype("string"),
            "period": period_rows["period"].astype("string"),
            "unexcused": (category == Category.ABSENT_UNEXCUSED.value)
            .fillna(False)
            .astype("int64"),
        }
    )
    out = (
        work.groupby(["student_id", "period"], observed=True)
        .agg(scheduled=("unexcused", "size"), unexcused_absent=("unexcused", "sum"))
        .reset_index()
    )
    out["rate"] = out["unexcused_absent"] / out["scheduled"]
    return out


def period_skips(period_table_frame: pd.DataFrame) -> pd.DataFrame:
    """Flag students whose unexcused misses concentrate in one period.

    A period qualifies when it has at least ``PERIOD_SKIP_MIN_COUNT``
    unexcused misses AND its miss rate is at least ``PERIOD_SKIP_RATIO`` times
    the mean rate of the student's OTHER periods (treated as 0 for a student
    with a single period). ``worst_period`` is the qualifying period with the
    highest rate, ``pd.NA`` when nothing qualifies.
    """
    if not len(period_table_frame):
        return pd.DataFrame(
            {
                "student_id": pd.array([], dtype="string"),
                "worst_period": pd.array([], dtype="string"),
                "skip_flag": pd.Series([], dtype="bool"),
            }
        )
    table = period_table_frame.copy()
    grouped = table.groupby("student_id", observed=True)["rate"]
    total_rate = grouped.transform("sum")
    n_periods = grouped.transform("count")
    other_mean = ((total_rate - table["rate"]) / (n_periods - 1)).where(
        n_periods > 1, 0.0
    )
    qualifies = (table["unexcused_absent"] >= PERIOD_SKIP_MIN_COUNT) & (
        table["rate"] >= PERIOD_SKIP_RATIO * other_mean
    )
    qualifying = (
        table.loc[qualifies]
        .sort_values(["student_id", "rate"], ascending=[True, False], kind="mergesort")
        .drop_duplicates("student_id")
    )
    worst_by_id = dict(
        zip(qualifying["student_id"].tolist(), qualifying["period"].tolist())
    )

    ids = table["student_id"].astype("string").drop_duplicates().tolist()
    return pd.DataFrame(
        {
            "student_id": pd.array(ids, dtype="string"),
            "worst_period": pd.array(
                [worst_by_id.get(sid, pd.NA) for sid in ids], dtype="string"
            ),
            "skip_flag": pd.Series([sid in worst_by_id for sid in ids], dtype="bool"),
        }
    )


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def _caseload_base(students: pd.DataFrame, report_ids: set) -> pd.DataFrame:
    """students frame -> student_id/name/grade/group/matched skeleton."""
    base = pd.DataFrame({"student_id": students["student_id"].astype("string")})
    for column in ("name", "grade", "group"):
        if column in students.columns:
            base[column] = students[column].astype("string").to_numpy()
        else:
            base[column] = pd.array([pd.NA] * len(students), dtype="string")
    if "matched" in students.columns:
        matched = students["matched"].fillna(False).astype(bool)
    else:
        matched = base["student_id"].isin(report_ids).fillna(False).astype(bool)
    base["matched"] = matched.to_numpy(dtype=bool)
    return base.reset_index(drop=True)


def _finalize_metrics(out: pd.DataFrame) -> pd.DataFrame:
    """Coerce the assembled frame to canonical dtypes and column order."""
    for column in _COUNT_COLUMNS:
        out[column] = out[column].astype("Int64")
    out["current_streak"] = out["current_streak"].astype("Int64")
    out["max_streak"] = out["max_streak"].astype("Int64")
    out["trend_slope_pp_per_week"] = pd.to_numeric(
        out["trend_slope_pp_per_week"], errors="coerce"
    )
    out["trend"] = out["trend"].astype("string")
    out["mon_fri_flag"] = out["mon_fri_flag"].astype("boolean")
    out["worst_period"] = out["worst_period"].astype("string")
    out["tier"] = out["tier"].astype("string")
    return out[METRICS_COLUMNS]


def metrics_from_events(
    events: pd.DataFrame,
    students: pd.DataFrame,
    absent_day_threshold: float = DEFAULT_ABSENT_DAY_THRESHOLD,
    enrolled_override: int | pd.Series | None = None,
) -> pd.DataFrame:
    """Assemble the per-student metrics frame from day/period events.

    Left-joins onto the caseload students frame, so unmatched students keep a
    row with NA metrics and ``matched=False``. If ``students`` already carries
    a 'matched' column (from joining) it is trusted; otherwise a student is
    matched when they appear in ``events``.
    """
    day_status = build_day_status(events, absent_day_threshold)
    counts = per_student_counts(day_status, enrolled_override)
    streaks = compute_streaks(day_status, events_calendar(events))
    flags = mon_fri_flags(weekday_rates(day_status))
    trends = compute_trends(weekly_rates(day_status))
    skips = period_skips(period_table(events))

    report_ids = set(events["student_id"].astype("string").dropna().tolist())
    out = _caseload_base(students, report_ids)
    out = out.merge(counts, on="student_id", how="left")
    out["attendance_rate"] = 1 - out["days_absent"] / out["days_enrolled"]
    out["absence_pct"] = 100 * out["days_absent"] / out["days_enrolled"]
    out["tier"] = tier_series(out["days_absent"], out["days_enrolled"])

    flag_frame = flags.rename("mon_fri_flag").reset_index()
    flag_frame["student_id"] = flag_frame["student_id"].astype("string")
    flag_frame["mon_fri_flag"] = flag_frame["mon_fri_flag"].astype("boolean")

    out = out.merge(streaks, on="student_id", how="left")
    out = out.merge(trends, on="student_id", how="left")
    out = out.merge(flag_frame, on="student_id", how="left")
    out = out.merge(skips[["student_id", "worst_period"]], on="student_id", how="left")
    return _finalize_metrics(out)


def metrics_from_summary(
    summary: pd.DataFrame, students: pd.DataFrame
) -> pd.DataFrame:
    """Assemble the metrics frame from a per-student summary report.

    Time-based columns (streaks, trend slope, Mon/Fri flag, worst period) are
    all NA and matched students get trend 'insufficient'. Tiers come from day
    counts when present, else from ``tier_from_absence_pct`` on the percentage
    implied by ``attendance_rate``.
    """
    value_columns = _COUNT_COLUMNS + ["attendance_rate"]
    values = summary.copy()
    values["student_id"] = values["student_id"].astype("string")
    for column in value_columns:
        if column in values.columns:
            values[column] = pd.to_numeric(values[column], errors="coerce")
        else:
            values[column] = np.nan

    report_ids = set(values["student_id"].dropna().tolist())
    out = _caseload_base(students, report_ids)
    out = out.merge(values[["student_id"] + value_columns], on="student_id", how="left")

    count_pct = 100 * out["days_absent"] / out["days_enrolled"]
    out["absence_pct"] = count_pct.fillna(100 * (1 - out["attendance_rate"]))
    out["attendance_rate"] = out["attendance_rate"].fillna(
        1 - out["days_absent"] / out["days_enrolled"]
    )
    out["tier"] = tier_series(out["days_absent"], out["days_enrolled"]).fillna(
        tier_from_absence_pct(out["absence_pct"])
    )

    n_rows = len(out)
    out["current_streak"] = pd.array([pd.NA] * n_rows, dtype="Int64")
    out["max_streak"] = pd.array([pd.NA] * n_rows, dtype="Int64")
    out["trend_slope_pp_per_week"] = np.nan
    out["trend"] = pd.array(
        [
            Trend.INSUFFICIENT.value if matched else pd.NA
            for matched in out["matched"].tolist()
        ],
        dtype="string",
    )
    out["mon_fri_flag"] = pd.array([pd.NA] * n_rows, dtype="boolean")
    out["worst_period"] = pd.array([pd.NA] * n_rows, dtype="string")
    return _finalize_metrics(out)
