"""Cohort aggregation: schoolwide baselines and caseload group comparisons.

Baselines are computed over the FULL schoolwide report before non-caseload
rows are dropped, and keep only aggregates (never per-student data) — see
:class:`~.model.BaselineMetrics`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .constants import DEFAULT_ABSENT_DAY_THRESHOLD, TIER_ORDER, Tier
from .metrics import (
    build_day_status,
    per_student_counts,
    tier_from_absence_pct,
    tier_series,
)
from .model import BaselineMetrics

_CHRONIC_OR_WORSE = (Tier.CHRONIC.value, Tier.SEVERE.value)


def _tier_counts(tiers: pd.Series) -> dict[str, int]:
    return {
        tier.value: int((tiers == tier.value).fillna(False).sum())
        for tier in TIER_ORDER
    }


def _pct_chronic_or_worse(tiers: pd.Series) -> float:
    if not len(tiers):
        return float("nan")
    mask = tiers.isin(_CHRONIC_OR_WORSE).fillna(False).astype(bool)
    return float(100.0 * mask.mean())


def _mean_or_none(rates: pd.Series) -> float | None:
    if not len(rates) or not rates.notna().any():
        return None
    return float(rates.mean())


def _grade_table(per_student: pd.DataFrame) -> pd.DataFrame:
    """grade / n_students / mean_attendance_rate / pct_chronic_or_worse."""
    grouped = per_student.groupby("grade", observed=True)
    table = pd.DataFrame(
        {
            "n_students": grouped.size(),
            "mean_attendance_rate": grouped["attendance_rate"].mean(),
            "pct_chronic_or_worse": grouped["tier"].apply(_pct_chronic_or_worse),
        }
    )
    table.index = table.index.astype("string")
    table.index.name = "grade"
    return table.reset_index()


def baseline_from_events(
    all_events: pd.DataFrame,
    absent_day_threshold: float = DEFAULT_ABSENT_DAY_THRESHOLD,
    enrolled_override: int | pd.Series | None = None,
) -> BaselineMetrics:
    """Schoolwide aggregates from the full events frame (all students)."""
    day_status = build_day_status(all_events, absent_day_threshold)
    counts = per_student_counts(day_status, enrolled_override)
    counts["attendance_rate"] = 1 - counts["days_absent"] / counts["days_enrolled"]
    counts["tier"] = tier_series(counts["days_absent"], counts["days_enrolled"])
    n_students = int(len(counts))

    by_grade = None
    if "grade" in all_events.columns and n_students:
        grades = (
            pd.DataFrame(
                {
                    "student_id": all_events["student_id"].astype("string"),
                    "grade": all_events["grade"].astype("string"),
                }
            )
            .groupby("student_id", observed=True)["grade"]
            .first()
        )
        per_student = counts.merge(
            grades.reset_index(), on="student_id", how="left"
        )
        per_student["grade"] = per_student["grade"].astype("string").fillna("(unknown)")
        by_grade = _grade_table(per_student)

    weekday_frame = None
    if len(day_status):
        work = pd.DataFrame(
            {
                "weekday": day_status["date"].dt.weekday.astype("int64"),
                "is_absent_day": day_status["is_absent_day"].astype(bool),
            }
        )
        weekday_frame = (
            work.groupby("weekday", observed=True)["is_absent_day"]
            .mean()
            .rename("absence_rate")
            .reset_index()
        )

    return BaselineMetrics(
        n_students=n_students,
        mean_attendance_rate=_mean_or_none(counts["attendance_rate"]),
        tier_counts=_tier_counts(counts["tier"]),
        by_grade=by_grade,
        weekday_absence_rate=weekday_frame,
    )


def baseline_from_summary(all_summary: pd.DataFrame) -> BaselineMetrics:
    """Schoolwide aggregates from a summary report (no weekday frame)."""
    n_students = int(len(all_summary))

    def numeric(column: str) -> pd.Series:
        if column in all_summary.columns:
            return pd.to_numeric(all_summary[column], errors="coerce")
        return pd.Series(np.nan, index=all_summary.index, dtype="float64")

    days_absent = numeric("days_absent")
    days_enrolled = numeric("days_enrolled")
    rate = numeric("attendance_rate").fillna(1 - days_absent / days_enrolled)
    tiers = tier_series(days_absent, days_enrolled).fillna(
        tier_from_absence_pct(100 * (1 - rate))
    )

    by_grade = None
    if "grade" in all_summary.columns and n_students:
        per_student = pd.DataFrame(
            {
                "grade": all_summary["grade"].astype("string").fillna("(unknown)"),
                "attendance_rate": rate,
                "tier": tiers,
            }
        )
        by_grade = _grade_table(per_student)

    return BaselineMetrics(
        n_students=n_students,
        mean_attendance_rate=_mean_or_none(rate),
        tier_counts=_tier_counts(tiers),
        by_grade=by_grade,
        weekday_absence_rate=None,
    )


def group_summary(metrics: pd.DataFrame, by: str) -> pd.DataFrame:
    """Aggregate matched caseload students per value of the ``by`` column.

    NA group values land in '(unassigned)'. One count column per tier value,
    plus pct_chronic_or_worse; sorted worst-first (mean_attendance_rate
    ascending).
    """
    matched_mask = metrics["matched"].fillna(False).astype(bool)
    work = metrics.loc[matched_mask].copy()
    work["_group"] = work[by].astype("string").fillna("(unassigned)")

    grouped = work.groupby("_group", observed=True)
    table = pd.DataFrame(
        {
            "n_students": grouped.size(),
            "mean_attendance_rate": grouped["attendance_rate"].mean(),
            "mean_absence_pct": grouped["absence_pct"].mean(),
        }
    )
    for tier in TIER_ORDER:
        table[tier.value] = grouped["tier"].apply(
            lambda tiers, value=tier.value: int(
                (tiers == value).fillna(False).sum()
            )
        )
    table["pct_chronic_or_worse"] = grouped["tier"].apply(_pct_chronic_or_worse)

    table = table.sort_values("mean_attendance_rate", ascending=True, kind="mergesort")
    table.index = table.index.astype("string")
    table.index.name = by
    return table.reset_index()


def caseload_vs_baseline(
    metrics: pd.DataFrame, baseline: BaselineMetrics
) -> pd.DataFrame:
    """Tidy caseload-vs-schoolwide comparison (one row per cohort)."""
    matched = metrics.loc[metrics["matched"].fillna(False).astype(bool)]
    n_caseload = int(len(matched))
    caseload_rate = (
        _mean_or_none(matched["attendance_rate"]) if n_caseload else None
    )
    caseload_pct = _pct_chronic_or_worse(matched["tier"]) if n_caseload else float("nan")

    classified = sum(baseline.tier_counts.values())
    if classified:
        chronic_or_worse = sum(
            baseline.tier_counts.get(value, 0) for value in _CHRONIC_OR_WORSE
        )
        school_pct = 100.0 * chronic_or_worse / classified
    else:
        school_pct = float("nan")
    school_rate = baseline.mean_attendance_rate

    return pd.DataFrame(
        {
            "cohort": pd.array(["caseload", "schoolwide"], dtype="string"),
            "n_students": pd.Series([n_caseload, baseline.n_students], dtype="int64"),
            "mean_attendance_rate": pd.Series(
                [
                    caseload_rate if caseload_rate is not None else np.nan,
                    school_rate if school_rate is not None else np.nan,
                ],
                dtype="float64",
            ),
            "pct_chronic_or_worse": pd.Series(
                [caseload_pct, school_pct], dtype="float64"
            ),
        }
    )
