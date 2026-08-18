"""End-to-end: file bytes -> detection -> pipeline -> DataBundle, all shapes."""

from __future__ import annotations

import pandas as pd
import pytest

from attendance_tracker import codes as codes_mod
from attendance_tracker import detection, pipeline, sample_data
from attendance_tracker.constants import Capability, Category, Shape, Trend
from attendance_tracker.model import ColumnMapping


def _detect_and_map(data: bytes, filename: str):
    frame, result = detection.detect_report(data, filename)
    mapping = ColumnMapping(shape=result.shape, columns=result.mapping)
    return frame, result, mapping


def _caseload_mapping(data: bytes, filename: str):
    frame, result = detection.detect_caseload(data, filename)
    return frame, ColumnMapping(shape=Shape.UNKNOWN, columns=result.mapping)


def _bundle_for(dataset, report_key: str, fmt, caseload_key: str = "caseload"):
    report_frame = dataset[report_key]
    caseload_frame = dataset[caseload_key]
    report_bytes = fmt(report_frame)
    caseload_bytes = fmt(caseload_frame)
    suffix = "csv" if report_bytes[:2] != b"PK" else "xlsx"

    frame, result, mapping = _detect_and_map(report_bytes, f"report.{suffix}")
    cl_frame, cl_mapping = _caseload_mapping(caseload_bytes, f"caseload.{suffix}")
    code_map = codes_mod.propose_code_map(result.observed_codes) if result.observed_codes else None
    bundle, warnings = pipeline.assemble_bundle(
        report_frame=frame,
        report_mapping=mapping,
        caseload_frame=cl_frame,
        caseload_mapping=cl_mapping,
        code_map=code_map,
    )
    return bundle, warnings, result


@pytest.mark.parametrize("fmt_name", ["csv", "xlsx"])
def test_daily_shape_end_to_end(small_dataset, as_csv_bytes, as_xlsx_bytes, fmt_name):
    fmt = as_csv_bytes if fmt_name == "csv" else as_xlsx_bytes
    bundle, _, result = _bundle_for(small_dataset, "report_daily", fmt)
    assert result.shape == Shape.DAILY
    assert bundle.capabilities == {Capability.SUMMARY_MIN, Capability.DAILY}
    roster = small_dataset["roster"]
    n_caseload = int(roster["on_caseload"].sum())
    assert len(bundle.metrics) == n_caseload
    assert bundle.metrics["matched"].all()
    assert bundle.unmatched.empty
    # Every matched student has day-derived metrics.
    assert bundle.metrics["days_enrolled"].notna().all()
    assert bundle.metrics["tier"].notna().all()
    assert bundle.day_status is not None and not bundle.day_status.empty
    # Baseline covers the whole school, not just the caseload.
    assert bundle.baseline.n_students == len(roster)


@pytest.mark.parametrize("fmt_name", ["csv", "xlsx"])
def test_summary_shape_end_to_end(small_dataset, as_csv_bytes, as_xlsx_bytes, fmt_name):
    fmt = as_csv_bytes if fmt_name == "csv" else as_xlsx_bytes
    bundle, _, result = _bundle_for(small_dataset, "report_summary", fmt)
    assert result.shape == Shape.SUMMARY
    assert bundle.capabilities == {Capability.SUMMARY_MIN}
    assert bundle.events is None and bundle.day_status is None
    assert (bundle.metrics["trend"] == Trend.INSUFFICIENT.value).all()
    assert bundle.metrics["tier"].notna().all()
    # Summary tiers must agree with the daily-derived truth from the simulator.
    truth = small_dataset["summary"].set_index("student_id")
    for _, row in bundle.metrics.iterrows():
        expected_absent = truth.at[row["student_id"], "days_absent"]
        assert row["days_absent"] == pytest.approx(expected_absent)


def test_period_shape_end_to_end(small_dataset, as_csv_bytes):
    bundle, _, result = _bundle_for(small_dataset, "report_period", as_csv_bytes)
    assert result.shape == Shape.PERIOD
    assert bundle.capabilities == {
        Capability.SUMMARY_MIN,
        Capability.DAILY,
        Capability.PERIOD,
    }
    # Period day-collapse must agree with the simulator's own daily derivation.
    daily_truth = small_dataset["daily_events"]
    truth_absent = (
        daily_truth[daily_truth["code"].isin(["A", "E"])]
        .groupby("student_id", observed=True)
        .size()
    )
    for _, row in bundle.metrics.iterrows():
        expected = int(truth_absent.get(row["student_id"], 0))
        assert row["days_absent"] == expected, row["student_id"]


def test_leading_zero_caseload_matches(small_dataset, as_csv_bytes):
    bundle, _, _ = _bundle_for(
        small_dataset, "report_daily", as_csv_bytes,
        caseload_key="caseload_leading_zeros",
    )
    assert bundle.metrics["matched"].all()
    assert bundle.unmatched.empty
    # Downstream frames are keyed by the caseload's (zero-padded) ids.
    assert bundle.metrics["student_id"].str.startswith("00").all()
    assert bundle.events["student_id"].str.startswith("00").all()


def test_messy_daily_report_end_to_end(small_dataset, as_csv_bytes):
    messy = sample_data.with_preamble(
        small_dataset["report_daily_messy"], sample_data.PREAMBLE_LINES
    )
    report_bytes = as_csv_bytes(messy, header=False)
    frame, result, mapping = _detect_and_map(report_bytes, "report.csv")
    assert result.shape == Shape.DAILY
    assert "Q" in result.observed_codes

    code_map = codes_mod.propose_code_map(result.observed_codes)
    assert code_map.codes["Q"] == Category.UNKNOWN
    code_map.codes["Q"] = Category.OTHER_PRESENT  # the UI's escape hatch

    cl_frame, cl_mapping = _caseload_mapping(
        as_csv_bytes(small_dataset["caseload"]), "caseload.csv"
    )
    bundle, _ = pipeline.assemble_bundle(
        report_frame=frame,
        report_mapping=mapping,
        caseload_frame=cl_frame,
        caseload_mapping=cl_mapping,
        code_map=code_map,
    )
    assert bundle.metrics["matched"].all()
    assert bundle.metrics["tier"].notna().all()


def test_unmatched_students_surface(small_dataset, as_csv_bytes):
    caseload = small_dataset["caseload"].copy()
    extra = caseload.iloc[[0]].copy()
    extra["Student ID"] = "999999"
    extra["Last Name"] = "Notinreport"
    caseload = pd.concat([caseload, extra], ignore_index=True)

    report_bytes = as_csv_bytes(small_dataset["report_daily"])
    frame, result, mapping = _detect_and_map(report_bytes, "report.csv")
    cl_frame, cl_mapping = _caseload_mapping(as_csv_bytes(caseload), "caseload.csv")
    bundle, _ = pipeline.assemble_bundle(
        report_frame=frame,
        report_mapping=mapping,
        caseload_frame=cl_frame,
        caseload_mapping=cl_mapping,
        code_map=codes_mod.propose_code_map(result.observed_codes),
    )
    assert len(bundle.unmatched) == 1
    assert bundle.unmatched.iloc[0]["student_id"] == "999999"
    # The unmatched student still has a metrics row, visibly unmatched.
    row = bundle.metrics[bundle.metrics["student_id"] == "999999"].iloc[0]
    assert row["matched"] == False  # noqa: E712
    assert pd.isna(row["attendance_rate"])
