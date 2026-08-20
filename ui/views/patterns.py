"""Patterns: day-of-week effects, streaks, tardy clusters, period skipping."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from attendance_tracker.constants import Capability, Category
from ui import charts, components, state

STREAK_COLUMNS = ["name", "student_id", "grade", "tier", "current_streak", "max_streak"]


def _caseload_weekday_rates(day_status: pd.DataFrame) -> pd.DataFrame:
    frame = day_status.copy()
    frame["weekday"] = frame["date"].dt.weekday
    frame = frame[frame["weekday"] < 5]
    grouped = (
        frame.groupby("weekday", observed=True)["is_absent_day"]
        .mean()
        .rename("absence_rate")
        .reset_index()
    )
    return grouped


def render() -> None:
    bundle = state.bundle()
    st.title("📅 Patterns")
    if not components.require(bundle, "day_of_week"):
        return

    metrics = bundle.metrics
    matched = metrics[metrics["matched"]]
    day_status = bundle.day_status

    st.subheader("Absences by day of week")
    st.plotly_chart(
        charts.weekday_bars(
            _caseload_weekday_rates(day_status),
            bundle.baseline.weekday_absence_rate,
        ),
        use_container_width=True,
    )
    flagged = matched[matched["mon_fri_flag"] == True]  # noqa: E712 — nullable bool
    if flagged.empty:
        st.caption("No students show a Monday/Friday absence pattern.")
    else:
        st.markdown(f"**{len(flagged)} student(s) with a Monday/Friday pattern:**")
        components.student_table_with_link(
            components.display_metrics_table(
                flagged[["name", "student_id", "grade", "tier", "absence_pct", "mon_fri_flag"]]
            ),
            key="monfri_table",
        )

    st.subheader("Consecutive-absence streaks")
    min_streak = st.slider(
        "Show streaks of at least…", min_value=2, max_value=15, value=3,
        key="min_streak",
    )
    streaky = matched[matched["max_streak"] >= min_streak].sort_values(
        ["current_streak", "max_streak"], ascending=False
    )
    if streaky.empty:
        st.caption(f"No streaks of {min_streak}+ school days.")
    else:
        components.student_table_with_link(
            components.display_metrics_table(streaky[STREAK_COLUMNS]),
            key="streak_table",
        )

    st.subheader("Tardies")
    if components.require(bundle, "tardy_clusters"):
        st.plotly_chart(
            charts.tardy_weekday_bar(day_status), use_container_width=True
        )
        events = bundle.events
        if bundle.has(Capability.PERIOD) and events is not None:
            tardies = events[events["category"] == Category.TARDY.value]
            if not tardies.empty:
                first_period_share = (
                    pd.to_numeric(tardies["period"], errors="coerce") == 1
                ).mean()
                st.caption(
                    f"{first_period_share:.0%} of tardies are in period 1 — "
                    "morning arrival."
                )

    if bundle.has(Capability.PERIOD):
        st.subheader("Possible period skipping")
        skippers = matched[matched["worst_period"].notna()]
        if skippers.empty:
            st.caption("No student shows a concentrated single-period absence pattern.")
        else:
            components.student_table_with_link(
                components.display_metrics_table(
                    skippers[
                        ["name", "student_id", "grade", "tier", "worst_period", "absence_pct"]
                    ]
                ),
                key="skip_table",
            )
            st.caption(
                "A period is flagged when its unexcused-absence rate is at "
                "least twice the student's other periods (minimum 3 misses). "
                "Open the student view for the per-period breakdown."
            )
