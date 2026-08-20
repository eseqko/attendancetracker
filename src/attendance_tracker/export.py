"""CSV export helpers: watchlist downloads and per-student summaries.

Pure pandas — the UI hands these bytes straight to a download button.
"""

from __future__ import annotations

import csv
import io

import numpy as np
import pandas as pd

from .constants import Category

#: Watchlist columns, in reading order (worst students sort to the top).
WATCHLIST_COLUMNS = [
    "name",
    "student_id",
    "grade",
    "group",
    "tier",
    "absence_pct",
    "attendance_rate",
    "days_absent",
    "days_enrolled",
    "days_tardy",
    "current_streak",
    "max_streak",
    "trend",
    "mon_fri_flag",
    "worst_period",
]

#: metrics column -> readable label for the per-student key/value block.
_SUMMARY_LABELS: list[tuple[str, str]] = [
    ("name", "Student name"),
    ("student_id", "Student ID"),
    ("grade", "Grade"),
    ("group", "Group"),
    ("tier", "Tier"),
    ("days_enrolled", "Days enrolled"),
    ("days_absent", "Days absent"),
    ("days_excused", "Absent days (excused)"),
    ("days_unexcused", "Absent days (unexcused)"),
    ("days_tardy", "Days tardy"),
    ("attendance_rate", "Attendance rate"),
    ("absence_pct", "Absence %"),
    ("current_streak", "Current absence streak"),
    ("max_streak", "Longest absence streak"),
    ("trend", "Trend"),
    ("trend_slope_pp_per_week", "Trend slope (pp/week)"),
    ("mon_fri_flag", "Mon/Fri pattern flag"),
    ("worst_period", "Most-skipped period"),
]

#: Categories left out of the event history (attended-as-normal rows).
_HISTORY_EXCLUDED = frozenset(
    {Category.PRESENT.value, Category.OTHER_PRESENT.value}
)


def frame_to_csv_bytes(frame: pd.DataFrame) -> bytes:
    """UTF-8 CSV bytes, no index."""
    return frame.to_csv(index=False).encode("utf-8")


def watchlist_csv_bytes(metrics: pd.DataFrame) -> bytes:
    """Readable watchlist CSV, sorted worst-first (absence_pct descending)."""
    frame = metrics.copy()
    if "absence_pct" in frame.columns:
        frame["absence_pct"] = frame["absence_pct"].round(1)
    if "attendance_rate" in frame.columns:
        frame["attendance_rate"] = frame["attendance_rate"].round(3)
    columns = [column for column in WATCHLIST_COLUMNS if column in frame.columns]
    frame = frame[columns]
    if "absence_pct" in frame.columns:
        frame = frame.sort_values(
            "absence_pct", ascending=False, na_position="last", kind="mergesort"
        )
    return frame_to_csv_bytes(frame)


def _format_value(value: object) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, (bool, np.bool_)):
        return "yes" if value else "no"
    if isinstance(value, (float, np.floating)):
        return f"{float(value):g}"
    return str(value)


def student_summary_csv_bytes(
    metrics_row: pd.Series, events: pd.DataFrame | None = None
) -> bytes:
    """One student's metrics as a key/value CSV block, plus event history.

    When ``events`` is given, a blank line and the student's non-present
    events (date, period, code, category — absences, tardies, unknown codes)
    follow, sorted newest first. Returns one UTF-8 CSV text as bytes.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["Field", "Value"])
    for key, label in _SUMMARY_LABELS:
        if key in metrics_row.index:
            writer.writerow([label, _format_value(metrics_row[key])])

    if events is not None and len(events):
        student_id = str(metrics_row.get("student_id", ""))
        rows = events.loc[
            (events["student_id"].astype("string") == student_id).fillna(False)
        ]
        category = rows["category"].astype("string")
        keep = ~category.isin(_HISTORY_EXCLUDED).fillna(False)
        rows = rows.loc[keep.to_numpy(dtype=bool)]
        rows = rows.sort_values("date", ascending=False, kind="mergesort")
        if "period" in rows.columns:
            periods = rows["period"].astype("string")
        else:
            periods = pd.array([pd.NA] * len(rows), dtype="string")
        history = pd.DataFrame(
            {
                "date": rows["date"].dt.strftime("%Y-%m-%d"),
                "period": periods,
                "code": rows["code"].astype("string"),
                "category": rows["category"].astype("string"),
            }
        )
        buffer.write("\n")
        history.to_csv(buffer, index=False, lineterminator="\n")

    return buffer.getvalue().encode("utf-8")
