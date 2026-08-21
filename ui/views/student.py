"""Individual student: stat header, calendar heatmap, weekly trend, history."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from attendance_tracker import export
from attendance_tracker import metrics as metrics_mod
from attendance_tracker.constants import Capability, Category
from ui import charts, components, state


def _student_options(metrics: pd.DataFrame) -> tuple[list[str], dict[str, str]]:
    matched = metrics[metrics["matched"]].copy()
    matched["_label"] = matched.apply(
        lambda r: f"{r['name']} ({r['student_id']})"
        if pd.notna(r["name"])
        else str(r["student_id"]),
        axis=1,
    )
    matched = matched.sort_values("_label")
    return matched["student_id"].tolist(), dict(
        zip(matched["student_id"], matched["_label"])
    )


def render() -> None:
    bundle = state.bundle()
    st.title("Student")
    metrics = bundle.metrics
    options, labels = _student_options(metrics)
    if not options:
        st.info("No matched students to show.")
        return

    default = state.selected_student()
    index = options.index(default) if default in options else 0
    student_id = st.selectbox(
        "Student",
        options,
        index=index,
        format_func=lambda sid: labels.get(sid, sid),
        key="student_select",
    )
    state.select_student(student_id)
    row = metrics[metrics["student_id"] == student_id].iloc[0]

    grade = f" · Grade {row['grade']}" if pd.notna(row.get("grade")) else ""
    group = f" · {row['group']}" if pd.notna(row.get("group")) else ""
    tier = components.TIER_DISPLAY.get(row["tier"], "–")
    st.caption(f"ID {row['student_id']}{grade}{group} · Tier: **{tier}**")

    c1, c2, c3, c4 = st.columns(4)
    rate = row["attendance_rate"]
    c1.metric("Attendance rate", f"{rate:.1%}" if pd.notna(rate) else "–")
    absent = row["days_absent"]
    breakdown = ""
    if pd.notna(row.get("days_excused")) and pd.notna(row.get("days_unexcused")):
        breakdown = f"{row['days_excused']:.0f} exc / {row['days_unexcused']:.0f} unexc"
    c2.metric(
        "Days absent",
        f"{absent:.0f}" if pd.notna(absent) else "–",
        delta=breakdown or None,
        delta_color="off",
    )
    tardy = row["days_tardy"]
    c3.metric("Tardies", f"{tardy:.0f}" if pd.notna(tardy) else "–")
    if pd.notna(row.get("current_streak")):
        c4.metric(
            "Absence streak",
            int(row["current_streak"]),
            delta=f"longest: {int(row['max_streak'])}",
            delta_color="off",
        )
    trend_label = components.TREND_DISPLAY.get(row.get("trend"), "–")
    slope = row.get("trend_slope_pp_per_week")
    if pd.notna(slope):
        st.caption(f"Trend: **{trend_label}** ({slope:+.1f} pp/week over recent weeks)")

    events = bundle.events
    student_events = (
        events[events["student_id"] == student_id] if events is not None else None
    )
    day_status = bundle.day_status
    student_days = (
        day_status[day_status["student_id"] == student_id]
        if day_status is not None
        else None
    )

    if components.require(bundle, "calendar"):
        st.subheader("Year at a glance")
        calendar = metrics_mod.events_calendar(events)
        st.plotly_chart(
            charts.calendar_heatmap(student_days, calendar), use_container_width=True
        )

    if components.require(bundle, "trends"):
        st.subheader("Weekly attendance rate")
        weekly = metrics_mod.weekly_rates(student_days)
        if len(weekly) >= 2:
            st.plotly_chart(charts.weekly_rate_line(weekly), use_container_width=True)
        else:
            st.caption("Not enough weeks of data yet for a trend line.")

    if bundle.has(Capability.PERIOD):
        st.subheader("By class period")
        period_frame = metrics_mod.period_table(student_events)
        if not period_frame.empty:
            st.plotly_chart(
                charts.period_bars(period_frame), use_container_width=True
            )

    if student_events is not None:
        st.subheader("Absence & tardy history")
        history = student_events[
            student_events["category"] != Category.PRESENT.value
        ].sort_values("date", ascending=False)
        display = pd.DataFrame(
            {
                "Date": history["date"].dt.strftime("%a %b %d, %Y"),
                "Period": history["period"].fillna("–") if "period" in history else "–",
                "Code": history["code"],
                "Meaning": history["category"].str.replace("_", " ").str.title(),
            }
        )
        st.dataframe(display, hide_index=True, height=280)

    components.download_csv(
        "Download student summary (CSV)",
        export.student_summary_csv_bytes(row, student_events),
        f"student_{row['student_id']}.csv",
        key="dl_student",
    )
