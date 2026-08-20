"""Cohorts: caseload vs schoolwide, by grade, and custom groups."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from attendance_tracker import cohorts as cohorts_core
from attendance_tracker import export
from ui import charts, components, state

#: Canonical columns that are not useful group-by candidates.
NON_GROUP_COLUMNS = {
    "student_id", "match_key", "name", "grade", "group", "matched",
}


def _extra_group_columns(students: pd.DataFrame) -> list[str]:
    return [
        c
        for c in students.columns
        if c not in NON_GROUP_COLUMNS and students[c].notna().any()
    ]


def render() -> None:
    bundle = state.bundle()
    st.title("👥 Cohorts")
    metrics = bundle.metrics

    st.subheader("Caseload vs. schoolwide")
    comparison = cohorts_core.caseload_vs_baseline(metrics, bundle.baseline)
    chart_col, table_col = st.columns([3, 2])
    with chart_col:
        st.plotly_chart(
            charts.rate_comparison_bars(comparison, comparison.columns[0]),
            use_container_width=True,
        )
    with table_col:
        display = comparison.copy()
        display["mean_attendance_rate"] = display["mean_attendance_rate"].map(
            lambda v: f"{v:.1%}" if pd.notna(v) else "–"
        )
        display["pct_chronic_or_worse"] = display["pct_chronic_or_worse"].map(
            lambda v: f"{v:.1f}%" if pd.notna(v) else "–"
        )
        display.columns = ["Cohort", "Students", "Mean attendance", "Chronic or worse"]
        st.dataframe(display, hide_index=True)

    st.subheader("By grade")
    grade_summary = cohorts_core.group_summary(metrics, "grade")
    baseline_by_grade = bundle.baseline.by_grade
    if baseline_by_grade is not None and not baseline_by_grade.empty:
        merged = grade_summary.merge(
            baseline_by_grade[["grade", "mean_attendance_rate"]].rename(
                columns={"mean_attendance_rate": "schoolwide_rate"}
            ),
            on="grade",
            how="left",
        ).sort_values("grade")
        st.plotly_chart(
            charts.grouped_rate_bars(
                merged, "grade", "mean_attendance_rate", "schoolwide_rate"
            ),
            use_container_width=True,
        )
    else:
        st.plotly_chart(
            charts.rate_comparison_bars(
                grade_summary.sort_values("grade"), "grade"
            ),
            use_container_width=True,
        )

    st.subheader("Custom groups")
    st.caption(
        "Assign your own groups (e.g. check-in tier, program, intervention) "
        "and compare them below. Groups live only in this session."
    )
    students = bundle.students
    matched_students = students[students["matched"]] if "matched" in students else students
    editor = st.data_editor(
        matched_students[["student_id", "name", "grade", "group"]].rename(
            columns={
                "student_id": "Student ID",
                "name": "Name",
                "grade": "Grade",
                "group": "Group",
            }
        ),
        column_config={
            "Student ID": st.column_config.TextColumn(disabled=True),
            "Name": st.column_config.TextColumn(disabled=True),
            "Grade": st.column_config.TextColumn(disabled=True),
            "Group": st.column_config.TextColumn(
                help="Type any label; students with the same label are compared "
                "as a group."
            ),
        },
        hide_index=True,
        key="group_editor",
        height=280,
    )
    if st.button("Apply groups", key="apply_groups"):
        assignments = dict(
            zip(editor["Student ID"].astype(str), editor["Group"])
        )
        new_groups_students = students["student_id"].map(assignments)
        students["group"] = new_groups_students.astype("string")
        metrics["group"] = metrics["student_id"].map(assignments).astype("string")
        st.rerun()

    st.subheader("Compare groups")
    by_options = ["group"] + _extra_group_columns(students)
    by = st.selectbox(
        "Group by",
        by_options,
        format_func=lambda c: "Custom group" if c == "group" else c,
        key="cohort_by",
    )
    if by != "group" and by not in metrics.columns:
        metrics = metrics.merge(
            students[["student_id", by]], on="student_id", how="left"
        )
    group_frame = cohorts_core.group_summary(metrics, by)
    if group_frame.empty or (by == "group" and students["group"].isna().all()):
        st.info("Assign at least one group above to see a comparison.", icon="🏷️")
        return
    st.plotly_chart(
        charts.tier_mix_stacked(group_frame, by), use_container_width=True
    )
    display = group_frame.copy()
    display["mean_attendance_rate"] = display["mean_attendance_rate"].map(
        lambda v: f"{v:.1%}" if pd.notna(v) else "–"
    )
    st.dataframe(display, hide_index=True)
    components.download_csv(
        "Download group summary (CSV)",
        export.frame_to_csv_bytes(group_frame),
        "group_summary.csv",
        key="dl_groups",
    )
