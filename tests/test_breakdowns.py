"""Breakdown aggregations and the course-context (ATC-style) supplemental
report: detection, parsing, and dimension tables."""

from __future__ import annotations

import pandas as pd

from attendance_tracker import breakdowns as bd
from attendance_tracker import codes as codes_mod
from attendance_tracker import detection, metrics, normalize, pipeline
from attendance_tracker.constants import Category, Shape
from attendance_tracker.model import ColumnMapping


def _events(rows):
    frame = pd.DataFrame(
        rows, columns=["student_id", "date", "period", "code", "category"]
    )
    frame["student_id"] = frame["student_id"].astype("string")
    frame["date"] = pd.to_datetime(frame["date"])
    frame["period"] = frame["period"].astype("string")
    return frame


def test_by_weekday_and_by_period_hand_checked():
    unexc = Category.ABSENT_UNEXCUSED.value
    tardy = Category.TARDY.value
    events = _events(
        [
            ("1", "2025-09-08", "1", "A", unexc),  # Monday absent (1 of 1)
            ("1", "2025-09-09", "1", "T", tardy),  # Tuesday tardy
            ("2", "2025-09-08", "5", "A", unexc),
            ("2", "2025-09-09", "5", "A", unexc),
        ]
    )
    day_status = metrics.build_day_status(events)
    weekday = bd.by_weekday(day_status).set_index("weekday")
    assert int(weekday.loc[0, "enrolled_days"]) == 2  # two student-Mondays
    assert int(weekday.loc[0, "absent_days"]) == 2
    assert weekday.loc[1, "absence_rate"] == 0.5  # student 2 absent Tuesday
    assert int(weekday.loc[1, "tardy_days"]) == 1

    period = bd.by_period(events).set_index("period")
    assert int(period.loc["5", "unexcused"]) == 2
    assert int(period.loc["5", "students"]) == 1
    assert int(period.loc["1", "tardies"]) == 1


def test_by_attribute_merges_and_totals():
    metrics_frame = pd.DataFrame(
        {
            "student_id": pd.array(["1", "2", "3"], dtype="string"),
            "matched": [True, True, True],
            "grade": pd.array(["09", "09", "10"], dtype="string"),
            "group": pd.array([pd.NA] * 3, dtype="string"),
            "attendance_rate": [0.9, 0.8, 1.0],
            "absence_pct": [10.0, 20.0, 0.0],
            "days_absent": pd.array([9, 18, 0], dtype="Int64"),
            "days_tardy": pd.array([1, 2, 0], dtype="Int64"),
            "tier": pd.array(["chronic", "severe", "satisfactory"], dtype="string"),
        }
    )
    attributes = pd.DataFrame(
        {
            "student_id": pd.array(["1", "2", "3"], dtype="string"),
            "ethnicity": pd.array(["Hispanic", "White", "Hispanic"], dtype="string"),
        }
    )
    table = bd.by_attribute(metrics_frame, attributes, "ethnicity")
    hispanic = table.set_index("ethnicity").loc["Hispanic"]
    assert int(hispanic["n_students"]) == 2
    assert int(hispanic["total_absent_days"]) == 9
    assert int(hispanic["total_tardies"]) == 1
    assert bd.dimension_columns(
        bd.student_attributes(
            attributes.assign(matched=True, grade=pd.NA, group=pd.NA), None
        )
    ) == ["ethnicity"]


def test_student_attributes_fill_from_events(small_dataset, as_xlsx_bytes):
    report_bytes = as_xlsx_bytes(small_dataset["report_atp201"])
    frame, result = detection.detect_report(report_bytes, "report.xlsx")
    assert result.mapping.get("ethnicity") == "Ethnicity"
    assert result.mapping.get("gender") == "Gender"
    code_map = codes_mod.propose_code_map(result.observed_codes)
    events, _ = normalize.build_events_wide(
        frame, ColumnMapping(shape=result.shape, columns=result.mapping), code_map
    )
    students = pd.DataFrame(
        {
            "student_id": events["student_id"].drop_duplicates().astype("string"),
            "matched": True,
        }
    )
    attributes = bd.student_attributes(students, events)
    assert "ethnicity" in attributes.columns
    assert attributes["ethnicity"].notna().all()
    assert attributes["ethnicity"].nunique() >= 2


def test_course_context_detection_and_marks(small_dataset, as_csv_bytes):
    data = as_csv_bytes(small_dataset["report_course_context"])
    frame, result = detection.detect_course_context(data, "courses.csv")
    assert result.confidence == "high"
    assert result.mapping["student_id"] == "Student ID"
    assert result.mapping["course"] == "Course Title"
    assert result.mapping["teacher"] == "Teacher Name"
    assert result.mapping["counselor"] == "Counselor Name"
    assert set(result.observed_codes) == {"UNV", "ILL", "UTY", "ACT"}

    marks, warnings = normalize.build_course_marks(
        frame, ColumnMapping(shape=Shape.UNKNOWN, columns=result.mapping)
    )
    # ACT is present-like even though its header says (Excused).
    act = marks[marks["code"] == "ACT"]
    assert act.empty or (act["category"] == Category.OTHER_PRESENT.value).all()
    # Totals must match the simulator's raw period events.
    truth = small_dataset["period_events"]
    assert (
        int(marks.loc[marks["code"] == "UNV", "count"].sum())
        == int((truth["code"] == "A").sum())
    )
    assert (
        int(marks.loc[marks["code"] == "UTY", "count"].sum())
        == int((truth["code"] == "T").sum())
    )


def test_end_to_end_with_course_context(small_dataset, as_csv_bytes, as_xlsx_bytes):
    report_frame, report_result = detection.detect_report(
        as_xlsx_bytes(small_dataset["report_atp201"]), "report.xlsx"
    )
    caseload_frame, caseload_result = detection.detect_caseload(
        as_xlsx_bytes(small_dataset["caseload_template"]), "caseload.xlsx"
    )
    course_frame, course_result = detection.detect_course_context(
        as_csv_bytes(small_dataset["report_course_context"]), "courses.csv"
    )
    bundle, warnings = pipeline.assemble_bundle(
        report_frame=report_frame,
        report_mapping=ColumnMapping(
            shape=report_result.shape, columns=report_result.mapping
        ),
        caseload_frame=caseload_frame,
        caseload_mapping=ColumnMapping(
            shape=Shape.UNKNOWN, columns=caseload_result.mapping
        ),
        code_map=codes_mod.propose_code_map(report_result.observed_codes),
        enrolled_override=len(small_dataset["calendar"]),
        course_frame=course_frame,
        course_mapping=ColumnMapping(
            shape=Shape.UNKNOWN, columns=course_result.mapping
        ),
    )
    assert bundle.course_marks is not None and not bundle.course_marks.empty
    # Filtered to caseload students only.
    caseload_ids = set(bundle.students["student_id"])
    assert set(bundle.course_marks["student_id"]) <= caseload_ids

    by_teacher = bd.course_breakdown(bundle.course_marks, "teacher")
    roster = small_dataset["roster"]
    truth = small_dataset["period_events"]
    caseload_truth = truth[
        truth["student_id"].isin(roster[roster["on_caseload"]]["student_id"])
    ]
    assert int(by_teacher["absences"].sum()) == int(
        caseload_truth["code"].isin(["A", "E"]).sum()
    )
    # Ethnicity flows from the ATP201 report into the dimensions.
    attributes = bd.student_attributes(bundle.students, bundle.events)
    assert "ethnicity" in bd.dimension_columns(attributes)
