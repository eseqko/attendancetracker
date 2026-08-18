"""Reusable Streamlit pieces shared by the views."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from attendance_tracker.constants import ANALYSIS_REQUIRES, Tier, Trend
from attendance_tracker.model import DataBundle

TIER_DISPLAY = {
    Tier.SATISFACTORY.value: "🟢 Satisfactory",
    Tier.AT_RISK.value: "🟡 At risk",
    Tier.CHRONIC.value: "🟠 Chronic",
    Tier.SEVERE.value: "🔴 Severe",
}

TREND_DISPLAY = {
    Trend.IMPROVING.value: "↗ Improving",
    Trend.STABLE.value: "→ Stable",
    Trend.DECLINING.value: "↘ Declining",
    Trend.INSUFFICIENT.value: "–",
}

CAPABILITY_NOTICES = {
    "trends": "Trend charts need day-level data; the uploaded report only has "
    "per-student totals.",
    "calendar": "The calendar view needs day-level data; the uploaded report "
    "only has per-student totals.",
    "streaks": "Streak detection needs day-level data; the uploaded report "
    "only has per-student totals.",
    "day_of_week": "Day-of-week patterns need day-level data; the uploaded "
    "report only has per-student totals.",
    "tardy_clusters": "Tardy patterns need day-level data; the uploaded report "
    "only has per-student totals.",
    "period_skipping": "Period-skipping analysis needs a period-by-period "
    "report; the uploaded report is day-level or summary only.",
}


def require(bundle: DataBundle, analysis: str) -> bool:
    """True when the bundle supports the analysis; otherwise renders the
    standard "this needs more data" notice and returns False."""
    needed = ANALYSIS_REQUIRES[analysis]
    if needed.issubset(bundle.capabilities):
        return True
    st.info(
        CAPABILITY_NOTICES.get(
            analysis, "This analysis needs data the uploaded report doesn't include."
        ),
        icon="ℹ️",
    )
    return False


def warnings_panel(warnings: list[str]) -> None:
    for message in warnings:
        st.warning(message, icon="⚠️")


def download_csv(label: str, data: bytes, filename: str, key: str) -> None:
    st.download_button(
        label, data=data, file_name=filename, mime="text/csv", key=key
    )


def display_metrics_table(metrics: pd.DataFrame) -> pd.DataFrame:
    """Human-readable copy of the metrics frame for st.dataframe display."""
    table = metrics.copy()
    table["tier"] = table["tier"].map(TIER_DISPLAY).fillna("–")
    if "trend" in table:
        table["trend"] = table["trend"].map(TREND_DISPLAY).fillna("–")
    if "mon_fri_flag" in table:
        table["mon_fri_flag"] = table["mon_fri_flag"].map(
            {True: "⚑ Mon/Fri", False: ""}
        )
    if "group" in table:
        table["group"] = table["group"].fillna("")
    return table


WATCHLIST_COLUMNS: dict[str, st.column_config.Column] = {}


def watchlist_column_config() -> dict:
    return {
        "name": st.column_config.TextColumn("Student", pinned=True),
        "student_id": st.column_config.TextColumn("ID"),
        "grade": st.column_config.TextColumn("Grade", width="small"),
        "group": st.column_config.TextColumn("Group"),
        "tier": st.column_config.TextColumn("Tier"),
        "absence_pct": st.column_config.NumberColumn(
            "Absent %", format="%.1f%%"
        ),
        "attendance_rate": st.column_config.NumberColumn(
            "Attendance", format="percent"
        ),
        "days_absent": st.column_config.NumberColumn("Days absent", format="%.0f"),
        "days_enrolled": st.column_config.NumberColumn("Days enrolled", format="%.0f"),
        "days_tardy": st.column_config.NumberColumn("Tardies", format="%.0f"),
        "current_streak": st.column_config.NumberColumn("Current streak"),
        "max_streak": st.column_config.NumberColumn("Longest streak"),
        "trend": st.column_config.TextColumn("Trend"),
        "mon_fri_flag": st.column_config.TextColumn("Pattern"),
        "worst_period": st.column_config.TextColumn("Skipped period"),
        "matched": None,
    }


def student_table_with_link(table: pd.DataFrame, key: str) -> None:
    """Render a metrics table with single-row selection; a button opens the
    selected student on the Student page (registered by app.py)."""
    from ui import state  # local import to avoid cycles

    event = st.dataframe(
        table,
        column_config=watchlist_column_config(),
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=key,
    )
    rows = event.selection.rows if event is not None else []
    if rows:
        selected_id = str(table.iloc[rows[0]]["student_id"])
        selected_name = table.iloc[rows[0]]["name"]
        if st.button(
            f"Open student view: {selected_name}", key=key + "_open", type="primary"
        ):
            state.select_student(selected_id)
            student_page = st.session_state.get("_pages", {}).get("student")
            if student_page is not None:
                st.switch_page(student_page)
