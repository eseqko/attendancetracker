"""ATP201-style wide period reports: detection, parsing, densification, and
end-to-end metrics — including robustness against the filled demographic and
family-contact columns of a real export. All fixtures are synthetic."""

from __future__ import annotations

import pandas as pd
import pytest

from attendance_tracker import codes as codes_mod
from attendance_tracker import detection, metrics, normalize, pipeline
from attendance_tracker.constants import Capability, Category, Shape
from attendance_tracker.model import CodeMap, ColumnMapping

#: Analysis columns events may carry — ethnicity/gender are deliberate
#: breakdown dimensions; contact/address/birth columns must NEVER survive.
CANONICAL_EVENT_COLUMNS = {
    "student_id", "date", "period", "code", "category", "name", "grade",
    "ethnicity", "gender",
}
BANNED_COLUMN_WORDS = ("birth", "phone", "address", "parent", "zip", "custody")


def _detect(dataset, as_xlsx_bytes):
    data = as_xlsx_bytes(dataset["report_atp201"])
    return detection.detect_report(data, "report_atp201.xlsx")


def test_detection_maps_the_right_columns(small_dataset, as_xlsx_bytes):
    frame, result = _detect(small_dataset, as_xlsx_bytes)
    assert result.shape == Shape.PERIOD_WIDE
    assert result.confidence == "high"
    assert result.mapping["student_id"] == "Sis Number"  # not Phone/ZIP
    assert result.mapping["date"] == "Date"  # not Birth Date
    assert result.mapping["grade"] == "Grade"
    # Periods come from column headers, never from a name-matched role.
    assert "period" not in result.mapping
    assert "code" not in result.mapping
    for code in ("UNVERIFIED", "ILNESS", "UNX.TARDY"):
        assert code in result.observed_codes
    # All observed words have known defaults -> no unknown codes to resolve.
    code_map = codes_mod.propose_code_map(result.observed_codes)
    assert codes_mod.unknown_codes(code_map, result.observed_codes) == []


def test_wide_events_strip_suffixes_and_drop_pii(small_dataset, as_xlsx_bytes):
    frame, result = _detect(small_dataset, as_xlsx_bytes)
    code_map = codes_mod.propose_code_map(result.observed_codes)
    mapping = ColumnMapping(shape=Shape.PERIOD_WIDE, columns=result.mapping)
    events, warnings = normalize.build_events_wide(frame, mapping, code_map)

    # Privacy containment: nothing beyond the canonical columns survives,
    # and contact/demographic-record columns are gone by name.
    assert set(events.columns) <= CANONICAL_EVENT_COLUMNS
    for column in events.columns:
        assert not any(word in column.lower() for word in BANNED_COLUMN_WORDS)
    # '(D2S)'-style suffixes never break date parsing.
    assert events["date"].notna().all()
    truth_dates = set(small_dataset["daily_events"]["date"])
    assert set(events["date"]) <= truth_dates
    assert set(events["period"].dropna()) <= {str(p) for p in range(1, 8)}
    assert set(events["category"].dropna()) <= {
        Category.ABSENT_UNEXCUSED.value,
        Category.ABSENT_EXCUSED.value,
        Category.TARDY.value,
    }


def _wide_fixture() -> pd.DataFrame:
    columns = ["Sis Number", "Date", "Period 1", "Period 2", "Period 3",
               "Period 4", "Period 5"]
    rows = [
        # full-day absence: all five periods marked
        ["901", "09/08/2025 (D2S)", "Unverified", "Unverified", "Unverified",
         "Unverified", "Unverified"],
        # single-period cut: must NOT count as an absent day
        ["901", "09/09/2025 (MFonly)", None, None, None, None, "Unverified"],
        # tardy only
        ["902", "09/09/2025 (MFonly)", "Unx.Tardy", None, None, None, None],
    ]
    return pd.DataFrame(rows, columns=columns)


def test_densify_day_collapse_and_missing_days():
    frame = _wide_fixture()
    mapping = ColumnMapping(
        shape=Shape.PERIOD_WIDE,
        columns={"student_id": "Sis Number", "date": "Date"},
    )
    code_map = codes_mod.propose_code_map({"UNVERIFIED": 6, "UNX.TARDY": 1})
    events, _ = normalize.build_events_wide(frame, mapping, code_map)

    assert metrics.infer_periods_per_day(events) == 5
    calendar = pd.DatetimeIndex(
        pd.to_datetime(["2025-09-08", "2025-09-09", "2025-09-10"])
    )
    dense = metrics.densify_day_status(
        metrics.build_day_status(events),
        periods_per_day=5,
        calendar=calendar,
        student_ids=["901", "902", "903"],  # 903 has no marks at all
    )
    # Every (student, calendar day) pair exists.
    assert len(dense) == 9
    by_key = dense.set_index(["student_id", "date"])

    full_day = by_key.loc[("901", pd.Timestamp("2025-09-08"))]
    assert bool(full_day["is_absent_day"])
    cut_day = by_key.loc[("901", pd.Timestamp("2025-09-09"))]
    assert not bool(cut_day["is_absent_day"])  # 1 of 5 periods < 50%
    assert bool(cut_day["is_partial_absence"])
    tardy_day = by_key.loc[("902", pd.Timestamp("2025-09-09"))]
    assert bool(tardy_day["is_tardy_day"]) and not bool(tardy_day["is_absent_day"])
    ghost = by_key.loc[("903", pd.Timestamp("2025-09-10"))]
    assert ghost["dominant_status"] == Category.PRESENT.value
    assert int(ghost["periods_scheduled"]) == 5

    counts = metrics.per_student_counts(dense)
    by_student = counts.set_index("student_id")
    assert int(by_student.loc["901", "days_absent"]) == 1
    assert int(by_student.loc["901", "days_enrolled"]) == 3
    assert int(by_student.loc["903", "days_absent"]) == 0


def _assemble(dataset, as_xlsx_bytes, school_days):
    report_frame, report_result = _detect(dataset, as_xlsx_bytes)
    caseload_frame, caseload_result = detection.detect_caseload(
        as_xlsx_bytes(dataset["caseload_template"]), "caseload.xlsx"
    )
    return pipeline.assemble_bundle(
        report_frame=report_frame,
        report_mapping=ColumnMapping(
            shape=report_result.shape, columns=report_result.mapping
        ),
        caseload_frame=caseload_frame,
        caseload_mapping=ColumnMapping(
            shape=Shape.UNKNOWN, columns=caseload_result.mapping
        ),
        code_map=codes_mod.propose_code_map(report_result.observed_codes),
        enrolled_override=school_days,
    )


def test_end_to_end_matches_simulator_truth(small_dataset, as_xlsx_bytes):
    n_days = len(small_dataset["calendar"])
    bundle, warnings = _assemble(small_dataset, as_xlsx_bytes, n_days)
    assert bundle.capabilities == {
        Capability.SUMMARY_MIN, Capability.DAILY, Capability.PERIOD,
    }

    roster = small_dataset["roster"]
    caseload = roster[roster["on_caseload"]]
    daily = small_dataset["daily_events"]
    marked_students = set(
        small_dataset["report_atp201"]["Sis Number"].astype(str)
    )

    metrics_frame = bundle.metrics.set_index("student_id")
    assert len(metrics_frame) == len(caseload)
    for student in caseload.itertuples(index=False):
        row = metrics_frame.loc[str(student.student_id)]
        truth = daily[daily["student_id"] == student.student_id]["code"]
        if str(student.student_id) not in marked_students:
            # Perfect attendance -> absent from an exception report.
            assert row["matched"] == False  # noqa: E712
            continue
        assert row["matched"] == True  # noqa: E712
        assert int(row["days_absent"]) == int(truth.isin(["A", "E"]).sum())
        assert int(row["days_tardy"]) == int((truth == "T").sum())
        assert int(row["days_enrolled"]) == n_days
        assert pd.notna(row["tier"])


def test_period_skipper_flagged_from_wide_report(demo_dataset, as_xlsx_bytes):
    n_days = len(demo_dataset["calendar"])
    bundle, _ = _assemble(demo_dataset, as_xlsx_bytes, n_days)
    roster = demo_dataset["roster"]
    caseload = roster[roster["on_caseload"]]
    metrics_frame = bundle.metrics.set_index("student_id")

    skippers = caseload[caseload["profile"] == "period5_skipper"]["student_id"]
    assert len(skippers)
    for student_id in skippers:
        row = metrics_frame.loc[str(student_id)]
        if row["matched"]:
            assert row["worst_period"] == "5"

    friday = caseload[caseload["profile"] == "friday_skipper"]["student_id"]
    assert len(friday)
    for student_id in friday:
        row = metrics_frame.loc[str(student_id)]
        if row["matched"]:
            assert row["mon_fri_flag"] == True  # noqa: E712
