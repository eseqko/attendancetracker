"""Column-role inference and report-shape detection (pure pandas/numpy).

Name evidence (header synonyms from constants.ROLE_SYNONYMS) is combined with
value evidence sampled from each column; the result is always surfaced to the
user for confirmation via model.DetectionResult.
"""

from __future__ import annotations

import re

import pandas as pd

from .constants import REQUIRED_ROLES, ROLE_SYNONYMS, SUMMARY_VALUE_ROLES, Shape
from .io_utils import load_table, looks_like_date
from .model import DetectionResult

#: All roles a schoolwide attendance report might map.
REPORT_ROLES = [
    "student_id", "name", "first_name", "last_name", "grade", "date", "code",
    "period", "days_enrolled", "days_absent", "days_excused", "days_unexcused",
    "days_tardy", "attendance_pct",
]

#: Roles a caseload upload might map.
CASELOAD_ROLES = ["student_id", "name", "first_name", "last_name", "grade"]

#: Roles whose values must be predominantly numeric, else the name-evidence
#: claim is dropped.
_NUMERIC_ROLES = frozenset(SUMMARY_VALUE_ROLES)

_VALUE_SAMPLE_ROWS = 500
_EXACT_SCORE = 100
_PHRASE_SCORE = 50

_HEADER_STRIP_RE = re.compile(r"[^a-z0-9%]+")
_PERIOD_VALUE_RE = re.compile(r"(?:P|PER|PD)?\s*0*([1-9]\d?)(?:\.0)?")
_ID_VALUE_RE = re.compile(r"\d+(?:\.0)?")

_CONFIDENCE_DOWNGRADE = {"high": "medium", "medium": "low", "low": "low"}


# ---------------------------------------------------------------------------
# Name evidence
# ---------------------------------------------------------------------------


def _normalize_header(text: str) -> str:
    """Lowercase, punctuation -> spaces ('%' kept as a token), collapsed."""
    lowered = str(text).lower().replace("%", " % ")
    return " ".join(_HEADER_STRIP_RE.sub(" ", lowered).split())


def _tokens_match(header_token: str, synonym_token: str) -> bool:
    return header_token == synonym_token or header_token == synonym_token + "s"


def _name_score(header_norm: str, synonym: str) -> int:
    """Score a header/synonym pair: exact beats containment, longer synonyms
    beat shorter ones (so 'Student ID' maps to student_id, not name)."""
    synonym_norm = _normalize_header(synonym)
    header_tokens = header_norm.split()
    synonym_tokens = synonym_norm.split()
    if not header_tokens or not synonym_tokens:
        return 0
    width = len(synonym_tokens)
    if len(header_tokens) == width and all(
        _tokens_match(h, s) for h, s in zip(header_tokens, synonym_tokens)
    ):
        return _EXACT_SCORE + len(synonym_norm)
    for start in range(len(header_tokens) - width + 1):
        window = header_tokens[start : start + width]
        if all(_tokens_match(h, s) for h, s in zip(window, synonym_tokens)):
            return _PHRASE_SCORE + len(synonym_norm)
    return 0


def _name_evidence(header_norm: str, synonyms: list[str]) -> tuple[int, int, int] | None:
    """Best (tier, synonym_index, length) for a header against one role's
    synonym list, or None when nothing matches.

    Tier 2 = exact match, 1 = whole-word-phrase containment. When several
    columns exact-match the same role, the SYNONYM LIST ORDER decides which
    column wins — the lists in constants.ROLE_SYNONYMS are preference-ordered,
    e.g. a caseload with 'Perm ID', 'State ID', and 'Ed-Fi ID' columns maps
    student_id to 'Perm ID' (the SIS-local ID attendance reports use).
    """
    best: tuple[int, int, int] | None = None
    for index, synonym in enumerate(synonyms):
        score = _name_score(header_norm, synonym)
        if not score:
            continue
        if score >= _EXACT_SCORE:
            tier, length = 2, score - _EXACT_SCORE
        else:
            tier, length = 1, score - _PHRASE_SCORE
        candidate = (tier, -index, length)
        if best is None or candidate > best:
            best = candidate
    if best is None:
        return None
    tier, negative_index, length = best
    return tier, -negative_index, length


# ---------------------------------------------------------------------------
# Value evidence
# ---------------------------------------------------------------------------


def _sample(series: pd.Series) -> pd.Series:
    """Up to 500 non-null values from a column, in file order."""
    return series.dropna().head(_VALUE_SAMPLE_ROWS)


def _date_fraction(sample: pd.Series) -> float:
    if sample.empty:
        return 0.0
    if pd.api.types.is_datetime64_any_dtype(sample):
        return 1.0
    hits = sum(1 for value in sample if looks_like_date(value))
    return hits / len(sample)


def _numeric_fraction(sample: pd.Series) -> float:
    if sample.empty or pd.api.types.is_datetime64_any_dtype(sample):
        return 0.0
    converted = pd.to_numeric(sample, errors="coerce")
    return float(converted.notna().mean())


def _date_like(sample: pd.Series) -> bool:
    return _date_fraction(sample) >= 0.9


def _code_like(sample: pd.Series) -> bool:
    """Short alphanumerics (len <= 4) with few distinct values."""
    if sample.empty or pd.api.types.is_datetime64_any_dtype(sample):
        return False
    text = sample.astype(str).str.strip()
    text = text[text != ""]
    if text.empty or (text.str.len() <= 4).mean() < 0.95:
        return False
    return text.nunique() <= 40


def _period_like(sample: pd.Series) -> bool:
    """Integers 1..15 (or 'P1'-style) with at most 15 distinct values."""
    if sample.empty or pd.api.types.is_datetime64_any_dtype(sample):
        return False
    text = sample.astype(str).str.strip().str.upper()
    if text.nunique() > 15:
        return False
    for value in text.unique():
        match = _PERIOD_VALUE_RE.fullmatch(value)
        if match is None or not 1 <= int(match.group(1)) <= 15:
            return False
    return True


def _pct_like(sample: pd.Series) -> bool:
    if sample.empty:
        return False
    converted = pd.to_numeric(sample, errors="coerce").dropna()
    if len(converted) < 0.9 * len(sample) or converted.empty:
        return False
    return float(converted.min()) >= 0 and float(converted.max()) <= 100


def _id_like(sample: pd.Series) -> bool:
    """High-cardinality digit strings/ints (one row per student)."""
    if len(sample) < 10 or pd.api.types.is_datetime64_any_dtype(sample):
        return False
    text = sample.astype(str).str.strip()
    if text.str.fullmatch(_ID_VALUE_RE).mean() < 0.9:
        return False
    return text.nunique() >= 0.9 * len(text)


# ---------------------------------------------------------------------------
# Role inference
# ---------------------------------------------------------------------------


def infer_roles(frame: pd.DataFrame, roles: list[str]) -> dict[str, str]:
    """Best column per role; each column is assigned to at most one role.

    Name evidence is resolved greedily by descending score; value evidence
    then denies contradicted claims (a 'date' column that never parses as
    dates, a numeric role that is not numeric) and fills date/code/student_id
    when the header gave nothing away and exactly one column fits.
    """
    columns = list(frame.columns)
    candidates: list[tuple[int, int, int, int, int, str, object]] = []
    for role_index, role in enumerate(roles):
        synonyms = ROLE_SYNONYMS.get(role, [])
        for column_index, column in enumerate(columns):
            header_norm = _normalize_header(str(column))
            evidence = _name_evidence(header_norm, synonyms)
            if evidence is not None:
                tier, synonym_index, length = evidence
                candidates.append(
                    (tier, synonym_index, length, role_index, column_index, role, column)
                )
    # Higher tier first; within a tier, earlier (preferred) synonym first,
    # then longer (more specific) synonym, then role/column order.
    candidates.sort(key=lambda entry: (-entry[0], entry[1], -entry[2], entry[3], entry[4]))

    mapping: dict[str, object] = {}
    used: set[object] = set()
    for _, _, _, _, _, role, column in candidates:
        if role in mapping or column in used:
            continue
        mapping[role] = column
        used.add(column)

    samples = {column: _sample(frame[column]) for column in columns}

    # Deny name-evidence claims that the values contradict.
    for role, column in list(mapping.items()):
        sample = samples[column]
        contradicted = (role == "date" and _date_fraction(sample) < 0.5) or (
            role in _NUMERIC_ROLES and _numeric_fraction(sample) < 0.5
        )
        if contradicted:
            del mapping[role]
            used.discard(column)

    # Fill weakly-named columns from value evidence, only when unambiguous.
    fillers = (("date", _date_like), ("code", _code_like), ("student_id", _id_like))
    for role, matcher in fillers:
        if role not in roles or role in mapping:
            continue
        matches = [c for c in columns if c not in used and matcher(samples[c])]
        if len(matches) == 1:
            mapping[role] = matches[0]
            used.add(matches[0])

    return {role: str(column) for role, column in mapping.items()}


def observed_code_counts(series: pd.Series) -> dict[str, int]:
    """Counts of the distinct codes in a column, upper-cased and stripped."""
    cleaned = series.dropna().astype(str).str.strip().str.upper()
    cleaned = cleaned[cleaned != ""]
    return {str(code): int(count) for code, count in cleaned.value_counts().items()}


# ---------------------------------------------------------------------------
# Shape detection
# ---------------------------------------------------------------------------


_PERIOD_WIDE_HEADER_RE = re.compile(r"^period (\d{1,2})$")


def period_wide_columns(frame: pd.DataFrame) -> list[str]:
    """Columns named 'Period N' (any case/punctuation), in period order.

    Two or more of these alongside a date column mark the wide period layout
    (e.g. Synergy ATP201): one row per student per day, one column per period,
    each cell a code word or blank.
    """
    found: list[tuple[int, str]] = []
    for column in frame.columns:
        match = _PERIOD_WIDE_HEADER_RE.match(_normalize_header(str(column)))
        if match:
            found.append((int(match.group(1)), str(column)))
    return [column for _, column in sorted(found)]


def _find_period_column(frame: pd.DataFrame, mapping: dict[str, str]) -> str | None:
    """Unmapped period-like column that best explains duplicate student-date
    rows (lowest residual duplicate rate once included)."""
    mapped = set(mapping.values())
    key = [mapping["student_id"], mapping["date"]]
    best: str | None = None
    best_dup_rate = float("inf")
    for column in frame.columns:
        if column in mapped or not _period_like(_sample(frame[column])):
            continue
        dup_rate = float(frame.duplicated(subset=key + [column]).mean())
        if dup_rate < best_dup_rate:
            best, best_dup_rate = column, dup_rate
    return best


def detect_shape(
    frame: pd.DataFrame, mapping: dict[str, str]
) -> tuple[Shape, str, list[str]]:
    """Classify the report layout from the mapped roles and the data.

    May add a value-detected 'period' role to ``mapping``. Sanity problems
    downgrade confidence with a warning — never silently.
    """
    warnings: list[str] = []
    id_col = mapping.get("student_id")
    date_col = mapping.get("date")
    code_col = mapping.get("code")

    wide_columns = period_wide_columns(frame)
    if date_col is not None and len(wide_columns) >= 2:
        # Wide period layout (ATP201-style). The codes live in the period
        # columns, so name-matched 'period'/'code' roles are false positives
        # here (e.g. 'ZIP Code 5' phrase-matching the code role) — drop them.
        mapping.pop("period", None)
        mapping.pop("code", None)
        confidence = "high"
        for role in REQUIRED_ROLES[Shape.PERIOD_WIDE]:
            if role not in mapping:
                warnings.append(f"No column could be found for '{role}'.")
                confidence = "low"
        return Shape.PERIOD_WIDE, confidence, warnings

    if date_col is not None and code_col is not None:
        shape, confidence = Shape.DAILY, "high"
        if "period" in mapping:
            shape = Shape.PERIOD
        elif id_col is not None and frame.duplicated(subset=[id_col, date_col]).any():
            period_col = _find_period_column(frame, mapping)
            if period_col is not None:
                mapping["period"] = period_col
                shape, confidence = Shape.PERIOD, "medium"
                warnings.append(
                    f"Column '{period_col}' looks like a class period; "
                    "treating the report as period-level."
                )
            else:
                confidence = "low"
                warnings.append(
                    "Multiple rows share the same student and date but no "
                    "period column was found; treating the report as daily."
                )
        for role in REQUIRED_ROLES[shape]:
            if role not in mapping:
                warnings.append(f"No column could be found for '{role}'.")
                confidence = "low"
        if id_col is not None:
            n_students = int(frame[id_col].nunique())
            if n_students and len(frame) < 3 * n_students:
                warnings.append(
                    "A daily/period report should have many rows per student, "
                    "but this file has fewer than 3 rows per student."
                )
                confidence = _CONFIDENCE_DOWNGRADE[confidence]
        return shape, confidence, warnings

    if date_col is None and id_col is not None:
        n_students = int(frame[id_col].nunique())
        one_row_per_student = (
            n_students > 0 and abs(len(frame) - n_students) <= 0.1 * n_students
        )
        has_value_role = any(role in mapping for role in SUMMARY_VALUE_ROLES)
        if one_row_per_student and has_value_role:
            return Shape.SUMMARY, "high", warnings
        if has_value_role and not one_row_per_student:
            warnings.append(
                "Summary-style columns were found but the file does not have "
                "one row per student."
            )

    warnings.append("Could not determine the report layout from its columns.")
    return Shape.UNKNOWN, "low", warnings


# ---------------------------------------------------------------------------
# Full pipelines
# ---------------------------------------------------------------------------


def detect_report(
    data: bytes,
    filename: str,
    sheet: str | None = None,
    header_row: int | None = None,
) -> tuple[pd.DataFrame, DetectionResult]:
    """Load a schoolwide report and detect its header, columns, and shape."""
    frame, used_header_row = load_table(
        data, filename, sheet=sheet, header_row=header_row
    )
    mapping = infer_roles(frame, REPORT_ROLES)
    shape, confidence, warnings = detect_shape(frame, mapping)
    observed_codes: dict[str, int] = {}
    if shape in (Shape.DAILY, Shape.PERIOD) and "code" in mapping:
        observed_codes = observed_code_counts(frame[mapping["code"]])
    elif shape == Shape.PERIOD_WIDE:
        for column in period_wide_columns(frame):
            for code, count in observed_code_counts(frame[column]).items():
                observed_codes[code] = observed_codes.get(code, 0) + count
    result = DetectionResult(
        shape=shape,
        confidence=confidence,
        header_row=used_header_row,
        mapping=mapping,
        warnings=warnings,
        observed_codes=observed_codes,
    )
    return frame, result


def detect_caseload(
    data: bytes,
    filename: str,
    sheet: str | None = None,
    header_row: int | None = None,
) -> tuple[pd.DataFrame, DetectionResult]:
    """Load a caseload file and detect its header and student columns."""
    frame, used_header_row = load_table(
        data, filename, sheet=sheet, header_row=header_row
    )
    mapping = infer_roles(frame, CASELOAD_ROLES)
    warnings: list[str] = []
    if "student_id" in mapping:
        confidence = "high"
    else:
        confidence = "low"
        warnings.append(
            "No student ID column could be found in the caseload file."
        )
    result = DetectionResult(
        shape=Shape.UNKNOWN,  # not applicable to caseload files
        confidence=confidence,
        header_row=used_header_row,
        mapping=mapping,
        warnings=warnings,
        observed_codes={},
    )
    return frame, result
