"""Tests for io_utils: format sniffing, encodings, and header-row detection."""

from __future__ import annotations

from attendance_tracker import io_utils, sample_data

CASELOAD_COLUMNS = [
    "Student ID", "Last Name", "First Name", "Grade", "Case Manager", "Program",
]
DAILY_COLUMNS = ["Student ID", "Student Name", "Grade", "Date", "Attendance Code"]


def test_is_excel_by_extension():
    assert io_utils.is_excel("report.xlsx")
    assert io_utils.is_excel("REPORT.XLSM")
    assert io_utils.is_excel("legacy.xls")
    assert not io_utils.is_excel("report.csv")
    assert not io_utils.is_excel("report.txt")


def test_list_sheets(small_dataset, as_csv_bytes, as_xlsx_bytes):
    caseload = small_dataset["caseload"]
    assert io_utils.list_sheets(as_csv_bytes(caseload), "caseload.csv") == []
    assert io_utils.list_sheets(as_xlsx_bytes(caseload), "caseload.xlsx") == [
        "Sheet1"
    ]


def test_clean_caseload_header_row_zero_csv(small_dataset, as_csv_bytes):
    caseload = small_dataset["caseload"]
    frame, header_row = io_utils.load_table(as_csv_bytes(caseload), "caseload.csv")
    assert header_row == 0
    assert list(frame.columns) == CASELOAD_COLUMNS
    assert len(frame) == len(caseload)
    assert str(frame.loc[0, "Student ID"]) == str(caseload.loc[0, "Student ID"])


def test_clean_caseload_header_row_zero_xlsx(small_dataset, as_xlsx_bytes):
    caseload = small_dataset["caseload"]
    frame, header_row = io_utils.load_table(as_xlsx_bytes(caseload), "caseload.xlsx")
    assert header_row == 0
    assert list(frame.columns) == CASELOAD_COLUMNS
    assert len(frame) == len(caseload)


def test_clean_daily_header_row_zero(small_dataset, as_csv_bytes, as_xlsx_bytes):
    report = small_dataset["report_daily"]
    for data, name in (
        (as_csv_bytes(report), "daily.csv"),
        (as_xlsx_bytes(report), "daily.xlsx"),
    ):
        frame, header_row = io_utils.load_table(data, name)
        assert header_row == 0
        assert list(frame.columns) == DAILY_COLUMNS
        assert len(frame) == len(report)


def test_preamble_header_detected_csv(small_dataset, as_csv_bytes):
    caseload = small_dataset["caseload"]
    stacked = sample_data.with_preamble(caseload, sample_data.PREAMBLE_LINES)
    data = as_csv_bytes(stacked, header=False)

    raw = io_utils.read_raw(data, "caseload.csv", nrows=40)
    assert io_utils.detect_header_row(raw) == 3

    frame, header_row = io_utils.load_table(data, "caseload.csv")
    assert header_row == 3
    assert list(frame.columns) == CASELOAD_COLUMNS
    assert len(frame) == len(caseload)
    assert str(frame.loc[0, "Student ID"]) == str(caseload.loc[0, "Student ID"])


def test_preamble_header_detected_xlsx(small_dataset, as_xlsx_bytes):
    caseload = small_dataset["caseload"]
    stacked = sample_data.with_preamble(caseload, sample_data.PREAMBLE_LINES)
    data = as_xlsx_bytes(stacked, header=False)

    raw = io_utils.read_raw(data, "caseload.xlsx", nrows=40)
    assert io_utils.detect_header_row(raw) == 3

    frame, header_row = io_utils.load_table(data, "caseload.xlsx")
    assert header_row == 3
    assert list(frame.columns) == CASELOAD_COLUMNS
    assert len(frame) == len(caseload)


def test_title_and_blank_row_inline():
    text = (
        "Weekly Attendance Export\n"
        "\n"
        "Student ID,Date,Code\n"
        "900001,09/08/2025,P\n"
        "900002,09/08/2025,A\n"
    )
    data = text.encode("utf-8")

    raw = io_utils.read_raw(data, "export.csv")
    assert io_utils.detect_header_row(raw) == 2

    frame, header_row = io_utils.load_table(data, "export.csv")
    assert header_row == 2
    assert list(frame.columns) == ["Student ID", "Date", "Code"]
    assert len(frame) == 2
    assert list(frame["Code"]) == ["P", "A"]


def test_semicolon_delimiter_sniffed():
    text = (
        "Student ID;Last Name;First Name;Grade\n"
        "900001;Testperson;Aaliyah;06\n"
        "900002;Example;Bruno;07\n"
        "900003;Sampleton;Carmen;08\n"
    )
    frame, header_row = io_utils.load_table(text.encode("utf-8"), "roster.csv")
    assert header_row == 0
    assert list(frame.columns) == ["Student ID", "Last Name", "First Name", "Grade"]
    assert len(frame) == 3
    assert list(frame["First Name"]) == ["Aaliyah", "Bruno", "Carmen"]


def test_latin1_encoded_csv_decodes():
    text = "Student ID,Last Name,First Name,Grade\n900001,Muñoz,José,06\n"
    data = text.encode("latin-1")
    frame, header_row = io_utils.load_table(data, "roster.csv")
    assert header_row == 0
    assert frame.loc[0, "First Name"] == "José"
    assert frame.loc[0, "Last Name"] == "Muñoz"
