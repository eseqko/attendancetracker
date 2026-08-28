"""Local persistence: save/load/clear round-trips, corruption tolerance, and
the no-student-data-in-JSON guarantee."""

from __future__ import annotations

import json

import pytest

from attendance_tracker import codes as codes_mod
from attendance_tracker import detection, pipeline, storage
from attendance_tracker.constants import Shape
from attendance_tracker.model import ColumnMapping


def _sample_inputs(dataset, as_xlsx_bytes, as_csv_bytes):
    caseload_bytes = as_xlsx_bytes(dataset["caseload_template"])
    report_bytes = as_xlsx_bytes(dataset["report_atp201"])
    course_bytes = as_csv_bytes(dataset["report_course_context"])
    _, cl_result = detection.detect_caseload(caseload_bytes, "caseload.xlsx")
    _, rp_result = detection.detect_report(report_bytes, "report.xlsx")
    _, co_result = detection.detect_course_context(course_bytes, "courses.csv")
    return {
        "files": {
            "caseload": (caseload_bytes, "caseload.xlsx"),
            "report": (report_bytes, "report.xlsx"),
            "course": (course_bytes, "courses.csv"),
        },
        "caseload_mapping": ColumnMapping(
            shape=Shape.UNKNOWN, columns=cl_result.mapping
        ),
        "report_mapping": ColumnMapping(
            shape=rp_result.shape, columns=rp_result.mapping
        ),
        "course_mapping": ColumnMapping(
            shape=Shape.UNKNOWN, columns=co_result.mapping
        ),
        "code_map": codes_mod.propose_code_map(rp_result.observed_codes),
        "settings": {
            "ignore_zeros": True,
            "assume_perfect": True,
            "enrolled_override": 40,
            "threshold": 0.5,
        },
    }


def test_round_trip(tmp_path, small_dataset, as_xlsx_bytes, as_csv_bytes):
    inputs = _sample_inputs(small_dataset, as_xlsx_bytes, as_csv_bytes)
    storage.save_profile(tmp_path, **inputs)
    profile = storage.load_profile(tmp_path)
    assert profile is not None
    for slot, (blob, name) in inputs["files"].items():
        assert profile.files[slot] == (blob, name)
    assert profile.caseload_mapping.columns == inputs["caseload_mapping"].columns
    assert profile.report_mapping.shape == Shape.PERIOD_WIDE
    assert profile.report_mapping.columns == inputs["report_mapping"].columns
    assert profile.course_mapping.columns == inputs["course_mapping"].columns
    assert profile.code_map.codes == inputs["code_map"].codes
    assert profile.settings == inputs["settings"]
    assert profile.saved_on  # a date string


def test_profile_json_contains_no_student_data(
    tmp_path, small_dataset, as_xlsx_bytes, as_csv_bytes
):
    inputs = _sample_inputs(small_dataset, as_xlsx_bytes, as_csv_bytes)
    storage.save_profile(tmp_path, **inputs)
    text = (tmp_path / storage.PROFILE_FILENAME).read_text()
    roster = small_dataset["roster"]
    for student_id in roster["student_id"]:
        assert str(student_id) not in text
    for last_name in roster["last_name"].unique():
        assert str(last_name) not in text


def test_missing_corrupt_and_version_mismatch(tmp_path):
    assert storage.load_profile(tmp_path) is None
    assert not storage.has_profile(tmp_path)

    (tmp_path / storage.PROFILE_FILENAME).write_text("{not json")
    assert storage.load_profile(tmp_path) is None

    (tmp_path / storage.PROFILE_FILENAME).write_text(
        json.dumps({"version": 999, "files": {}})
    )
    assert storage.has_profile(tmp_path)
    assert storage.load_profile(tmp_path) is None


def test_clear_profile(tmp_path, small_dataset, as_xlsx_bytes, as_csv_bytes):
    inputs = _sample_inputs(small_dataset, as_xlsx_bytes, as_csv_bytes)
    storage.save_profile(tmp_path, **inputs)
    assert storage.has_profile(tmp_path)
    storage.clear_profile(tmp_path)
    assert not storage.has_profile(tmp_path)
    assert list(tmp_path.glob("*.bin")) == []
    # Clearing an already-clear directory is a no-op.
    storage.clear_profile(tmp_path)


def test_ui_prefs_round_trip_and_tolerance(tmp_path):
    assert storage.load_ui_prefs(tmp_path) == {}
    storage.save_ui_prefs({"menu_position": "top"}, tmp_path)
    assert storage.load_ui_prefs(tmp_path) == {"menu_position": "top"}
    (tmp_path / storage.UI_PREFS_FILENAME).write_text("{broken")
    assert storage.load_ui_prefs(tmp_path) == {}
    # Forgetting saved student data must not erase UI preferences.
    storage.save_ui_prefs({"menu_position": "right"}, tmp_path)
    storage.clear_profile(tmp_path)
    assert storage.load_ui_prefs(tmp_path) == {"menu_position": "right"}


def test_restored_profile_assembles_identically(
    tmp_path, small_dataset, as_xlsx_bytes, as_csv_bytes
):
    from attendance_tracker import io_utils, normalize

    inputs = _sample_inputs(small_dataset, as_xlsx_bytes, as_csv_bytes)
    storage.save_profile(tmp_path, **inputs)
    profile = storage.load_profile(tmp_path)

    def assemble(caseload_bytes, report_bytes, course_bytes, mappings, code_map):
        cl_frame, _ = io_utils.load_table(caseload_bytes, "caseload.xlsx")
        students, _ = normalize.build_students(cl_frame, mappings["caseload"])
        rp_frame, _ = io_utils.load_table(report_bytes, "report.xlsx")
        co_frame, _ = io_utils.load_table(course_bytes, "courses.csv")
        return pipeline.assemble_bundle(
            report_frame=rp_frame,
            report_mapping=mappings["report"],
            code_map=code_map,
            enrolled_override=40,
            prebuilt_students=students,
            assume_perfect_attendance=True,
            course_frame=co_frame,
            course_mapping=mappings["course"],
        )[0]

    direct = assemble(
        inputs["files"]["caseload"][0],
        inputs["files"]["report"][0],
        inputs["files"]["course"][0],
        {
            "caseload": inputs["caseload_mapping"],
            "report": inputs["report_mapping"],
            "course": inputs["course_mapping"],
        },
        inputs["code_map"],
    )
    restored = assemble(
        profile.files["caseload"][0],
        profile.files["report"][0],
        profile.files["course"][0],
        {
            "caseload": profile.caseload_mapping,
            "report": profile.report_mapping,
            "course": profile.course_mapping,
        },
        profile.code_map,
    )
    assert direct.metrics.equals(restored.metrics)
    assert direct.capabilities == restored.capabilities
    assert direct.course_marks.equals(restored.course_marks)
