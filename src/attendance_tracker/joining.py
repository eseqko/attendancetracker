"""Joining the caseload to report-side student IDs and rewriting report keys.

Caseload spreadsheets and SIS exports frequently disagree about leading zeros
in student IDs (Excel strips them; some SIS exports pad them). The default
join therefore uses a zero-stripped match key, falling back to exact-ID
matching whenever zero-stripping would merge distinct IDs on either side.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .normalize import make_match_key


@dataclass
class JoinResult:
    """Outcome of matching the caseload against report-side student IDs."""

    students: pd.DataFrame  # caseload frame + 'matched' (bool) column
    unmatched: pd.DataFrame  # student_id, name, hint — caseload-only students
    id_map: dict[str, str]  # report-side normalized id -> caseload student_id
    used_match_key: bool
    report_only_count: int  # distinct report ids not on the caseload
    warnings: list[str] = field(default_factory=list)


def join_caseload(
    students: pd.DataFrame,
    report_ids: pd.Series,
    force_exact: bool = False,
) -> JoinResult:
    """Match caseload students against the report's student-ID population.

    ``report_ids`` must be an already-normalized "string" series (duplicates
    are deduped internally). Default mode joins on match_key (leading zeros
    stripped) unless zero-stripping creates a collision — two distinct
    caseload IDs or two distinct report IDs sharing one match key — in which
    case it falls back to an exact student_id join with a warning.
    ``force_exact=True`` skips match-key joining entirely (UI toggle).
    """
    warnings: list[str] = []

    report = pd.Series(report_ids, dtype="string").dropna()
    report_unique = report.drop_duplicates().reset_index(drop=True)
    report_keys = make_match_key(report_unique)

    caseload = students.copy()
    caseload_ids = caseload["student_id"].astype("string")
    if "match_key" in caseload.columns:
        caseload_keys = caseload["match_key"].astype("string")
    else:
        caseload_keys = make_match_key(caseload_ids)

    use_match_key = not force_exact
    if use_match_key:
        pairs = pd.DataFrame(
            {"id": caseload_ids, "key": caseload_keys}
        ).drop_duplicates()
        caseload_collision = bool(pairs["key"].duplicated().any())
        report_collision = bool(report_keys.duplicated().any())
        if caseload_collision or report_collision:
            use_match_key = False
            warnings.append(
                "Zero-stripped matching would merge distinct student IDs; "
                "fell back to exact student ID matching."
            )

    id_map: dict[str, str] = {}
    if use_match_key:
        key_to_caseload = dict(zip(caseload_keys.tolist(), caseload_ids.tolist()))
        for report_id, report_key in zip(
            report_unique.tolist(), report_keys.tolist()
        ):
            if report_key in key_to_caseload:
                id_map[report_id] = key_to_caseload[report_key]
        matched_mask = caseload_ids.isin(set(id_map.values()))
    else:
        caseload_set = set(caseload_ids.dropna().tolist())
        id_map = {
            report_id: report_id
            for report_id in report_unique.tolist()
            if report_id in caseload_set
        }
        matched_mask = caseload_ids.isin(set(id_map))

    caseload["matched"] = matched_mask.astype(bool)

    # Hints for caseload-only students.
    key_to_report: dict[str, str] = {}
    for report_id, report_key in zip(report_unique.tolist(), report_keys.tolist()):
        key_to_report.setdefault(report_key, report_id)

    unmatched_rows = caseload.loc[~caseload["matched"]]
    unmatched_keys = caseload_keys.loc[unmatched_rows.index]
    hints: list[str] = []
    for key in unmatched_keys.tolist():
        if not use_match_key and key in key_to_report:
            hints.append(
                f"report has this student as ID {key_to_report[key]} "
                "(leading zeros differ)"
            )
        else:
            hints.append("not found in the attendance report")

    if "name" in unmatched_rows.columns:
        unmatched_names = unmatched_rows["name"].tolist()
    else:
        unmatched_names = [pd.NA] * len(unmatched_rows)
    unmatched = pd.DataFrame(
        {
            "student_id": pd.Series(
                unmatched_rows["student_id"].tolist(), dtype="string"
            ),
            "name": pd.Series(unmatched_names, dtype="string"),
            "hint": pd.Series(hints, dtype="string"),
        }
    )

    return JoinResult(
        students=caseload.reset_index(drop=True),
        unmatched=unmatched,
        id_map=id_map,
        used_match_key=use_match_key,
        report_only_count=int(len(report_unique) - len(id_map)),
        warnings=warnings,
    )


def apply_id_map(frame: pd.DataFrame, id_map: dict[str, str]) -> pd.DataFrame:
    """Filter a normalized events/summary frame to matched report IDs and
    rewrite student_id to the caseload's ID so downstream frames share keys."""
    student_id = frame["student_id"].astype("string")
    keep = student_id.isin(set(id_map))
    out = frame.loc[keep].copy()
    out["student_id"] = student_id.loc[keep].map(id_map).astype("string")
    return out.reset_index(drop=True)
