"""Breakdowns: every dimension the uploads support, on one page.

Day of week, month, period, attendance codes, grade, race/ethnicity, gender,
custom groups and extra caseload columns — and course/teacher/counselor when
the optional course-context report is attached.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from attendance_tracker import breakdowns as bd
from attendance_tracker import export
from attendance_tracker.constants import Capability
from ui import charts, components, state

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

COURSE_SECTION_TITLES = {
    "course": "By course / subject",
    "teacher": "By teacher",
    "counselor": "By counselor",
}


def _download(label: str, frame: pd.DataFrame, filename: str, key: str) -> None:
    components.download_csv(
        label, export.frame_to_csv_bytes(frame), filename, key=key
    )


def _pct(series: pd.Series) -> pd.Series:
    return series.map(lambda v: f"{v:.1%}" if pd.notna(v) else "–")


def _attribute_display(frame: pd.DataFrame) -> pd.DataFrame:
    display = frame.copy()
    if "mean_attendance_rate" in display:
        display["mean_attendance_rate"] = _pct(display["mean_attendance_rate"])
    if "mean_absence_pct" in display:
        display["mean_absence_pct"] = display["mean_absence_pct"].map(
            lambda v: f"{v:.1f}%" if pd.notna(v) else "–"
        )
    if "pct_chronic_or_worse" in display:
        display["pct_chronic_or_worse"] = display["pct_chronic_or_worse"].map(
            lambda v: f"{v:.1f}%" if pd.notna(v) else "–"
        )
    return display


def render() -> None:
    bundle = state.bundle()
    st.title("🧮 Breakdowns")
    st.caption(
        "Caseload absences sliced every way the uploaded files allow. "
        "Every table has a CSV download."
    )
    metrics_frame = bundle.metrics
    events = bundle.events
    day_status = bundle.day_status
    attributes = bd.student_attributes(bundle.students, events)

    st.subheader("By day of week")
    if components.require(bundle, "day_of_week"):
        weekday = bd.by_weekday(day_status)
        st.plotly_chart(
            charts.weekday_bars(weekday, bundle.baseline.weekday_absence_rate),
            use_container_width=True,
        )
        display = weekday.copy()
        display["weekday"] = display["weekday"].map(
            lambda d: WEEKDAY_NAMES[int(d)]
        )
        display["absence_rate"] = _pct(display["absence_rate"])
        display["tardy_rate"] = _pct(display["tardy_rate"])
        st.dataframe(display, hide_index=True)
        _download("Download (CSV)", weekday, "by_weekday.csv", "dl_weekday")

    st.subheader("By month")
    if components.require(bundle, "trends"):
        month = bd.by_month(day_status)
        chart_frame = month.copy()
        chart_frame["month"] = chart_frame["month"].dt.strftime("%b %Y")
        st.plotly_chart(
            charts.rate_comparison_bars(
                chart_frame, "month", "absence_rate",
                axis_title="Absence rate", full_scale=False,
            ),
            use_container_width=True,
        )
        display = chart_frame.copy()
        display["absence_rate"] = _pct(display["absence_rate"])
        display["tardy_rate"] = _pct(display["tardy_rate"])
        st.dataframe(display, hide_index=True)
        _download("Download (CSV)", month, "by_month.csv", "dl_month")

    st.subheader("By period")
    if components.require(bundle, "period_skipping") and events is not None:
        period = bd.by_period(events)
        if not period.empty:
            st.plotly_chart(
                charts.category_stack_bars(
                    period.assign(period="P" + period["period"].astype(str)),
                    "period",
                ),
                use_container_width=True,
            )
            st.dataframe(period, hide_index=True)
            _download("Download (CSV)", period, "by_period.csv", "dl_period")

    if events is not None:
        st.subheader("By attendance code")
        codes = bd.by_code(events)
        st.dataframe(codes, hide_index=True)
        _download("Download (CSV)", codes, "by_code.csv", "dl_code")

    for dimension in bd.dimension_columns(attributes):
        title = "By custom group" if dimension == "group" else f"By {dimension}"
        st.subheader(title)
        table = bd.by_attribute(metrics_frame, attributes, dimension)
        if table.empty:
            st.caption("No data for this dimension.")
            continue
        st.plotly_chart(
            charts.tier_mix_stacked(table, dimension), use_container_width=True
        )
        st.dataframe(_attribute_display(table), hide_index=True)
        _download(
            "Download (CSV)", table, f"by_{dimension}.csv", f"dl_{dimension}"
        )

    marks = bundle.course_marks
    if marks is not None and not marks.empty:
        for by in bd.COURSE_DIMENSIONS:
            if marks[by].isna().all():
                continue
            st.subheader(COURSE_SECTION_TITLES[by])
            table = bd.course_breakdown(marks, by)
            st.plotly_chart(
                charts.top_hbar(table, by, "absences", "Absences (counted)"),
                use_container_width=True,
            )
            st.dataframe(table, hide_index=True)
            _download("Download (CSV)", table, f"by_{by}.csv", f"dl_{by}")
    else:
        st.subheader("By course, teacher & counselor")
        st.info(
            "Upload the optional course/teacher context report (the per-class "
            "code-count export) in Upload & Setup to unlock these breakdowns.",
            icon="📚",
        )
