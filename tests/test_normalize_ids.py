"""Tests for ID normalization and the canonical frame builders."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from attendance_tracker.constants import Category, Shape
from attendance_tracker.model import CodeMap, ColumnMapping
from attendance_tracker.normalize import (
    build_events,
    build_students,
    build_summary,
    make_match_key,
    normalize_id,
    normalize_id_series,
)


class TestNormalizeId:
    def test_integral_float(self):
        assert normalize_id(123456.0) == "123456"

    def test_numpy_float(self):
        assert normalize_id(np.float64(123456.0)) == "123456"

    def test_string_with_spaces(self):
        assert normalize_id("  4512 ") == "4512"

    def test_leading_zeros_kept(self):
        assert normalize_id("004512") == "004512"

    def test_string_trailing_point_zero(self):
        assert normalize_id("123456.0") == "123456"

    def test_ints(self):
        assert normalize_id(789) == "789"
        assert normalize_id(np.int64(789)) == "789"

    def test_missing_values(self):
        assert normalize_id(None) is None
        assert normalize_id(float("nan")) is None
        assert normalize_id(np.nan) is None
        assert normalize_id(pd.NA) is None
        assert normalize_id("") is None
        assert normalize_id("   ") is None

    def test_non_numeric_id_kept_verbatim(self):
        # '.0' is only stripped when the rest is all digits
        assert normalize_id("AB123.0") == "AB123.0"


def test_normalize_id_series():
    raw = pd.Series([123456.0, np.nan, None, "", " 004512 ", "77.0"], dtype=object)
    result = normalize_id_series(raw)
    expected = pd.Series(
        ["123456", pd.NA, pd.NA, pd.NA, "004512", "77"], dtype="string"
    )
    pd.testing.assert_series_equal(result, expected)


def test_make_match_key():
    ids = pd.Series(["004512", "0000", "123", pd.NA], dtype="string")
    expected = pd.Series(["4512", "0", "123", pd.NA], dtype="string")
    pd.testing.assert_series_equal(make_match_key(ids), expected)


class TestBuildStudents:
    def test_full_build_with_name_parts_extras_and_warnings(self):
        frame = pd.DataFrame(
            {
                "Student Number": [123456.0, 4512.0, 123456.0, np.nan],
                "Last": ["Sampleton", "Fixture", "Sampleton", "Ghost"],
                "First": ["Rosa", "Ezra", "Rosa", "Gone"],
                "Grade": [9, 10, 9, 11],
                "Case Manager": ["JV", "OTHER", "JV", "JV"],
            }
        )
        mapping = ColumnMapping(
            shape=Shape.UNKNOWN,
            columns={
                "student_id": "Student Number",
                "first_name": "First",
                "last_name": "Last",
                "grade": "Grade",
            },
        )
        students, warnings = build_students(frame, mapping)

        assert students["student_id"].tolist() == ["123456", "4512"]
        assert students["match_key"].tolist() == ["123456", "4512"]
        assert students["name"].tolist() == ["Sampleton, Rosa", "Fixture, Ezra"]
        assert students["grade"].tolist() == ["9", "10"]
        assert students["group"].isna().all()
        # unmapped source column preserved verbatim as a string column
        assert students["Case Manager"].tolist() == ["JV", "OTHER"]
        for col in ("student_id", "match_key", "name", "grade", "group",
                    "Case Manager"):
            assert students[col].dtype == "string"

        missing_warnings = [w for w in warnings if "missing" in w.lower()]
        dup_warnings = [w for w in warnings if "duplicate" in w.lower()]
        assert len(missing_warnings) == 1
        assert "1" in missing_warnings[0]
        assert len(dup_warnings) == 1
        assert "123456" in dup_warnings[0]

    def test_name_from_single_column_and_unmapped_grade(self):
        frame = pd.DataFrame(
            {"ID": ["001"], "Student Name": [" Fixture, Ezra "]}
        )
        mapping = ColumnMapping(
            shape=Shape.UNKNOWN,
            columns={"student_id": "ID", "name": "Student Name"},
        )
        students, warnings = build_students(frame, mapping)
        assert students["student_id"].tolist() == ["001"]
        assert students["match_key"].tolist() == ["1"]
        assert students["name"].tolist() == ["Fixture, Ezra"]
        assert students["grade"].isna().all()
        assert warnings == []


class TestBuildEvents:
    def test_period_shape_codes_categories_and_date_drop(self):
        frame = pd.DataFrame(
            {
                "ID": ["001001", "001002", "001003", "001004"],
                "Date": ["2025-09-08", "2025-09-09", "not a date", "2025-09-10"],
                "Code": [" a ", "e", "T", "q"],
                "Per": [1, 5, 3, 7],
            }
        )
        mapping = ColumnMapping(
            shape=Shape.PERIOD,
            columns={
                "student_id": "ID",
                "date": "Date",
                "code": "Code",
                "period": "Per",
            },
        )
        code_map = CodeMap(
            codes={
                "A": Category.ABSENT_UNEXCUSED,
                "E": Category.ABSENT_EXCUSED,
                "T": Category.TARDY,
            }
        )
        events, warnings = build_events(frame, mapping, code_map)

        assert len(events) == 3
        assert events["student_id"].tolist() == ["001001", "001002", "001004"]
        assert events["code"].tolist() == ["A", "E", "Q"]
        assert events["category"].tolist() == [
            "absent_unexcused",
            "absent_excused",
            "unknown",
        ]
        assert events["period"].tolist() == ["1", "5", "7"]
        assert events["date"].tolist() == [
            pd.Timestamp("2025-09-08"),
            pd.Timestamp("2025-09-09"),
            pd.Timestamp("2025-09-10"),
        ]
        assert events["date"].dtype == "datetime64[ns]"
        for col in ("student_id", "period", "code", "category"):
            assert events[col].dtype == "string"
        assert len(warnings) == 1
        assert "1" in warnings[0] and "date" in warnings[0].lower()

    def test_daily_shape_period_na_and_midnight_normalization(self):
        frame = pd.DataFrame(
            {
                "ID": [111, 222],
                "Date": ["2025-09-08 08:15:00", "2025-09-09 13:00:00"],
                "Code": ["P", "T"],
            }
        )
        mapping = ColumnMapping(
            shape=Shape.DAILY,
            columns={"student_id": "ID", "date": "Date", "code": "Code"},
        )
        code_map = CodeMap(
            codes={"P": Category.PRESENT, "T": Category.TARDY}
        )
        events, warnings = build_events(frame, mapping, code_map)
        assert events["student_id"].tolist() == ["111", "222"]
        assert events["period"].isna().all()
        assert events["period"].dtype == "string"
        assert events["date"].tolist() == [
            pd.Timestamp("2025-09-08"),
            pd.Timestamp("2025-09-09"),
        ]
        assert warnings == []

    def test_missing_student_id_rows_dropped_with_warning(self):
        frame = pd.DataFrame(
            {
                "ID": ["100", None, "300"],
                "Date": ["2025-09-08", "2025-09-08", "2025-09-08"],
                "Code": ["A", "A", "P"],
            }
        )
        mapping = ColumnMapping(
            shape=Shape.DAILY,
            columns={"student_id": "ID", "date": "Date", "code": "Code"},
        )
        code_map = CodeMap(
            codes={"A": Category.ABSENT_UNEXCUSED, "P": Category.PRESENT}
        )
        events, warnings = build_events(frame, mapping, code_map)
        assert events["student_id"].tolist() == ["100", "300"]
        assert len(warnings) == 1
        assert "1" in warnings[0] and "missing" in warnings[0].lower()


class TestBuildSummary:
    def test_pct_scaled_and_rate_recomputed_from_counts(self):
        # Percent column is rounded on purpose; the rate must be recomputed
        # from absent/enrolled, not taken from the percent column.
        frame = pd.DataFrame(
            {
                "ID": ["1", "2"],
                "Enrolled": [40, 40],
                "Absent": [4, 10],
                "Pct": [90.4, 74.6],
            }
        )
        mapping = ColumnMapping(
            shape=Shape.SUMMARY,
            columns={
                "student_id": "ID",
                "days_enrolled": "Enrolled",
                "days_absent": "Absent",
                "attendance_pct": "Pct",
            },
        )
        summary, warnings = build_summary(frame, mapping)
        assert summary["attendance_rate"].tolist() == pytest.approx([0.9, 0.75])
        assert summary["days_enrolled"].tolist() == [40.0, 40.0]
        assert summary["days_absent"].tolist() == [4.0, 10.0]
        assert summary["days_excused"].isna().all()
        assert summary["days_tardy"].isna().all()
        assert warnings == []

    def test_absent_derived_from_excused_plus_unexcused(self):
        frame = pd.DataFrame(
            {
                "ID": ["1", "2"],
                "Enrolled": [30, 30],
                "Exc": [2, 3],
                "Unexc": [1, 0],
            }
        )
        mapping = ColumnMapping(
            shape=Shape.SUMMARY,
            columns={
                "student_id": "ID",
                "days_enrolled": "Enrolled",
                "days_excused": "Exc",
                "days_unexcused": "Unexc",
            },
        )
        summary, warnings = build_summary(frame, mapping)
        assert summary["days_absent"].tolist() == [3.0, 3.0]
        assert summary["attendance_rate"].tolist() == pytest.approx([0.9, 0.9])
        assert warnings == []

    def test_enrolled_back_derived_with_warning(self):
        frame = pd.DataFrame(
            {"ID": ["1", "2"], "Absent": [5, 0], "Pct": [90.0, 100.0]}
        )
        mapping = ColumnMapping(
            shape=Shape.SUMMARY,
            columns={
                "student_id": "ID",
                "days_absent": "Absent",
                "attendance_pct": "Pct",
            },
        )
        summary, warnings = build_summary(frame, mapping)
        # 5 absences at 90% attendance -> 50 enrolled days
        assert summary["days_enrolled"].iloc[0] == pytest.approx(50.0)
        # rate == 1 -> cannot back-derive
        assert np.isnan(summary["days_enrolled"].iloc[1])
        assert summary["attendance_rate"].tolist() == pytest.approx([0.9, 1.0])
        assert len(warnings) == 1
        assert "back-derived" in warnings[0]

    def test_pct_only_file(self):
        frame = pd.DataFrame({"ID": ["1", "2"], "Rate": [0.95, 0.88]})
        mapping = ColumnMapping(
            shape=Shape.SUMMARY,
            columns={"student_id": "ID", "attendance_pct": "Rate"},
        )
        summary, warnings = build_summary(frame, mapping)
        # already 0..1 scale -> not divided by 100
        assert summary["attendance_rate"].tolist() == pytest.approx([0.95, 0.88])
        for col in (
            "days_enrolled",
            "days_absent",
            "days_excused",
            "days_unexcused",
            "days_tardy",
        ):
            assert summary[col].isna().all()
            assert summary[col].dtype == "float64"
        assert warnings == []
