"""Tests for caseload/report joining and report-side ID rewriting."""

from __future__ import annotations

import pandas as pd

from attendance_tracker.joining import apply_id_map, join_caseload
from attendance_tracker.normalize import make_match_key


def make_students(ids: list[str], names: list[str] | None = None) -> pd.DataFrame:
    student_id = pd.Series(ids, dtype="string")
    return pd.DataFrame(
        {
            "student_id": student_id,
            "match_key": make_match_key(student_id),
            "name": pd.Series(
                names if names is not None else [pd.NA] * len(ids),
                dtype="string",
            ),
            "grade": pd.Series([pd.NA] * len(ids), dtype="string"),
            "group": pd.Series([pd.NA] * len(ids), dtype="string"),
        }
    )


def test_match_key_join_bridges_leading_zeros():
    students = make_students(
        ["0900001", "123"], names=["Sampleton, Rosa", "Fixture, Ezra"]
    )
    report_ids = pd.Series(["900001", "123", "555", "555"], dtype="string")

    result = join_caseload(students, report_ids)

    assert result.used_match_key is True
    assert result.id_map == {"900001": "0900001", "123": "123"}
    assert result.students["matched"].tolist() == [True, True]
    assert result.students["matched"].dtype == bool
    assert len(result.unmatched) == 0
    assert list(result.unmatched.columns) == ["student_id", "name", "hint"]
    # '555' deduped -> one distinct report-only student
    assert result.report_only_count == 1
    assert result.warnings == []


def test_force_exact_yields_leading_zero_hint():
    students = make_students(
        ["0900001", "123"], names=["Sampleton, Rosa", "Fixture, Ezra"]
    )
    report_ids = pd.Series(["900001", "123", "555"], dtype="string")

    result = join_caseload(students, report_ids, force_exact=True)

    assert result.used_match_key is False
    assert result.id_map == {"123": "123"}
    assert result.students["matched"].tolist() == [False, True]
    assert result.unmatched["student_id"].tolist() == ["0900001"]
    assert result.unmatched["name"].tolist() == ["Sampleton, Rosa"]
    assert (
        result.unmatched["hint"].iloc[0]
        == "report has this student as ID 900001 (leading zeros differ)"
    )
    assert result.report_only_count == 2


def test_caseload_collision_falls_back_to_exact_with_warning():
    students = make_students(["01", "1"])
    report_ids = pd.Series(["01", "1"], dtype="string")

    result = join_caseload(students, report_ids)

    assert result.used_match_key is False
    assert len(result.warnings) == 1
    assert "exact" in result.warnings[0].lower()
    # both still match exactly
    assert result.id_map == {"01": "01", "1": "1"}
    assert result.students["matched"].all()
    assert len(result.unmatched) == 0
    assert result.report_only_count == 0


def test_caseload_only_student_gets_not_found_hint():
    students = make_students(["777", "888"])
    report_ids = pd.Series(["888", "999"], dtype="string")

    result = join_caseload(students, report_ids)

    assert result.used_match_key is True
    assert result.id_map == {"888": "888"}
    assert result.students["matched"].tolist() == [False, True]
    assert result.unmatched["student_id"].tolist() == ["777"]
    assert result.unmatched["hint"].iloc[0] == "not found in the attendance report"
    assert result.unmatched["hint"].dtype == "string"
    assert result.report_only_count == 1


def test_apply_id_map_filters_and_rewrites_ids():
    events = pd.DataFrame(
        {
            "student_id": pd.Series(["900001", "555", "900001"], dtype="string"),
            "code": pd.Series(["A", "P", "T"], dtype="string"),
        }
    )
    out = apply_id_map(events, {"900001": "0900001"})

    assert len(out) == 2
    assert out["student_id"].tolist() == ["0900001", "0900001"]
    assert out["student_id"].dtype == "string"
    assert out["code"].tolist() == ["A", "T"]
    # original frame untouched
    assert events["student_id"].tolist() == ["900001", "555", "900001"]
