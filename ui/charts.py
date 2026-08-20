"""Plotly figure builders — pure functions from canonical frames to Figures.

Color roles (validated reference palette): tiers and day-statuses are *states*
and use the status palette, always paired with visible text labels; magnitude
comparisons use a single blue; the schoolwide baseline is always a recessive
gray reference, never a competing hue.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from attendance_tracker.constants import TIER_LABELS, TIER_ORDER, Tier

# Ink & chrome (light surface, Apple-neutral)
INK = "#1d1d1f"
INK_SECONDARY = "#6e6e73"
MUTED = "#86868b"
GRID = "#e8e8ed"
AXIS = "#d2d2d7"

# Series roles
BLUE = "#0071e3"  # primary measure (accent)
BLUE_LIGHT = "#8ec0f2"  # secondary line (rolling average)
BASELINE_GRAY = "#aeaeb2"  # schoolwide reference

# Status palette — tiers are states (good/warning/serious/critical)
TIER_COLORS: dict[str, str] = {
    Tier.SATISFACTORY.value: "#0ca30c",
    Tier.AT_RISK.value: "#fab219",
    Tier.CHRONIC.value: "#ec835a",
    Tier.SEVERE.value: "#d03b3b",
}

# Calendar day statuses — states; present recedes toward the surface
DAY_STATUS_COLORS: dict[str, str] = {
    "present": "#eceef1",
    "tardy": "#fab219",
    "partial": "#f6c6ae",
    "absent_excused": "#ec835a",
    "absent_unexcused": "#d03b3b",
}
DAY_STATUS_LABELS: dict[str, str] = {
    "present": "Present",
    "tardy": "Tardy",
    "partial": "Partial absence",
    "absent_excused": "Absent (excused)",
    "absent_unexcused": "Absent (unexcused)",
}

WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri"]

FONT = (
    '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, '
    '"Helvetica Neue", Arial, sans-serif'
)


def _base_layout(fig: go.Figure, height: int = 320) -> go.Figure:
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, color=INK_SECONDARY, size=13),
        margin=dict(l=8, r=8, t=16, b=8),
        height=height,
        hoverlabel=dict(font_family=FONT),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    fig.update_xaxes(
        gridcolor=GRID, linecolor=AXIS, tickfont=dict(color=MUTED), zeroline=False
    )
    fig.update_yaxes(
        gridcolor=GRID, linecolor=AXIS, tickfont=dict(color=MUTED), zeroline=False
    )
    return fig


def tier_bar(metrics: pd.DataFrame) -> go.Figure:
    """Tier distribution for matched caseload students. One state per bar,
    status colors, direct count labels (color never carries meaning alone)."""
    matched = metrics[metrics["matched"]]
    counts = [int((matched["tier"] == t.value).sum()) for t in TIER_ORDER]
    labels = [TIER_LABELS[t] for t in TIER_ORDER]
    fig = go.Figure(
        go.Bar(
            x=labels,
            y=counts,
            marker_color=[TIER_COLORS[t.value] for t in TIER_ORDER],
            text=counts,
            textposition="outside",
            textfont=dict(color=INK),
            hovertemplate="%{x}: %{y} students<extra></extra>",
            width=0.55,
        )
    )
    fig.update_yaxes(title_text="Students", rangemode="tozero")
    return _base_layout(fig, height=280)


def calendar_heatmap(
    day_status: pd.DataFrame, calendar: pd.DatetimeIndex
) -> go.Figure:
    """One student's year at a glance: weeks x weekday grid of day statuses.

    Discrete state colors with a labeled legend (dummy scatter entries) and a
    full-detail tooltip; non-school days stay blank.
    """
    status_order = list(DAY_STATUS_COLORS)
    by_date = day_status.set_index("date")

    cal = pd.DataFrame({"date": calendar})
    cal["weekday"] = cal["date"].dt.weekday
    cal = cal[cal["weekday"] < 5]
    cal["week"] = cal["date"].dt.to_period("W").dt.start_time
    cal["status"] = [
        by_date.at[d, "dominant_status"] if d in by_date.index else None
        for d in cal["date"]
    ]
    weeks = sorted(cal["week"].unique())
    week_index = {w: i for i, w in enumerate(weeks)}

    z = [[None] * len(weeks) for _ in range(5)]
    text = [[""] * len(weeks) for _ in range(5)]
    for row in cal.itertuples(index=False):
        if row.status is None:
            continue
        col = week_index[row.week]
        z[row.weekday][col] = status_order.index(row.status)
        text[row.weekday][col] = (
            f"{row.date.strftime('%a %b %d, %Y')}<br>{DAY_STATUS_LABELS[row.status]}"
        )

    n = len(status_order)
    colorscale = []
    for i, status in enumerate(status_order):
        colorscale.append((i / n, DAY_STATUS_COLORS[status]))
        colorscale.append(((i + 1) / n, DAY_STATUS_COLORS[status]))

    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=[w.strftime("%b %d") for w in weeks],
            y=WEEKDAY_NAMES,
            zmin=-0.5,
            zmax=n - 0.5,
            colorscale=colorscale,
            showscale=False,
            xgap=2,
            ygap=2,
            text=text,
            hoverinfo="text",
            hoverongaps=False,
        )
    )
    for status in status_order:
        fig.add_trace(
            go.Scatter(
                x=[None],
                y=[None],
                mode="markers",
                marker=dict(size=10, color=DAY_STATUS_COLORS[status], symbol="square"),
                name=DAY_STATUS_LABELS[status],
            )
        )
    fig.update_yaxes(autorange="reversed", showgrid=False)
    fig.update_xaxes(showgrid=False, tickangle=-45)
    return _base_layout(fig, height=260)


def weekly_rate_line(weekly: pd.DataFrame, rolling_weeks: int = 4) -> go.Figure:
    """Weekly attendance rate with a rolling average. Two series -> legend."""
    weekly = weekly.sort_values("week")
    rolling = weekly["rate"].rolling(rolling_weeks, min_periods=1).mean()
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=weekly["week"],
            y=weekly["rate"],
            mode="lines+markers",
            name="Weekly rate",
            line=dict(color=BLUE, width=2),
            marker=dict(size=6),
            hovertemplate="Week of %{x|%b %d}: %{y:.0%}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=weekly["week"],
            y=rolling,
            mode="lines",
            name=f"{rolling_weeks}-week average",
            line=dict(color=BLUE_LIGHT, width=2, dash="dot"),
            hovertemplate="%{y:.0%}<extra></extra>",
        )
    )
    fig.update_yaxes(tickformat=".0%", rangemode="tozero", title_text="Attendance rate")
    return _base_layout(fig, height=300)


def rate_comparison_bars(
    frame: pd.DataFrame,
    label_col: str,
    rate_col: str = "mean_attendance_rate",
    axis_title: str = "Mean attendance rate",
    full_scale: bool = True,
) -> go.Figure:
    """Single-measure rate comparison across groups: one hue, direct labels."""
    fig = go.Figure(
        go.Bar(
            x=frame[label_col].astype(str),
            y=frame[rate_col],
            marker_color=BLUE,
            text=[f"{v:.0%}" if pd.notna(v) else "" for v in frame[rate_col]],
            textposition="outside",
            textfont=dict(color=INK),
            hovertemplate="%{x}: %{y:.1%}<extra></extra>",
            width=0.5,
        )
    )
    fig.update_yaxes(tickformat=".0%", title_text=axis_title)
    if full_scale:
        fig.update_yaxes(range=[0, 1.08])
    else:
        fig.update_yaxes(rangemode="tozero")
    return _base_layout(fig, height=300)


#: Event-category colors for breakdown bars — same state semantics as the
#: calendar (unexcused=critical, excused=serious, tardy=warning).
CATEGORY_MEASURE_COLORS = {
    "unexcused": "#d03b3b",
    "excused": "#ec835a",
    "tardies": "#fab219",
}
CATEGORY_MEASURE_LABELS = {
    "unexcused": "Unexcused absences",
    "excused": "Excused absences",
    "tardies": "Tardies",
}


def category_stack_bars(frame: pd.DataFrame, label_col: str) -> go.Figure:
    """Stacked unexcused/excused/tardy counts per label (period, etc.)."""
    fig = go.Figure()
    for measure in ("unexcused", "excused", "tardies"):
        if measure not in frame.columns:
            continue
        fig.add_trace(
            go.Bar(
                x=frame[label_col].astype(str),
                y=frame[measure],
                name=CATEGORY_MEASURE_LABELS[measure],
                marker=dict(
                    color=CATEGORY_MEASURE_COLORS[measure],
                    line=dict(color="#ffffff", width=2),
                ),
                hovertemplate="%{x} — "
                + CATEGORY_MEASURE_LABELS[measure]
                + ": %{y}<extra></extra>",
            )
        )
    fig.update_layout(barmode="stack")
    fig.update_yaxes(title_text="Events", rangemode="tozero")
    return _base_layout(fig, height=300)


def top_hbar(
    frame: pd.DataFrame, label_col: str, value_col: str, axis_title: str,
    top_n: int = 15,
) -> go.Figure:
    """Horizontal top-N bar for long labels (courses, teachers). One hue,
    worst at the top, direct count labels."""
    top = frame.nlargest(top_n, value_col).iloc[::-1]
    fig = go.Figure(
        go.Bar(
            x=top[value_col],
            y=top[label_col].astype(str),
            orientation="h",
            marker_color=BLUE,
            text=top[value_col],
            textposition="outside",
            textfont=dict(color=INK),
            hovertemplate="%{y}: %{x}<extra></extra>",
        )
    )
    fig.update_xaxes(title_text=axis_title, rangemode="tozero")
    fig.update_yaxes(automargin=True)
    return _base_layout(fig, height=max(240, 30 * len(top) + 80))


def grouped_rate_bars(
    frame: pd.DataFrame,
    label_col: str,
    caseload_col: str,
    baseline_col: str,
) -> go.Figure:
    """Caseload (blue) vs schoolwide baseline (gray) per group. Legend on."""
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=frame[label_col].astype(str),
            y=frame[caseload_col],
            name="Caseload",
            marker_color=BLUE,
            hovertemplate="%{x} caseload: %{y:.1%}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            x=frame[label_col].astype(str),
            y=frame[baseline_col],
            name="Schoolwide",
            marker_color=BASELINE_GRAY,
            hovertemplate="%{x} schoolwide: %{y:.1%}<extra></extra>",
        )
    )
    fig.update_layout(barmode="group", bargroupgap=0.08)
    fig.update_yaxes(tickformat=".0%", rangemode="tozero", title_text="Mean attendance rate")
    return _base_layout(fig, height=300)


def tier_mix_stacked(group_frame: pd.DataFrame, label_col: str) -> go.Figure:
    """Stacked tier mix per group (status colors, 2px spacers, legend)."""
    fig = go.Figure()
    for tier in TIER_ORDER:
        col = tier.value
        if col not in group_frame.columns:
            continue
        fig.add_trace(
            go.Bar(
                x=group_frame[label_col].astype(str),
                y=group_frame[col],
                name=TIER_LABELS[tier],
                marker=dict(
                    color=TIER_COLORS[tier.value],
                    line=dict(color="#ffffff", width=2),
                ),
                hovertemplate="%{x} — " + TIER_LABELS[tier] + ": %{y}<extra></extra>",
            )
        )
    fig.update_layout(barmode="stack")
    fig.update_yaxes(title_text="Students", rangemode="tozero")
    return _base_layout(fig, height=320)


def weekday_bars(
    caseload: pd.DataFrame, baseline: pd.DataFrame | None
) -> go.Figure:
    """Caseload absence rate by weekday (bars) vs schoolwide (gray line)."""
    caseload = caseload.sort_values("weekday")
    fig = go.Figure(
        go.Bar(
            x=[WEEKDAY_NAMES[int(d)] for d in caseload["weekday"]],
            y=caseload["absence_rate"],
            name="Caseload",
            marker_color=BLUE,
            width=0.5,
            hovertemplate="%{x}: %{y:.1%} absent<extra></extra>",
        )
    )
    if baseline is not None and not baseline.empty:
        baseline = baseline.sort_values("weekday")
        fig.add_trace(
            go.Scatter(
                x=[WEEKDAY_NAMES[int(d)] for d in baseline["weekday"]],
                y=baseline["absence_rate"],
                name="Schoolwide",
                mode="lines+markers",
                line=dict(color=BASELINE_GRAY, width=2),
                marker=dict(size=8),
                hovertemplate="%{x} schoolwide: %{y:.1%}<extra></extra>",
            )
        )
    fig.update_yaxes(tickformat=".0%", rangemode="tozero", title_text="Absence rate")
    return _base_layout(fig, height=300)


def period_bars(period_frame: pd.DataFrame) -> go.Figure:
    """One student's unexcused-absence rate by class period. Single hue."""
    frame = period_frame.copy()
    frame["_sort"] = pd.to_numeric(frame["period"], errors="coerce")
    frame = frame.sort_values(["_sort", "period"])
    fig = go.Figure(
        go.Bar(
            x="P" + frame["period"].astype(str),
            y=frame["rate"],
            marker_color=BLUE,
            width=0.5,
            text=[f"{v:.0%}" for v in frame["rate"]],
            textposition="outside",
            textfont=dict(color=INK),
            hovertemplate="Period %{x}: %{y:.1%} unexcused<extra></extra>",
        )
    )
    fig.update_yaxes(tickformat=".0%", rangemode="tozero", title_text="Unexcused rate")
    return _base_layout(fig, height=280)


def tardy_weekday_bar(day_status: pd.DataFrame) -> go.Figure:
    """Caseload tardies by weekday. Single hue, direct labels."""
    frame = day_status.copy()
    frame["weekday"] = frame["date"].dt.weekday
    counts = (
        frame[frame["weekday"] < 5]
        .groupby("weekday", observed=True)["is_tardy_day"]
        .sum()
        .reindex(range(5), fill_value=0)
    )
    fig = go.Figure(
        go.Bar(
            x=WEEKDAY_NAMES,
            y=counts.values,
            marker_color=BLUE,
            width=0.5,
            text=[int(v) for v in counts.values],
            textposition="outside",
            textfont=dict(color=INK),
            hovertemplate="%{x}: %{y} tardies<extra></extra>",
        )
    )
    fig.update_yaxes(title_text="Tardy days", rangemode="tozero")
    return _base_layout(fig, height=280)
