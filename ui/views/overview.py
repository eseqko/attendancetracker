"""Overview: KPIs, tier distribution, and the sortable watch-list."""

from __future__ import annotations

import streamlit as st

from attendance_tracker import export
from attendance_tracker.constants import TIER_LABELS, TIER_ORDER, Tier, Trend
from ui import charts, components, state

WATCHLIST_COLUMNS = [
    "name", "student_id", "grade", "group", "tier", "absence_pct",
    "attendance_rate", "days_absent", "days_enrolled", "days_tardy",
    "current_streak", "max_streak", "trend", "mon_fri_flag", "worst_period",
]


def render() -> None:
    bundle = state.bundle()
    st.title("📊 Overview")
    metrics = bundle.metrics
    matched = metrics[metrics["matched"]]
    baseline = bundle.baseline

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    kpi1.metric("Caseload students", f"{len(matched)} of {len(metrics)}")
    mean_rate = matched["attendance_rate"].mean()
    delta = None
    if baseline.mean_attendance_rate is not None and mean_rate == mean_rate:
        delta = f"{(mean_rate - baseline.mean_attendance_rate) * 100:+.1f} pp vs school"
    kpi2.metric(
        "Mean attendance rate",
        f"{mean_rate:.1%}" if mean_rate == mean_rate else "–",
        delta=delta,
        delta_color="normal",
    )
    chronic_or_worse = int(
        matched["tier"].isin([Tier.CHRONIC.value, Tier.SEVERE.value]).sum()
    )
    kpi3.metric("Chronic or severe", chronic_or_worse)
    if "trend" in matched:
        declining = int((matched["trend"] == Trend.DECLINING.value).sum())
        kpi4.metric("Declining", declining)

    st.plotly_chart(charts.tier_bar(metrics), use_container_width=True)

    st.subheader("Watch-list")
    f1, f2, f3, f4 = st.columns([2, 1, 2, 1])
    with f1:
        tier_filter = st.multiselect(
            "Tier",
            [t.value for t in TIER_ORDER],
            format_func=lambda t: TIER_LABELS[Tier(t)],
            key="ov_tier_filter",
        )
    with f2:
        grades = sorted(matched["grade"].dropna().unique().tolist())
        grade_filter = st.multiselect("Grade", grades, key="ov_grade_filter")
    with f3:
        groups = sorted(matched["group"].dropna().unique().tolist())
        group_filter = st.multiselect("Group", groups, key="ov_group_filter") if groups else []
    with f4:
        declining_only = st.checkbox("Declining only", key="ov_declining")

    view = matched
    if tier_filter:
        view = view[view["tier"].isin(tier_filter)]
    if grade_filter:
        view = view[view["grade"].isin(grade_filter)]
    if group_filter:
        view = view[view["group"].isin(group_filter)]
    if declining_only and "trend" in view:
        view = view[view["trend"] == Trend.DECLINING.value]

    view = view.sort_values("absence_pct", ascending=False)
    display_columns = [c for c in WATCHLIST_COLUMNS if c in view.columns]
    components.student_table_with_link(
        components.display_metrics_table(view[display_columns]), key="watchlist"
    )
    components.download_csv(
        "Download watch-list (CSV)",
        export.watchlist_csv_bytes(view),
        "watchlist.csv",
        key="dl_watchlist",
    )

    if not bundle.unmatched.empty:
        with st.expander(
            f"⚠️ {len(bundle.unmatched)} caseload student(s) not found in the report"
        ):
            st.dataframe(
                bundle.unmatched.rename(
                    columns={"student_id": "Student ID", "name": "Name", "hint": "Hint"}
                ),
                hide_index=True,
            )
    components.warnings_panel(state.bundle_warnings())
