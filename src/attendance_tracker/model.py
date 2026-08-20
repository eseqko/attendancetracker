"""Dataclasses shared across the core package and the UI."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .constants import Capability, Category, Shape


@dataclass
class DetectionResult:
    """Outcome of header/shape/column detection on an uploaded report.

    Always shown to the user for confirmation — high confidence only means
    confirming takes one click.
    """

    shape: Shape
    confidence: str  # "high" | "medium" | "low"
    header_row: int  # 0-based row index of the header within the raw file
    mapping: dict[str, str]  # role -> source column name
    warnings: list[str] = field(default_factory=list)
    observed_codes: dict[str, int] = field(default_factory=dict)  # code -> count


@dataclass
class ColumnMapping:
    """User-confirmed mapping from roles to source columns."""

    shape: Shape
    columns: dict[str, str]  # role -> source column name


@dataclass
class CodeMap:
    """User-confirmed mapping from raw attendance codes to categories."""

    codes: dict[str, Category]
    version: int = 1

    def category_for(self, code: str) -> Category:
        return self.codes.get(str(code).strip().upper(), Category.UNKNOWN)


@dataclass
class BaselineMetrics:
    """Schoolwide aggregates kept after non-caseload rows are dropped.

    Contains no per-student data — only counts and rates.
    """

    n_students: int
    mean_attendance_rate: float | None
    tier_counts: dict[str, int]  # Tier.value -> count
    by_grade: pd.DataFrame | None = None  # grade, n_students, mean_attendance_rate
    weekday_absence_rate: pd.DataFrame | None = None  # weekday, absence_rate


@dataclass
class DataBundle:
    """Everything the analysis pages need, built once at end of setup."""

    students: pd.DataFrame
    metrics: pd.DataFrame
    baseline: BaselineMetrics
    unmatched: pd.DataFrame
    capabilities: frozenset[Capability]
    events: pd.DataFrame | None = None  # daily/period shapes only
    summary: pd.DataFrame | None = None  # summary shape only
    day_status: pd.DataFrame | None = None  # derived from events
    code_map: CodeMap | None = None

    def has(self, capability: Capability) -> bool:
        return capability in self.capabilities
