"""Enums, thresholds, default code mappings, and column-role vocabulary."""

from __future__ import annotations

import enum


class Category(str, enum.Enum):
    """Canonical meaning of an attendance code."""

    PRESENT = "present"
    ABSENT_EXCUSED = "absent_excused"
    ABSENT_UNEXCUSED = "absent_unexcused"
    TARDY = "tardy"
    OTHER_PRESENT = "other_present"  # field trip, school activity, nurse, etc.
    UNKNOWN = "unknown"


#: Categories that count as a missed day (federal chronic-absenteeism convention:
#: excused, unexcused, and suspension days all count as missed).
ABSENT_CATEGORIES = frozenset({Category.ABSENT_EXCUSED, Category.ABSENT_UNEXCUSED})

#: Categories that count as attending (tardy students attended the day).
PRESENT_LIKE_CATEGORIES = frozenset(
    {Category.PRESENT, Category.OTHER_PRESENT, Category.TARDY}
)


class Shape(str, enum.Enum):
    """Detected layout of an uploaded attendance report."""

    DAILY = "daily"  # one row per student per day
    SUMMARY = "summary"  # one row per student, totals only
    PERIOD = "period"  # one row per student per day per period
    PERIOD_WIDE = "period_wide"  # one row per student per day, one column per
    # period (e.g. Synergy ATP201) — an exception report: days with no marks
    # don't appear, and a blank period cell means present/unscheduled
    UNKNOWN = "unknown"


class Capability(str, enum.Enum):
    """What a given upload's data can support."""

    SUMMARY_MIN = "summary_min"  # per-student totals -> tiers, cohorts
    DAILY = "daily"  # day-level events -> trends, streaks, day-of-week
    PERIOD = "period"  # period-level events -> period-skipping


#: Capabilities granted by each report shape.
SHAPE_CAPABILITIES: dict[Shape, frozenset[Capability]] = {
    Shape.DAILY: frozenset({Capability.SUMMARY_MIN, Capability.DAILY}),
    Shape.PERIOD: frozenset(
        {Capability.SUMMARY_MIN, Capability.DAILY, Capability.PERIOD}
    ),
    Shape.PERIOD_WIDE: frozenset(
        {Capability.SUMMARY_MIN, Capability.DAILY, Capability.PERIOD}
    ),
    Shape.SUMMARY: frozenset({Capability.SUMMARY_MIN}),
}

#: What each analysis needs. UI blocks render a standard notice when unmet.
ANALYSIS_REQUIRES: dict[str, frozenset[Capability]] = {
    "tiers": frozenset({Capability.SUMMARY_MIN}),
    "cohorts": frozenset({Capability.SUMMARY_MIN}),
    "trends": frozenset({Capability.DAILY}),
    "calendar": frozenset({Capability.DAILY}),
    "streaks": frozenset({Capability.DAILY}),
    "day_of_week": frozenset({Capability.DAILY}),
    "tardy_clusters": frozenset({Capability.DAILY}),
    "period_skipping": frozenset({Capability.PERIOD}),
}


class Tier(str, enum.Enum):
    """Chronic-absenteeism tier by percent of enrolled days missed."""

    SATISFACTORY = "satisfactory"  # < 5%
    AT_RISK = "at_risk"  # 5% - <10%
    CHRONIC = "chronic"  # 10% - <20%
    SEVERE = "severe"  # >= 20%


TIER_ORDER = [Tier.SATISFACTORY, Tier.AT_RISK, Tier.CHRONIC, Tier.SEVERE]

#: Lower bound of each tier in percent of enrolled days missed.
TIER_LOWER_BOUND_PCT: dict[Tier, float] = {
    Tier.SATISFACTORY: 0.0,
    Tier.AT_RISK: 5.0,
    Tier.CHRONIC: 10.0,
    Tier.SEVERE: 20.0,
}

TIER_LABELS: dict[Tier, str] = {
    Tier.SATISFACTORY: "Satisfactory (<5%)",
    Tier.AT_RISK: "At risk (5–9%)",
    Tier.CHRONIC: "Chronic (10–19%)",
    Tier.SEVERE: "Severe (≥20%)",
}


class Trend(str, enum.Enum):
    IMPROVING = "improving"
    STABLE = "stable"
    DECLINING = "declining"
    INSUFFICIENT = "insufficient"


#: Fraction of a day's scheduled periods that must be missed for the day to
#: count absent (federal ">=50% of the day" convention). Configurable in setup.
DEFAULT_ABSENT_DAY_THRESHOLD = 0.5

#: Trend slope cutoffs, in attendance-rate units per week (0.005 = 0.5 pp/week).
TREND_SLOPE_CUTOFF = 0.005
TREND_WINDOW_WEEKS = 6
TREND_MIN_WEEKS = 4

#: Day-of-week flag: Mon or Fri absence rate >= this multiple of the Tue-Thu
#: mean, with at least MIN_ABSENCES_FOR_DOW_FLAG total absences.
DOW_FLAG_RATIO = 1.5
MIN_ABSENCES_FOR_DOW_FLAG = 5

#: Period skipping: a period's unexcused rate >= this multiple of the mean of
#: the student's other periods, with at least PERIOD_SKIP_MIN_COUNT misses.
PERIOD_SKIP_RATIO = 2.0
PERIOD_SKIP_MIN_COUNT = 3

#: If fewer than this fraction of events are present-like, the report is
#: probably an absences-only exception export and enrolled days can't be
#: derived from it.
EXCEPTION_REPORT_PRESENT_SHARE = 0.05


#: Default mapping from SIS attendance codes (upper-cased, stripped) to
#: categories. Users confirm/override these in the setup wizard.
DEFAULT_CODE_MAP: dict[str, Category] = {
    # present
    "P": Category.PRESENT,
    "PR": Category.PRESENT,
    "PRE": Category.PRESENT,
    "+": Category.PRESENT,
    ".": Category.PRESENT,
    # unexcused absence (suspensions count as missed per federal convention;
    # ISS is ambiguous — some schools count it present — so the UI flags it)
    "A": Category.ABSENT_UNEXCUSED,
    "U": Category.ABSENT_UNEXCUSED,
    "AU": Category.ABSENT_UNEXCUSED,
    "UNX": Category.ABSENT_UNEXCUSED,
    "UNV": Category.ABSENT_UNEXCUSED,
    "ABS": Category.ABSENT_UNEXCUSED,
    "TRU": Category.ABSENT_UNEXCUSED,
    "OSS": Category.ABSENT_UNEXCUSED,
    "SUS": Category.ABSENT_UNEXCUSED,
    "ISS": Category.ABSENT_UNEXCUSED,
    # excused absence
    "E": Category.ABSENT_EXCUSED,
    "X": Category.ABSENT_EXCUSED,
    "AE": Category.ABSENT_EXCUSED,
    "EA": Category.ABSENT_EXCUSED,
    "EXC": Category.ABSENT_EXCUSED,
    "ILL": Category.ABSENT_EXCUSED,
    "MED": Category.ABSENT_EXCUSED,
    "RE": Category.ABSENT_EXCUSED,
    # tardy
    "T": Category.TARDY,
    "TDY": Category.TARDY,
    "TE": Category.TARDY,
    "TU": Category.TARDY,
    "L": Category.TARDY,
    "LT": Category.TARDY,
    # present-like exceptions
    "F": Category.OTHER_PRESENT,
    "FT": Category.OTHER_PRESENT,
    "SCH": Category.OTHER_PRESENT,
    "ACT": Category.OTHER_PRESENT,
    "NUR": Category.OTHER_PRESENT,
    # Word-style codes (Synergy ATP201 period cells). "Activity" and
    # "Office Ex" are present-like: the district's own ATC report excludes
    # their ACT/OFF counterparts from Total Absences. "Ilness" is the SIS's
    # spelling; keep both.
    "UNVERIFIED": Category.ABSENT_UNEXCUSED,
    "PARENT UNEXCUSED": Category.ABSENT_UNEXCUSED,
    "ILNESS": Category.ABSENT_EXCUSED,
    "ILLNESS": Category.ABSENT_EXCUSED,
    "EXCUSED": Category.ABSENT_EXCUSED,
    "COUNSELING": Category.ABSENT_EXCUSED,
    "ACTIVITY": Category.OTHER_PRESENT,
    "OFFICE EX": Category.OTHER_PRESENT,
    "TARDY": Category.TARDY,
    "UNX.TARDY": Category.TARDY,
    "TARDY 30MIN": Category.TARDY,
}

#: Codes whose default categorization deserves a second look from the user.
AMBIGUOUS_CODES = frozenset({"ISS"})


#: Column roles the detector can assign. Values are synonym fragments matched
#: against normalized header names (lowercased, punctuation stripped).
#: Each list is PREFERENCE-ORDERED: when several columns match the same role,
#: the column matching the earlier synonym wins (e.g. 'Perm ID' beats
#: 'State ID' for student_id — Perm ID is the SIS-local ID that attendance
#: reports key on).
ROLE_SYNONYMS: dict[str, list[str]] = {
    "student_id": [
        "student id", "studentid", "student number", "student no", "stu id",
        "local id", "localid", "perm id", "permid", "sis number", "sis id",
        "ssid", "state id", "id number", "student_number", "othername id", "id",
    ],
    "name": [
        "student name", "name", "student", "full name",
    ],
    "first_name": ["first name", "firstname", "first"],
    "last_name": ["last name", "lastname", "last", "surname"],
    "grade": ["grade level", "grade lvl", "grade", "gr lvl", "gr", "grd"],
    "date": [
        "att date", "attendance date", "absence date", "date of absence",
        "date", "day",
    ],
    "code": [
        "att code", "attendance code", "absence code", "code", "mark",
        "attendance", "status",
    ],
    "period": ["period", "per", "prd", "block", "pd"],
    "days_enrolled": [
        "days enrolled", "membership days", "days of membership", "membership",
        "possible days", "days possible", "days in session", "enrolled",
        "total days", "days expected",
    ],
    "days_absent": [
        "days absent", "total absent", "absences", "absent days", "abs days",
        "days abs", "total absences", "absent",
    ],
    "days_excused": ["excused absences", "days excused", "excused"],
    "days_unexcused": [
        "unexcused absences", "days unexcused", "unexcused", "unverified",
    ],
    "days_tardy": ["days tardy", "tardies", "tardy count", "total tardy", "tardy"],
    "attendance_pct": [
        "attendance rate", "attendance pct", "att rate", "att pct", "ada",
        "pct present", "percent present", "attendance %", "att %", "%", "rate",
        "pct", "percent",
    ],
    "ethnicity": ["ethnicity", "race ethnicity", "race"],
    "gender": ["gender", "sex"],
    # course-context (ATC-style) files
    "course": ["course title", "course name", "course", "class"],
    "section": ["section id", "section"],
    "teacher": ["teacher name", "teacher"],
    "counselor": ["counselor name", "counselor", "case manager"],
}

#: Per-student attribute roles carried through events/students frames for
#: demographic breakdowns. In-memory only, like all student data.
ATTRIBUTE_ROLES = ["ethnicity", "gender"]

#: Category suffix of an ATC-style code-count header ('CUT - (Unexcused)').
COURSE_HEADER_CATEGORIES: dict[str, Category] = {
    "excused": Category.ABSENT_EXCUSED,
    "unexcused": Category.ABSENT_UNEXCUSED,
    "unverified": Category.ABSENT_UNEXCUSED,
    "positive": Category.OTHER_PRESENT,
    "excused tardy": Category.TARDY,
    "unexcused tardy": Category.TARDY,
}

#: Codes whose ATC counts are excluded from 'Total Absences' by the district
#: despite an '(Excused)' label — verified against the report's own totals.
COURSE_PRESENT_LIKE_CODES = frozenset({"ACT", "OFF"})

#: Roles a report must map for each shape (beyond these, more is optional).
REQUIRED_ROLES: dict[Shape, list[str]] = {
    Shape.DAILY: ["student_id", "date", "code"],
    Shape.PERIOD: ["student_id", "date", "code", "period"],
    Shape.PERIOD_WIDE: ["student_id", "date"],  # period columns are derived
    Shape.SUMMARY: ["student_id"],  # plus >=1 of the summary count roles
}

SUMMARY_VALUE_ROLES = [
    "days_enrolled",
    "days_absent",
    "days_excused",
    "days_unexcused",
    "days_tardy",
    "attendance_pct",
]
