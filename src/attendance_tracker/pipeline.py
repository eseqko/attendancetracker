"""Assemble a DataBundle from confirmed uploads — the seam between UI and core.

The UI collects raw frames plus user-confirmed mappings; this module runs the
full normalize -> baseline -> join -> metrics pipeline in one call so the whole
flow is testable end-to-end without Streamlit.
"""

from __future__ import annotations

import pandas as pd

from . import cohorts, joining, metrics, normalize
from .constants import DEFAULT_ABSENT_DAY_THRESHOLD, SHAPE_CAPABILITIES, Shape
from .model import CodeMap, ColumnMapping, DataBundle


def assemble_bundle(
    report_frame: pd.DataFrame,
    report_mapping: ColumnMapping,
    caseload_frame: pd.DataFrame | None = None,
    caseload_mapping: ColumnMapping | None = None,
    code_map: CodeMap | None = None,
    force_exact: bool = False,
    absent_day_threshold: float = DEFAULT_ABSENT_DAY_THRESHOLD,
    enrolled_override: int | None = None,
    prebuilt_students: pd.DataFrame | None = None,
) -> tuple[DataBundle, list[str]]:
    """Build the complete DataBundle. Returns (bundle, warnings).

    Pass either a raw caseload frame + mapping, or an already-canonical
    students frame via prebuilt_students (the setup wizard builds it early so
    its warnings surface in section 1).

    The schoolwide report is parsed in full so the baseline reflects the whole
    school; non-caseload rows are dropped right after the baseline is computed.
    """
    warnings: list[str] = []

    if prebuilt_students is not None:
        students = prebuilt_students
    else:
        if caseload_frame is None or caseload_mapping is None:
            raise ValueError(
                "either prebuilt_students or caseload_frame + caseload_mapping "
                "is required"
            )
        students, w = normalize.build_students(caseload_frame, caseload_mapping)
        warnings.extend(w)

    shape = report_mapping.shape
    if shape == Shape.SUMMARY:
        all_summary, w = normalize.build_summary(report_frame, report_mapping)
        warnings.extend(w)
        baseline = cohorts.baseline_from_summary(all_summary)
        join = joining.join_caseload(
            students, all_summary["student_id"], force_exact=force_exact
        )
        warnings.extend(join.warnings)
        summary = joining.apply_id_map(all_summary, join.id_map)
        metrics_frame = metrics.metrics_from_summary(summary, join.students)
        bundle = DataBundle(
            students=join.students,
            metrics=metrics_frame,
            baseline=baseline,
            unmatched=join.unmatched,
            capabilities=SHAPE_CAPABILITIES[shape],
            summary=summary,
            code_map=code_map,
        )
        return bundle, warnings

    if code_map is None:
        raise ValueError("code_map is required for day/period-level reports")

    all_events, w = normalize.build_events(report_frame, report_mapping, code_map)
    warnings.extend(w)
    if metrics.is_exception_report(all_events) and enrolled_override is None:
        warnings.append(
            "This looks like an absences-only export (almost no present rows); "
            "attendance rates need a total-school-days value to be meaningful."
        )
    baseline = cohorts.baseline_from_events(
        all_events,
        absent_day_threshold=absent_day_threshold,
        enrolled_override=enrolled_override,
    )
    join = joining.join_caseload(
        students, all_events["student_id"], force_exact=force_exact
    )
    warnings.extend(join.warnings)
    events = joining.apply_id_map(all_events, join.id_map)
    day_status = metrics.build_day_status(events, absent_day_threshold)
    metrics_frame = metrics.metrics_from_events(
        events,
        join.students,
        absent_day_threshold=absent_day_threshold,
        enrolled_override=enrolled_override,
    )
    bundle = DataBundle(
        students=join.students,
        metrics=metrics_frame,
        baseline=baseline,
        unmatched=join.unmatched,
        capabilities=SHAPE_CAPABILITIES[shape],
        events=events,
        day_status=day_status,
        code_map=code_map,
    )
    return bundle, warnings
