"""The district caseload template (Synergy QRY801-style) must work end-to-end.

Header row: Student Name | Perm ID | Ed-Fi ID | State ID | Legal Last Name |
Legal First Name | Grade. 'Perm ID' is the ID that must drive matching — never
Ed-Fi or State ID. Fixtures are synthetic (sample_data); no real exports
involved.
"""

from __future__ import annotations

import io

import pandas as pd

from attendance_tracker import codes as codes_mod
from attendance_tracker import detection, pipeline, sample_data
from attendance_tracker.constants import Shape
from attendance_tracker.model import ColumnMapping


def _template_xlsx_bytes(frame: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    frame.to_excel(
        buffer, index=False, sheet_name=sample_data.CASELOAD_TEMPLATE_SHEET
    )
    return buffer.getvalue()


def test_template_columns_are_the_documented_ones(small_dataset):
    template = small_dataset["caseload_template"]
    assert list(template.columns) == sample_data.CASELOAD_TEMPLATE_COLUMNS


def test_template_detection_maps_perm_id_not_state_or_edfi(small_dataset):
    data = _template_xlsx_bytes(small_dataset["caseload_template"])
    frame, result = detection.detect_caseload(data, "Caseload_template.XLSX")
    assert result.mapping["student_id"] == "Perm ID"
    assert result.mapping["name"] == "Student Name"
    assert result.mapping["last_name"] == "Legal Last Name"
    assert result.mapping["first_name"] == "Legal First Name"
    assert result.mapping["grade"] == "Grade"
    assert result.confidence == "high"


def test_template_header_only_file_detects_header_row(small_dataset):
    # The blank template (header row, zero students) must still map correctly.
    empty = small_dataset["caseload_template"].iloc[0:0]
    data = _template_xlsx_bytes(empty)
    _, result = detection.detect_caseload(data, "Caseload_template.XLSX")
    assert result.header_row == 0
    assert result.mapping["student_id"] == "Perm ID"


def test_template_end_to_end_matches_on_perm_id(small_dataset, as_csv_bytes):
    caseload_bytes = _template_xlsx_bytes(small_dataset["caseload_template"])
    cl_frame, cl_result = detection.detect_caseload(
        caseload_bytes, "Caseload_template.XLSX"
    )
    report_bytes = as_csv_bytes(small_dataset["report_daily"])
    report_frame, report_result = detection.detect_report(report_bytes, "report.csv")

    bundle, _ = pipeline.assemble_bundle(
        report_frame=report_frame,
        report_mapping=ColumnMapping(
            shape=report_result.shape, columns=report_result.mapping
        ),
        caseload_frame=cl_frame,
        caseload_mapping=ColumnMapping(shape=Shape.UNKNOWN, columns=cl_result.mapping),
        code_map=codes_mod.propose_code_map(report_result.observed_codes),
    )
    roster = small_dataset["roster"]
    n_caseload = int(roster["on_caseload"].sum())
    assert len(bundle.metrics) == n_caseload
    assert bundle.metrics["matched"].all()
    assert bundle.unmatched.empty
    # Matching keyed on Perm ID values (the roster's student_id), and the
    # unmapped Ed-Fi / State ID columns survive as extra group-by columns.
    assert set(bundle.metrics["student_id"]) == set(
        roster[roster["on_caseload"]]["student_id"]
    )
    assert "Ed-Fi ID" in bundle.students.columns
    assert "State ID" in bundle.students.columns
    # Grade came through for every student (powers by-grade cohorts).
    assert bundle.metrics["grade"].notna().all()
