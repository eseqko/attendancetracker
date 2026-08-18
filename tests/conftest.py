"""Shared fixtures: all test data comes from the seeded synthetic generator
(attendance_tracker.sample_data) or is hand-built inline — no data files are
ever committed to the repo."""

from __future__ import annotations

import datetime as dt
import io

import pytest

from attendance_tracker import sample_data


@pytest.fixture(scope="session")
def small_dataset():
    """Small and fast: 30 school students (12 on caseload), ~8 school weeks."""
    return sample_data.build_dataset(
        n_school=30,
        n_caseload=12,
        seed=7,
        start=dt.date(2025, 9, 8),
        end=dt.date(2025, 10, 31),
    )


@pytest.fixture(scope="session")
def demo_dataset():
    """Mid-size dataset over the full simulated year — enough weeks for
    trend/day-of-week analyses to be meaningful."""
    return sample_data.build_dataset(n_school=80, n_caseload=20, seed=42)


@pytest.fixture()
def as_csv_bytes():
    def _to_bytes(frame, header: bool = True) -> bytes:
        return frame.to_csv(index=False, header=header).encode("utf-8")

    return _to_bytes


@pytest.fixture()
def as_xlsx_bytes():
    def _to_bytes(frame, header: bool = True) -> bytes:
        buffer = io.BytesIO()
        frame.to_excel(buffer, index=False, header=header)
        return buffer.getvalue()

    return _to_bytes
