"""Tests for detection: role inference, shape detection, and full pipelines."""

from __future__ import annotations

import pandas as pd

from attendance_tracker import detection, sample_data
from attendance_tracker.constants import Shape


# ---------------------------------------------------------------------------
# infer_roles
# ---------------------------------------------------------------------------


def test_infer_roles_specific_synonyms_win():
    frame = pd.DataFrame(
        {
            "Student ID": ["900001", "900002", "900003"],
            "Attendance Code": ["P", "A", "T"],
            "Grade": ["06", "07", "08"],
        }
    )
    mapping = detection.infer_roles(
        frame, ["student_id", "name", "grade", "code", "attendance_pct"]
    )
    # "Student ID" must beat the 'name' synonym "student".
    assert mapping["student_id"] == "Student ID"
    # "Attendance Code" must map to code, not attendance_pct.
    assert mapping["code"] == "Attendance Code"
    assert mapping["grade"] == "Grade"
    assert "name" not in mapping
    assert "attendance_pct" not in mapping


def test_infer_roles_drops_date_contradicted_by_values():
    frame = pd.DataFrame(
        {
            "Student ID": ["900001", "900002", "900003"],
            "Date": ["apple", "banana", "cherry"],
        }
    )
    mapping = detection.infer_roles(frame, ["student_id", "date"])
    assert mapping["student_id"] == "Student ID"
    assert "date" not in mapping


# ---------------------------------------------------------------------------
# detect_report: clean shapes
# ---------------------------------------------------------------------------


def test_clean_daily_report(small_dataset, as_csv_bytes):
    report = small_dataset["report_daily"]
    frame, result = detection.detect_report(as_csv_bytes(report), "daily.csv")
    assert result.shape is Shape.DAILY
    assert result.confidence == "high"
    assert result.header_row == 0
    assert result.warnings == []
    assert result.mapping["student_id"] == "Student ID"
    assert result.mapping["name"] == "Student Name"
    assert result.mapping["grade"] == "Grade"
    assert result.mapping["date"] == "Date"
    assert result.mapping["code"] == "Attendance Code"
    assert "period" not in result.mapping
    assert set(result.observed_codes) == {"P", "A", "E", "T"}
    assert sum(result.observed_codes.values()) == len(report)


def test_clean_daily_report_xlsx(small_dataset, as_xlsx_bytes):
    report = small_dataset["report_daily"]
    frame, result = detection.detect_report(as_xlsx_bytes(report), "daily.xlsx")
    assert result.shape is Shape.DAILY
    assert result.confidence == "high"
    assert result.mapping["code"] == "Attendance Code"
    assert set(result.observed_codes) == {"P", "A", "E", "T"}


def test_clean_summary_report(small_dataset, as_csv_bytes):
    report = small_dataset["report_summary"]
    frame, result = detection.detect_report(as_csv_bytes(report), "summary.csv")
    assert result.shape is Shape.SUMMARY
    assert result.confidence == "high"
    assert result.mapping["student_id"] == "Student ID"
    assert result.mapping["name"] == "Student Name"
    assert result.mapping["days_enrolled"] == "Days Enrolled"
    assert result.mapping["days_absent"] == "Days Absent"
    assert result.mapping["days_tardy"] == "Days Tardy"
    assert result.mapping["attendance_pct"] == "Attendance %"
    assert "date" not in result.mapping
    assert "code" not in result.mapping
    assert result.observed_codes == {}


def test_clean_period_report(small_dataset, as_csv_bytes):
    report = small_dataset["report_period"]
    frame, result = detection.detect_report(as_csv_bytes(report), "period.csv")
    assert result.shape is Shape.PERIOD
    assert result.confidence == "high"
    assert result.mapping["student_id"] == "Student ID"
    assert result.mapping["date"] == "Date"
    assert result.mapping["period"] == "Period"
    assert result.mapping["code"] == "Code"
    assert set(result.observed_codes) == {"P", "A", "E", "T"}
    assert sum(result.observed_codes.values()) == len(report)


# ---------------------------------------------------------------------------
# detect_report: messy and renamed variants
# ---------------------------------------------------------------------------


def test_messy_daily_report_with_preamble(small_dataset, as_csv_bytes):
    messy = small_dataset["report_daily_messy"]
    stacked = sample_data.with_preamble(messy, sample_data.PREAMBLE_LINES)
    frame, result = detection.detect_report(
        as_csv_bytes(stacked, header=False), "messy.csv"
    )
    assert result.shape is Shape.DAILY
    assert result.header_row == 3
    assert result.mapping["student_id"] == "Student ID"
    assert result.mapping["date"] == "Date"
    assert result.mapping["code"] == "Attendance Code"
    assert "Q" in result.observed_codes
    assert sum(result.observed_codes.values()) == len(messy)


def test_period_report_renamed_prd(small_dataset, as_csv_bytes):
    report = small_dataset["report_period"].rename(columns={"Period": "Prd"})
    frame, result = detection.detect_report(as_csv_bytes(report), "period.csv")
    assert result.shape is Shape.PERIOD
    assert result.mapping["period"] == "Prd"


def test_period_report_nonsense_period_name(small_dataset, as_csv_bytes):
    report = small_dataset["report_period"].rename(columns={"Period": "Slot"})
    frame, result = detection.detect_report(as_csv_bytes(report), "period.csv")
    # No synonym matches "Slot": PERIOD must come from the duplicate
    # (student, date) pairs plus period-like values in the unmapped column.
    assert result.shape is Shape.PERIOD
    assert result.mapping["period"] == "Slot"
    assert result.confidence in ("high", "medium")


def test_daily_report_with_few_rows_per_student_downgrades():
    frame = pd.DataFrame(
        {
            "Student ID": ["900001", "900001", "900002", "900002", "900003", "900003"],
            "Date": ["09/08/2025", "09/09/2025"] * 3,
            "Attendance Code": ["P", "A", "P", "P", "E", "T"],
        }
    )
    mapping = detection.infer_roles(frame, detection.REPORT_ROLES)
    shape, confidence, warnings = detection.detect_shape(frame, mapping)
    assert shape is Shape.DAILY
    assert confidence == "medium"  # downgraded from high, never silently
    assert any("rows per student" in warning for warning in warnings)


def test_ambiguous_frame_is_unknown(as_csv_bytes):
    frame = pd.DataFrame(
        {
            "color": ["red", "blue", "teal", "cyan"] * 10,
            "price": [3.5, 12.25, 7.8, 21.4] * 10,
            "qty": [2, 5, 1, 8] * 10,
        }
    )
    loaded, result = detection.detect_report(as_csv_bytes(frame), "mystery.csv")
    assert result.shape is Shape.UNKNOWN
    assert result.confidence == "low"
    assert "student_id" not in result.mapping
    assert "date" not in result.mapping
    assert result.warnings
    assert result.observed_codes == {}


# ---------------------------------------------------------------------------
# detect_caseload
# ---------------------------------------------------------------------------


def test_caseload_detection(small_dataset, as_csv_bytes):
    caseload = small_dataset["caseload"]
    frame, result = detection.detect_caseload(as_csv_bytes(caseload), "caseload.csv")
    assert result.shape is Shape.UNKNOWN
    assert result.confidence == "high"
    assert result.header_row == 0
    assert result.warnings == []
    assert result.mapping["student_id"] == "Student ID"
    assert result.mapping["last_name"] == "Last Name"
    assert result.mapping["first_name"] == "First Name"
    assert result.mapping["grade"] == "Grade"
    assert result.observed_codes == {}


def test_caseload_without_id_column(as_csv_bytes):
    frame = pd.DataFrame(
        {
            "Students": [
                "Testperson, Aaliyah",
                "Example, Bruno",
                "Sampleton, Carmen",
            ]
        }
    )
    loaded, result = detection.detect_caseload(as_csv_bytes(frame), "caseload.csv")
    assert result.confidence == "low"
    assert result.warnings
    assert "student_id" not in result.mapping
    assert result.mapping.get("name") == "Students"
