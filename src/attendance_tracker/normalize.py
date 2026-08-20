"""Student-ID normalization and canonical frame builders.

Turns raw uploaded frames plus a user-confirmed :class:`ColumnMapping` into
the canonical students / events / summary frames the rest of the pipeline
consumes. Pure pandas/numpy — no UI imports.

Canonical dtypes: student_id/name/grade/code/period columns use pandas
"string" dtype with ``pd.NA`` for missing; dates are ``datetime64[ns]``
normalized to midnight; category columns store ``Category.value`` strings.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .constants import Shape
from .model import CodeMap, ColumnMapping


def normalize_id(value) -> str | None:
    """Normalize one raw student-ID cell to a canonical string.

    Missing values (None / NaN / pd.NA / empty or whitespace-only string)
    return ``None``. Integral floats (Excel's ``123456.0``) become
    ``'123456'``; ints become their decimal string; strings are stripped of
    surrounding whitespace and of a trailing ``'.0'`` when the remainder is
    all digits (``'123456.0'`` -> ``'123456'``). Leading zeros are KEPT —
    ``'004512'`` stays ``'004512'``.
    """
    if value is None:
        return None
    if isinstance(value, (float, np.floating)):
        as_float = float(value)
        if np.isnan(as_float):
            return None
        if as_float.is_integer():
            return str(int(as_float))
        return str(as_float)
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):  # non-scalar oddities: fall through to str()
        pass
    text = str(value).strip()
    if not text:
        return None
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text


def normalize_id_series(s: pd.Series) -> pd.Series:
    """Apply :func:`normalize_id` element-wise; "string" dtype, pd.NA missing."""
    return s.map(normalize_id).astype("string")


def make_match_key(s: pd.Series) -> pd.Series:
    """Zero-insensitive join key: leading zeros stripped, all-zero IDs -> '0'.

    Input should be an already-normalized ID series; output is "string" dtype
    with pd.NA preserved.
    """
    key = s.astype("string").str.lstrip("0")
    empty = (key == "").fillna(False)
    return key.mask(empty, "0")


def _string_column(series: pd.Series) -> pd.Series:
    """Cast a source column to "string" dtype, stripping surrounding spaces."""
    return series.astype("string").str.strip()


def _na_string_column(index: pd.Index) -> pd.Series:
    return pd.Series(pd.NA, index=index, dtype="string")


def _drop_missing_ids(
    frame: pd.DataFrame, warnings: list[str]
) -> pd.DataFrame:
    missing = frame["student_id"].isna()
    if missing.any():
        warnings.append(
            f"Dropped {int(missing.sum())} row(s) with missing student ID."
        )
        frame = frame.loc[~missing]
    return frame


def build_students(
    frame: pd.DataFrame, mapping: ColumnMapping
) -> tuple[pd.DataFrame, list[str]]:
    """Build the canonical caseload frame from a raw upload + confirmed mapping.

    Output columns: student_id, match_key, name ('Last, First' when built from
    parts), grade, group (all pd.NA — filled later in the UI), plus every
    unmapped source column preserved verbatim as "string" dtype (extra
    group-by candidates). Rows with missing student_id are dropped with a
    warning; duplicate student_ids keep the first occurrence with a warning
    listing the dropped IDs.
    """
    warnings: list[str] = []
    cols = mapping.columns
    out = pd.DataFrame(index=frame.index)

    student_id = normalize_id_series(frame[cols["student_id"]])
    out["student_id"] = student_id
    out["match_key"] = make_match_key(student_id)

    if "name" in cols:
        out["name"] = _string_column(frame[cols["name"]])
    elif "first_name" in cols and "last_name" in cols:
        first = _string_column(frame[cols["first_name"]])
        last = _string_column(frame[cols["last_name"]])
        out["name"] = last + ", " + first
    else:
        out["name"] = _na_string_column(frame.index)

    if "grade" in cols:
        out["grade"] = _string_column(frame[cols["grade"]])
    else:
        out["grade"] = _na_string_column(frame.index)

    out["group"] = _na_string_column(frame.index)

    mapped_sources = set(cols.values())
    for column in frame.columns:
        if column in mapped_sources or str(column) in out.columns:
            continue
        out[str(column)] = frame[column].astype("string")

    out = _drop_missing_ids(out, warnings)

    duplicated = out["student_id"].duplicated(keep="first")
    if duplicated.any():
        dropped_ids = sorted(set(out.loc[duplicated, "student_id"].tolist()))
        warnings.append(
            "Dropped duplicate student ID(s), keeping the first occurrence: "
            + ", ".join(dropped_ids)
        )
        out = out.loc[~duplicated]

    return out.reset_index(drop=True), warnings


def build_events(
    frame: pd.DataFrame, mapping: ColumnMapping, code_map: CodeMap
) -> tuple[pd.DataFrame, list[str]]:
    """Build the canonical event frame for Shape.DAILY / Shape.PERIOD reports.

    Output columns: student_id, date (midnight datetime64[ns]), period
    ("string"; pd.NA for DAILY), code (stripped + uppercased), category
    (Category.value via code_map), plus name/grade when those roles are
    mapped. Rows with missing student_id or unparseable dates are dropped
    with count warnings.
    """
    warnings: list[str] = []
    cols = mapping.columns
    out = pd.DataFrame(index=frame.index)

    out["student_id"] = normalize_id_series(frame[cols["student_id"]])
    out["date"] = (
        pd.to_datetime(frame[cols["date"]], errors="coerce")
        .astype("datetime64[ns]")
        .dt.normalize()
    )

    if mapping.shape is Shape.PERIOD and "period" in cols:
        out["period"] = _string_column(frame[cols["period"]])
    else:
        out["period"] = _na_string_column(frame.index)

    code = frame[cols["code"]].astype("string").str.strip().str.upper()
    out["code"] = code
    out["category"] = code.map(
        lambda c: code_map.category_for(c).value, na_action="ignore"
    ).astype("string")

    for role in ("name", "grade"):
        if role in cols:
            out[role] = _string_column(frame[cols[role]])

    out = _drop_missing_ids(out, warnings)

    bad_dates = out["date"].isna()
    if bad_dates.any():
        warnings.append(
            f"Dropped {int(bad_dates.sum())} row(s) with unparseable dates."
        )
        out = out.loc[~bad_dates]

    return out.reset_index(drop=True), warnings


#: Leading date token of strings like '08/07/2026 (D2S)' — ATP201 date cells
#: carry a schedule-type suffix that must not reach the date parser.
_DATE_PREFIX_RE = r"^\s*([0-9][0-9/\-\.]*)"


def build_events_wide(
    frame: pd.DataFrame, mapping: ColumnMapping, code_map: CodeMap
) -> tuple[pd.DataFrame, list[str]]:
    """Build canonical events from a wide period report (Shape.PERIOD_WIDE).

    The input (e.g. Synergy ATP201) has one row per student per day and one
    column per period; each cell is a code word or blank. Only marked cells
    become events — a blank cell means present/unscheduled, and days with no
    marks don't appear at all (exception report). Date cells may carry a
    schedule-type suffix like '08/07/2026 (D2S)', which is stripped.

    Privacy: every column that is not the student id, date, grade, name, or a
    'Period N' column is discarded here — the demographic and family-contact
    columns of a full ATP201 export never reach the analysis frames.
    """
    from .detection import period_wide_columns  # function-level: avoids a cycle

    warnings: list[str] = []
    period_columns = period_wide_columns(frame)
    if not period_columns:
        raise ValueError("no 'Period N' columns found for a wide period report")
    cols = mapping.columns

    base = pd.DataFrame(index=frame.index)
    base["student_id"] = normalize_id_series(frame[cols["student_id"]])
    date_text = (
        frame[cols["date"]].astype("string").str.extract(_DATE_PREFIX_RE)[0]
    )
    base["date"] = (
        pd.to_datetime(date_text, errors="coerce")
        .astype("datetime64[ns]")
        .dt.normalize()
    )
    for role in ("name", "grade"):
        if role in cols:
            base[role] = _string_column(frame[cols[role]])

    pieces: list[pd.DataFrame] = []
    for column in period_columns:
        digits = "".join(ch for ch in str(column) if ch.isdigit())
        cell = frame[column].astype("string").str.strip()
        marked = (cell.notna() & (cell != "")).fillna(False)
        if not marked.any():
            continue
        piece = base.loc[marked].copy()
        piece["period"] = pd.array([digits] * len(piece), dtype="string")
        code = cell.loc[marked].str.upper()
        piece["code"] = code
        piece["category"] = code.map(
            lambda c: code_map.category_for(c).value, na_action="ignore"
        ).astype("string")
        pieces.append(piece)

    columns_order = ["student_id", "date", "period", "code", "category"] + [
        role for role in ("name", "grade") if role in cols
    ]
    if pieces:
        out = pd.concat(pieces)[columns_order]
    else:
        out = base.iloc[0:0].reindex(columns=columns_order)
        warnings.append("No attendance marks were found in the period columns.")

    out = _drop_missing_ids(out, warnings)
    bad_dates = out["date"].isna()
    if bad_dates.any():
        warnings.append(
            f"Dropped {int(bad_dates.sum())} row(s) with unparseable dates."
        )
        out = out.loc[~bad_dates]

    return out.sort_values(["student_id", "date"]).reset_index(drop=True), warnings


def build_summary(
    frame: pd.DataFrame, mapping: ColumnMapping
) -> tuple[pd.DataFrame, list[str]]:
    """Build the canonical per-student summary frame for Shape.SUMMARY reports.

    Output columns: student_id, days_enrolled, days_absent, days_excused,
    days_unexcused, days_tardy (float64, NaN where unmapped), attendance_rate
    (float 0..1), plus name/grade when mapped.

    Derivations: days_absent falls back to excused + unexcused when unmapped;
    a 0..100-scale percent column is divided by 100; attendance_rate is
    recomputed from days_absent/days_enrolled where possible (source percent
    columns are often rounded), else taken from the percent column; when
    days_enrolled is unmapped but days_absent and a percent are available,
    days_enrolled is back-derived as days_absent / (1 - rate) where rate < 1,
    with a warning.
    """
    warnings: list[str] = []
    cols = mapping.columns

    def numeric(role: str) -> pd.Series:
        if role in cols:
            return pd.to_numeric(frame[cols[role]], errors="coerce").astype(
                "float64"
            )
        return pd.Series(np.nan, index=frame.index, dtype="float64")

    student_id = normalize_id_series(frame[cols["student_id"]])
    days_enrolled = numeric("days_enrolled")
    days_absent = numeric("days_absent")
    days_excused = numeric("days_excused")
    days_unexcused = numeric("days_unexcused")
    days_tardy = numeric("days_tardy")

    if (
        "days_absent" not in cols
        and "days_excused" in cols
        and "days_unexcused" in cols
    ):
        days_absent = days_excused + days_unexcused

    pct: pd.Series | None = None
    if "attendance_pct" in cols:
        pct = pd.to_numeric(frame[cols["attendance_pct"]], errors="coerce").astype(
            "float64"
        )
        if (pct > 1.5).any():  # looks like a 0..100 scale
            pct = pct / 100.0

    rate = (1.0 - days_absent / days_enrolled).where(days_enrolled > 0)
    if pct is not None:
        rate = rate.fillna(pct)

    if "days_enrolled" not in cols and pct is not None and days_absent.notna().any():
        days_enrolled = (days_absent / (1.0 - rate)).where(rate < 1.0).astype(
            "float64"
        )
        warnings.append(
            "Days enrolled column missing; back-derived from days absent and "
            "the attendance rate."
        )

    out = pd.DataFrame(
        {
            "student_id": student_id,
            "days_enrolled": days_enrolled,
            "days_absent": days_absent,
            "days_excused": days_excused,
            "days_unexcused": days_unexcused,
            "days_tardy": days_tardy,
            "attendance_rate": rate.astype("float64"),
        }
    )
    for role in ("name", "grade"):
        if role in cols:
            out[role] = _string_column(frame[cols[role]])

    out = _drop_missing_ids(out, warnings)
    return out.reset_index(drop=True), warnings
