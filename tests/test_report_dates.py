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
