"""School-days inference: the distinct dates in a schoolwide exception report
are the school days elapsed (every school day, someone has a mark)."""

from __future__ import annotations

import pandas as pd
import pytest

from attendance_tracker import codes as codes_mod
from attendance_tracker import detection, normalize
from attendance_tracker.constants import Shape
from attendance_tracker.model import ColumnMapping


def test_report_dates_strips_suffixes_dedupes_and_sorts():
    frame = pd.DataFrame(
        {
            "Sis Number": ["1", "2", "3", "4", "5", "6"],
            "Date": [
                "09/09/2025 (D2S)",
                "09/08/2025",
                "09/08/2025 (A)",
                "not a date",
                None,
                "  09/10/2025 (D2S)",
            ],
        }
    )
    mapping = ColumnMapping(
        shape=Shape.PERIOD_WIDE,
        columns={"student_id": "Sis Number", "date": "Date"},
    )
    dates = normalize.report_dates(frame, mapping)
    assert list(dates) == [
        pd.Timestamp("2025-09-08"),
        pd.Timestamp("2025-09-09"),
        pd.Timestamp("2025-09-10"),
    ]


def test_report_dates_empty_without_date_column():
    frame = pd.DataFrame({"Sis Number": ["1"]})
    mapping = ColumnMapping(
        shape=Shape.SUMMARY, columns={"student_id": "Sis Number"}
    )
    assert len(normalize.report_dates(frame, mapping)) == 0


def _future_str(days=30):
    return (
        pd.Timestamp.today().normalize() + pd.Timedelta(days=days)
    ).strftime("%m/%d/%Y")


def test_future_marks_dropped_from_wide_events():
    """Synergy allows pre-scheduled marks; a mark that hasn't happened yet
    must not count as an absence taken."""
    frame = pd.DataFrame(
        {
            "Sis Number": ["1", "1"],
            "Date": ["09/08/2025 (D2S)", f"{_future_str()} (D2S)"],
            "Period 1": ["UNVERIFIED", "ILNESS"],
            "Period 2": [None, None],
        }
    )
    mapping = ColumnMapping(
        shape=Shape.PERIOD_WIDE,
        columns={"student_id": "Sis Number", "date": "Date"},
    )
    code_map = codes_mod.propose_code_map({"UNVERIFIED": 1, "ILNESS": 1})
    events, warnings = normalize.build_events_wide(frame, mapping, code_map)
    assert list(events["date"]) == [pd.Timestamp("2025-09-08")]
    assert any("future" in w.lower() for w in warnings)


def test_future_marks_dropped_from_daily_events():
    frame = pd.DataFrame(
        {
            "ID": ["1", "1"],
            "Date": ["09/08/2025", _future_str()],
            "Code": ["A", "A"],
        }
    )
    mapping = ColumnMapping(
        shape=Shape.DAILY,
        columns={"student_id": "ID", "date": "Date", "code": "Code"},
    )
    code_map = codes_mod.propose_code_map({"A": 2})
    events, warnings = normalize.build_events(frame, mapping, code_map)
    assert list(events["date"]) == [pd.Timestamp("2025-09-08")]
    assert any("future" in w.lower() for w in warnings)


def test_report_dates_matches_atp201_event_calendar(
    small_dataset, as_xlsx_bytes
):
    """The inferred school days equal the calendar the pipeline itself derives
    from the same report (unique event dates), so the prefill and the analysis
    agree by construction."""
    data = as_xlsx_bytes(small_dataset["report_atp201"])
    frame, result = detection.detect_report(data, "report.xlsx")
    mapping = ColumnMapping(shape=result.shape, columns=result.mapping)
    code_map = codes_mod.propose_code_map(result.observed_codes)

    inferred = normalize.report_dates(frame, mapping)
    events, _ = normalize.build_events_wide(frame, mapping, code_map)
    event_dates = pd.DatetimeIndex(sorted(events["date"].dropna().unique()))

    assert len(inferred) > 0
    assert list(inferred) == list(event_dates)
