"""Legacy .xls uploads must parse end to end — Synergy exports ATP201 in the
old Excel format, and the uploader advertises XLS support, so xlrd is a hard
dependency. Fixtures are written with xlwt (pandas can no longer write .xls)."""

from __future__ import annotations

import io

import pytest

from attendance_tracker import detection, io_utils
from attendance_tracker.constants import Shape

xlwt = pytest.importorskip("xlwt")


@pytest.fixture()
def as_xls_bytes():
    def _to_bytes(frame) -> bytes:
        book = xlwt.Workbook()
        sheet = book.add_sheet("Sheet1")
        for col, name in enumerate(frame.columns):
            sheet.write(0, col, str(name))
        for row, (_, values) in enumerate(frame.iterrows(), start=1):
            for col, value in enumerate(values):
                if value is None or (isinstance(value, float) and value != value):
                    continue  # blank cell, like a present period in ATP201
                text = str(value)
                if text:
                    sheet.write(row, col, text)
        buffer = io.BytesIO()
        book.save(buffer)
        return buffer.getvalue()

    return _to_bytes


def test_list_sheets_reads_xls(small_dataset, as_xls_bytes):
    # The exact call that crashed in the field when xlrd was missing.
    data = as_xls_bytes(small_dataset["report_atp201"])
    assert io_utils.list_sheets(data, "report.xls") == ["Sheet1"]


def test_atp201_xls_matches_xlsx_detection(
    small_dataset, as_xls_bytes, as_xlsx_bytes
):
    frame = small_dataset["report_atp201"]
    _, xls_result = detection.detect_report(as_xls_bytes(frame), "report.xls")
    _, xlsx_result = detection.detect_report(as_xlsx_bytes(frame), "report.xlsx")
    assert xls_result.shape == Shape.PERIOD_WIDE
    assert xls_result.mapping == xlsx_result.mapping


def test_load_table_xls_preserves_leading_zeros(as_xls_bytes):
    import pandas as pd

    frame = pd.DataFrame({"Perm ID": ["007123", "900004"], "Grade": ["09", "10"]})
    loaded, header_row = io_utils.load_table(as_xls_bytes(frame), "caseload.xls")
    assert header_row == 0
    assert list(loaded["Perm ID"]) == ["007123", "900004"]
