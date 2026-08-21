"""Multi-dimensional attendance breakdowns.

Everything the Breakdowns page renders: absences by day of week, month,
period, attendance code, any student attribute (grade, ethnicity, gender,
custom group, extra caseload columns), and — when a course-context report is
attached — by course, teacher, and counselor. Pure pandas; every function
returns a tidy frame ready for charting and CSV export.
"""

from __future__ import annotations

import pandas as pd

from . import cohorts
from .constants import ABSENT_CATEGORIES, ATTRIBUTE_ROLES, Category

_ABSENT_VALUES = {category.value for category in ABSENT_CATEGORIES}

#: Canonical student columns that are never breakdown dimensions.
_NON_DIMENSION_COLUMNS = {"student_id", "match_key", "name", "matched"}


# ---------------------------------------------------------------------------
# Student attributes
# ---------------------------------------------------------------------------


def student_attributes(
    students: pd.DataFrame, events: pd.DataFrame | None = None
) -> pd.DataFrame:
    """One row per student with every attribute usable as a dimension.

    Caseload columns win; report-side attributes (ethnicity/gender/grade on
    the events frame) fill the gaps with each student's first value.
    """
    out = students.copy()
    if events is not None:
        for role in ("grade", *ATTRIBUTE_ROLES):
            if role not in events.columns:
                continue
            from_report = (
                events[["student_id", role]]
                .dropna()
                .groupby("student_id", observed=True)[role]
                .first()
            )
            if role in out.columns:
                filled = out["student_id"].map(from_report)
                out[role] = out[role].fillna(filled).astype("string")
            else:
                out[role] = out["student_id"].map(from_report).astype("string")
    return out


def dimension_columns(attributes: pd.DataFrame) -> list[str]:
    """Attribute columns worth offering as dimensions (any non-NA value),
    canonical ones first. Columns that are unique (or nearly unique) per
    student — IDs, names — are excluded: one group per student is not a
    breakdown."""
    canonical = ["grade", *ATTRIBUTE_ROLES, "group"]
    extras = [
        column
        for column in attributes.columns
        if column not in canonical and column not in _NON_DIMENSION_COLUMNS
    ]
    n_students = max(len(attributes), 1)
    out: list[str] = []
    for column in canonical + extras:
        if column not in attributes.columns:
            continue
        values = attributes[column].dropna()
        if values.empty:
            continue
        if column not in canonical and values.nunique() > 0.5 * n_students:
            continue  # ID-like: distinct for most students
        out.append(column)
    return out


# ---------------------------------------------------------------------------
# Time dimensions (need day-level data)
# ---------------------------------------------------------------------------


def by_weekday(day_status: pd.DataFrame) -> pd.DataFrame:
    """Per weekday (0=Mon..4=Fri): enrolled/absent days, absence & tardy rates."""
    frame = day_status.copy()
    frame["weekday"] = frame["date"].dt.weekday
    frame = frame[frame["weekday"] < 5]
    out = (
        frame.groupby("weekday", observed=True)
        .agg(
            enrolled_days=("date", "size"),
            absent_days=("is_absent_day", "sum"),
            tardy_days=("is_tardy_day", "sum"),
        )
        .reset_index()
    )
    out["absence_rate"] = out["absent_days"] / out["enrolled_days"]
    out["tardy_rate"] = out["tardy_days"] / out["enrolled_days"]
    return out


def by_month(day_status: pd.DataFrame) -> pd.DataFrame:
    """Per calendar month: enrolled/absent days, absence & tardy rates."""
    frame = day_status.copy()
    frame["month"] = frame["date"].dt.to_period("M").dt.start_time
    out = (
        frame.groupby("month", observed=True)
        .agg(
            enrolled_days=("date", "size"),
            absent_days=("is_absent_day", "sum"),
            tardy_days=("is_tardy_day", "sum"),
        )
        .reset_index()
        .sort_values("month")
    )
    out["absence_rate"] = out["absent_days"] / out["enrolled_days"]
    out["tardy_rate"] = out["tardy_days"] / out["enrolled_days"]
    return out


def by_period(events: pd.DataFrame) -> pd.DataFrame:
    """Per class period: unexcused/excused absences, tardies, students hit."""
    if "period" not in events.columns:
        return pd.DataFrame(
            columns=["period", "unexcused", "excused", "tardies", "students"]
        )
    rows = events.loc[events["period"].notna()].copy()
    category = rows["category"].astype("string")
    rows["unexcused"] = (
        (category == Category.ABSENT_UNEXCUSED.value).fillna(False).astype(int)
    )
    rows["excused"] = (
        (category == Category.ABSENT_EXCUSED.value).fillna(False).astype(int)
    )
    rows["tardies"] = (category == Category.TARDY.value).fillna(False).astype(int)
    out = (
        rows.groupby("period", observed=True)
        .agg(
            unexcused=("unexcused", "sum"),
            excused=("excused", "sum"),
            tardies=("tardies", "sum"),
            students=("student_id", "nunique"),
        )
        .reset_index()
    )
    out["_sort"] = pd.to_numeric(out["period"], errors="coerce")
    return out.sort_values(["_sort", "period"]).drop(columns="_sort")


def by_code(events: pd.DataFrame) -> pd.DataFrame:
    """Per raw attendance code: how often it occurs and what it counts as."""
    out = (
        events.groupby(["code", "category"], observed=True)
        .agg(occurrences=("student_id", "size"), students=("student_id", "nunique"))
        .reset_index()
        .sort_values("occurrences", ascending=False)
        .reset_index(drop=True)
    )
    return out


# ---------------------------------------------------------------------------
# Attribute dimensions
# ---------------------------------------------------------------------------


def by_attribute(
    metrics: pd.DataFrame, attributes: pd.DataFrame, attribute: str
) -> pd.DataFrame:
    """Group summary (rates, tier mix) per value of one student attribute,
    plus total absence/tardy day counts."""
    merged = metrics
    if attribute not in merged.columns:
        merged = merged.merge(
            attributes[["student_id", attribute]], on="student_id", how="left"
        )
    summary = cohorts.group_summary(merged, attribute)
    matched = merged[merged["matched"]].copy()
    matched[attribute] = (
        matched[attribute].astype("string").fillna("(unassigned)")
    )
    totals = (
        matched.groupby(attribute, observed=True)
        .agg(
            total_absent_days=("days_absent", "sum"),
            total_tardies=("days_tardy", "sum"),
        )
        .reset_index()
    )
    return summary.merge(totals, on=attribute, how="left")


# ---------------------------------------------------------------------------
# Course context (ATC-style supplemental report)
# ---------------------------------------------------------------------------

COURSE_DIMENSIONS = ("course", "teacher", "counselor")


def course_breakdown(course_marks: pd.DataFrame, by: str) -> pd.DataFrame:
    """Per course/teacher/counselor: absence & tardy counts across the
    caseload, worst first. Counts follow the district's rules — present-like
    codes (Activity, Office Ex) don't count as absences."""
    if by not in COURSE_DIMENSIONS:
        raise ValueError(f"unknown course dimension: {by!r}")
    rows = course_marks.copy()
    category = rows["category"].astype("string")
    count = rows["count"].astype("int64")
    rows["absences"] = count.where(category.isin(_ABSENT_VALUES), 0)
    rows["unexcused"] = count.where(
        (category == Category.ABSENT_UNEXCUSED.value).fillna(False), 0
    )
    rows["tardies"] = count.where(
        (category == Category.TARDY.value).fillna(False), 0
    )
    rows[by] = rows[by].astype("string").fillna("(unknown)")
    out = (
        rows.groupby(by, observed=True)
        .agg(
            absences=("absences", "sum"),
            unexcused=("unexcused", "sum"),
            tardies=("tardies", "sum"),
            students=("student_id", "nunique"),
        )
        .reset_index()
        .sort_values(["absences", "unexcused"], ascending=False)
        .reset_index(drop=True)
    )
    return out
