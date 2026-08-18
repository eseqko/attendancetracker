"""Uploaded-file loading: format and delimiter sniffing, raw reads, and
header-row detection for CSV/Excel exports that often carry title preambles."""

from __future__ import annotations

import csv
import datetime as dt
import io
import re

import pandas as pd

_EXCEL_EXTENSIONS = (".xlsx", ".xlsm", ".xls")
_SNIFF_CHARS = 8192
_SNIFF_DELIMITERS = ",;\t|"
_HEADER_SCAN_ROWS = 40
#: The winning header row must score strictly above this, else row 0 is used.
_HEADER_SCORE_FLOOR = 3

#: Substrings that suggest a cell is a column header, matched against
#: lowercased, punctuation-stripped cell text ('%' is kept).
_HEADER_KEYWORDS = (
    "student", "id", "name", "date", "code", "absen", "tard", "enrol",
    "member", "period", "pct", "%", "att", "grade",
)

_KEYWORD_STRIP_RE = re.compile(r"[^a-z0-9%\s]+")
_DIGIT_RE = re.compile(r"\d")
_DATE_SEPARATOR_RE = re.compile(r"[/\-:]")


def is_excel(filename: str) -> bool:
    """True when the filename has an Excel extension (.xlsx/.xlsm/.xls)."""
    return filename.lower().endswith(_EXCEL_EXTENSIONS)


def list_sheets(data: bytes, filename: str) -> list[str]:
    """Sheet names of an Excel upload; [] for CSV files."""
    if not is_excel(filename):
        return []
    with pd.ExcelFile(io.BytesIO(data)) as book:
        return [str(name) for name in book.sheet_names]


def _decode_csv(data: bytes) -> str:
    """Decode CSV bytes as UTF-8 (BOM tolerated), falling back to latin-1."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _sniff_delimiter(text: str) -> str:
    """Guess the delimiter from the first few KB; comma when unsure."""
    sample = text[:_SNIFF_CHARS]
    try:
        return csv.Sniffer().sniff(sample, delimiters=_SNIFF_DELIMITERS).delimiter
    except csv.Error:
        return ","


def read_raw(
    data: bytes,
    filename: str,
    sheet: str | None = None,
    nrows: int | None = None,
) -> pd.DataFrame:
    """Read a file with no header applied, preserving every physical row.

    CSV rows are parsed with the sniffed delimiter and padded to equal width
    (SIS preambles are often narrower than the data), with blank cells as
    None. Excel reads the requested sheet, or the first one.
    """
    if is_excel(filename):
        return pd.read_excel(
            io.BytesIO(data),
            sheet_name=sheet if sheet is not None else 0,
            header=None,
            nrows=nrows,
        )
    text = _decode_csv(data)
    delimiter = _sniff_delimiter(text)
    rows: list[list[object]] = []
    for index, row in enumerate(csv.reader(io.StringIO(text), delimiter=delimiter)):
        if nrows is not None and index >= nrows:
            break
        rows.append([cell if cell.strip() else None for cell in row])
    return pd.DataFrame(rows)


def looks_like_number(value: object) -> bool:
    """True when a cell value is numeric or parses cleanly as a number."""
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    try:
        float(str(value).strip())
    except ValueError:
        return False
    return True


def looks_like_date(value: object) -> bool:
    """True when a cell value is a date or a string that parses as one.

    Strings must contain a digit and a date separator before parsing is even
    attempted, so bare numbers ("06") and words ("March") never count.
    """
    if isinstance(value, (pd.Timestamp, dt.date, dt.datetime)):
        return True
    text = str(value).strip()
    if not _DIGIT_RE.search(text) or not _DATE_SEPARATOR_RE.search(text):
        return False
    try:
        pd.to_datetime(text)
    except (ValueError, TypeError, OverflowError):
        return False
    return True


def _is_blank(value: object) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return not str(value).strip()


def detect_header_row(raw: pd.DataFrame) -> int:
    """Best-guess 0-based header row within the first 40 raw rows.

    Each row is scored (+2 per cell containing a header keyword, +1 per
    non-null cell that is neither a number nor a date, +1 when all non-null
    cells are unique, -3 when the row has <= 2 non-null cells) and the
    earliest argmax wins. If no row clears a small floor, row 0 is assumed.
    """
    best_row = 0
    best_score = float("-inf")
    for row_index in range(min(len(raw), _HEADER_SCAN_ROWS)):
        cells = [value for value in raw.iloc[row_index] if not _is_blank(value)]
        score = 0
        for value in cells:
            normalized = _KEYWORD_STRIP_RE.sub(" ", str(value).lower())
            if any(keyword in normalized for keyword in _HEADER_KEYWORDS):
                score += 2
            if not looks_like_number(value) and not looks_like_date(value):
                score += 1
        if cells and len({str(value) for value in cells}) == len(cells):
            score += 1
        if len(cells) <= 2:
            score -= 3
        if score > best_score:
            best_row, best_score = row_index, score
    return best_row if best_score > _HEADER_SCORE_FLOOR else 0


def load_table(
    data: bytes,
    filename: str,
    sheet: str | None = None,
    header_row: int | None = None,
) -> tuple[pd.DataFrame, int]:
    """Load a table with the header row detected (or given) and applied.

    Every column is read as text (dtype=str): pandas' type inference would
    otherwise strip leading zeros from student IDs and reformat values the
    detection/normalize layers are built to interpret themselves.

    Fully-empty rows and columns are dropped and column names are stripped
    strings. Returns (frame, header_row_used).
    """
    if header_row is None:
        raw = read_raw(data, filename, sheet=sheet, nrows=_HEADER_SCAN_ROWS)
        header_row = detect_header_row(raw)
    if is_excel(filename):
        frame = pd.read_excel(
            io.BytesIO(data),
            sheet_name=sheet if sheet is not None else 0,
            header=header_row,
            dtype=str,
        )
    else:
        text = _decode_csv(data)
        delimiter = _sniff_delimiter(text)
        frame = pd.read_csv(
            io.StringIO(text),
            sep=delimiter,
            skiprows=header_row,
            header=0,
            skip_blank_lines=False,
            dtype=str,
        )
    frame = frame.dropna(axis=0, how="all").dropna(axis=1, how="all")
    frame.columns = [str(column).strip() for column in frame.columns]
    frame = frame.reset_index(drop=True)
    return frame, header_row
