"""Synthetic sample data: fake caseload + attendance reports in all three shapes.

Single source of demo and test data. Everything is deterministic for a given
seed, and every name/ID is obviously fake. Tests import these functions and
write into tmp_path; the CLI (scripts/generate_sample_data.py) writes a demo
set into a gitignored directory. No real student data is ever involved.

Simulation strategy: period-level attendance is simulated first (7 periods per
day), the daily view is derived from it (a day is absent when >=50% of periods
are absent), and the summary view is derived from the daily view — so the three
report shapes are mutually consistent.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

FIRST_NAMES = [
    "Aaliyah", "Bruno", "Carmen", "Devi", "Ezra", "Fatima", "Gustavo", "Hana",
    "Imani", "Jorge", "Kira", "Luca", "Mina", "Nico", "Opal", "Priya",
    "Quentin", "Rosa", "Silas", "Tova", "Umar", "Vera", "Wren", "Ximena",
    "Yusuf", "Zed",
]
LAST_NAMES = [
    "Testperson", "Example", "Sampleton", "Fakerly", "Demoson", "Mockwell",
    "Placeholder", "Fixture", "Dataman", "Specimen", "Dummyfield", "Pretendo",
]

PERIODS_PER_DAY = 7

#: profile -> (p_absent_day, excused_share, p_tardy_day)
PROFILE_PARAMS: dict[str, tuple[float, float, float]] = {
    "good": (0.015, 0.7, 0.02),
    "moderate": (0.06, 0.6, 0.05),
    "chronic": (0.25, 0.4, 0.05),
    "friday_skipper": (0.02, 0.3, 0.03),  # plus Friday/Monday boosts below
    "declining": (0.02, 0.5, 0.04),  # ramps to ~0.35 by year end
    "tardy_prone": (0.03, 0.6, 0.30),
    "period5_skipper": (0.02, 0.5, 0.03),  # plus period-5 skips below
}

FRIDAY_SKIP_P = 0.30
MONDAY_SKIP_P = 0.12
DECLINING_END_P = 0.35
PERIOD5_SKIP_P = 0.25
PARTIAL_DAY_P = 0.01  # anyone: 3-period excused partial (appointment)

#: Deliberate mix on the caseload so every analysis has something to show.
CASELOAD_PROFILE_CYCLE = [
    "good", "chronic", "friday_skipper", "good", "declining", "moderate",
    "tardy_prone", "good", "period5_skipper", "moderate",
]


def school_calendar(
    start: dt.date = dt.date(2025, 8, 11),
    end: dt.date = dt.date(2026, 3, 13),
) -> list[dt.date]:
    """Weekday school days between start and end, minus common breaks."""
    breaks: set[dt.date] = set()
    breaks.add(dt.date(2025, 9, 1))  # Labor Day
    breaks.update(dt.date(2025, 11, 24) + dt.timedelta(d) for d in range(5))
    winter = dt.date(2025, 12, 22)
    while winter <= dt.date(2026, 1, 2):
        breaks.add(winter)
        winter += dt.timedelta(days=1)
    breaks.add(dt.date(2026, 1, 19))  # MLK Day
    breaks.add(dt.date(2026, 2, 16))  # Presidents Day

    days = []
    day = start
    while day <= end:
        if day.weekday() < 5 and day not in breaks:
            days.append(day)
        day += dt.timedelta(days=1)
    return days


def make_roster(
    n_school: int = 300, n_caseload: int = 45, seed: int = 42
) -> pd.DataFrame:
    """Fake school roster; the first n_caseload students are the caseload.

    Columns: student_id, first_name, last_name, grade, profile, on_caseload,
    case_manager, program.
    """
    rng = np.random.default_rng(seed)
    ids = [f"{900001 + i}" for i in range(n_school)]
    first = rng.choice(FIRST_NAMES, size=n_school)
    last = rng.choice(LAST_NAMES, size=n_school)
    grades = rng.choice(["06", "07", "08"], size=n_school)

    profiles = []
    for i in range(n_school):
        if i < n_caseload:
            profiles.append(CASELOAD_PROFILE_CYCLE[i % len(CASELOAD_PROFILE_CYCLE)])
        else:
            profiles.append(rng.choice(["good", "good", "good", "moderate", "chronic"]))

    managers = ["Casey Manager", "Robin Counselor", "Alex Advisor"]
    programs = ["Resource", "Speech", "Counseling"]
    return pd.DataFrame(
        {
            "student_id": pd.array(ids, dtype="string"),
            "first_name": pd.array(first, dtype="string"),
            "last_name": pd.array(last, dtype="string"),
            "grade": pd.array(grades, dtype="string"),
            "profile": pd.array(profiles, dtype="string"),
            "on_caseload": np.arange(n_school) < n_caseload,
            "case_manager": pd.array(
                [managers[i % len(managers)] for i in range(n_school)], dtype="string"
            ),
            "program": pd.array(
                [programs[i % len(programs)] for i in range(n_school)], dtype="string"
            ),
        }
    )


def simulate_period_events(
    roster: pd.DataFrame, calendar: list[dt.date], seed: int = 42
) -> pd.DataFrame:
    """Period-level events: student_id, date, period (1..7), code (P/A/E/T)."""
    rng = np.random.default_rng(seed + 1)
    n_days = len(calendar)
    rows_id, rows_date, rows_period, rows_code = [], [], [], []

    for student in roster.itertuples(index=False):
        p_absent, excused_share, p_tardy = PROFILE_PARAMS[str(student.profile)]
        for day_idx, day in enumerate(calendar):
            p_abs = p_absent
            if student.profile == "friday_skipper":
                if day.weekday() == 4:
                    p_abs = FRIDAY_SKIP_P
                elif day.weekday() == 0:
                    p_abs = MONDAY_SKIP_P
            elif student.profile == "declining":
                frac = day_idx / max(n_days - 1, 1)
                p_abs = p_absent + (DECLINING_END_P - p_absent) * frac

            roll = rng.random()
            if roll < p_abs:
                code = "E" if rng.random() < excused_share else "A"
                day_codes = [code] * PERIODS_PER_DAY
            elif roll < p_abs + PARTIAL_DAY_P:
                day_codes = ["P"] * PERIODS_PER_DAY
                for per in (4, 5, 6):  # afternoon appointment
                    day_codes[per] = "E"
            else:
                day_codes = ["P"] * PERIODS_PER_DAY
                if (
                    student.profile == "period5_skipper"
                    and rng.random() < PERIOD5_SKIP_P
                ):
                    day_codes[4] = "A"  # period 5
                if rng.random() < p_tardy:
                    day_codes[0] = "T"

            rows_id.extend([student.student_id] * PERIODS_PER_DAY)
            rows_date.extend([day] * PERIODS_PER_DAY)
            rows_period.extend(range(1, PERIODS_PER_DAY + 1))
            rows_code.extend(day_codes)

    return pd.DataFrame(
        {
            "student_id": pd.array(rows_id, dtype="string"),
            "date": pd.to_datetime(rows_date),
            "period": rows_period,
            "code": pd.array(rows_code, dtype="string"),
        }
    )


def derive_daily_events(period_events: pd.DataFrame) -> pd.DataFrame:
    """Collapse period events to one row per student-day (P/A/E/T)."""

    def day_code(codes: pd.Series) -> str:
        n_absent = codes.isin(["A", "E"]).sum()
        if n_absent / len(codes) >= 0.5:
            n_unexcused = (codes == "A").sum()
            return "A" if n_unexcused > n_absent - n_unexcused else "E"
        if (codes == "T").any():
            return "T"
        return "P"

    daily = (
        period_events.groupby(["student_id", "date"], observed=True)["code"]
        .apply(day_code)
        .reset_index()
    )
    daily["student_id"] = daily["student_id"].astype("string")
    daily["code"] = daily["code"].astype("string")
    return daily


def derive_summary(daily_events: pd.DataFrame, calendar: list[dt.date]) -> pd.DataFrame:
    """Per-student totals derived from the daily view."""
    n_days = len(calendar)
    grouped = daily_events.groupby("student_id", observed=True)["code"]
    summary = pd.DataFrame(
        {
            "days_absent": grouped.apply(lambda c: int(c.isin(["A", "E"]).sum())),
            "days_tardy": grouped.apply(lambda c: int((c == "T").sum())),
        }
    ).reset_index()
    summary["days_enrolled"] = n_days
    summary["attendance_pct"] = (
        100 * (1 - summary["days_absent"] / summary["days_enrolled"])
    ).round(1)
    return summary


# ---------------------------------------------------------------------------
# Report renderers: turn simulated frames into SIS-style export frames.
# ---------------------------------------------------------------------------


def _full_name(roster: pd.DataFrame) -> pd.Series:
    return roster["last_name"] + ", " + roster["first_name"]


#: Header row of the district caseload template (Synergy QRY801-style export).
#: 'Perm ID' is the SIS-local student ID that attendance reports key on;
#: 'Ed-Fi ID' and 'State ID' are other ID systems and must NOT be used for
#: matching by default.
CASELOAD_TEMPLATE_COLUMNS = [
    "Student Name", "Perm ID", "Ed-Fi ID", "State ID",
    "Legal Last Name", "Legal First Name", "Grade",
]
CASELOAD_TEMPLATE_SHEET = "QRY801"


def render_caseload_template(roster: pd.DataFrame) -> pd.DataFrame:
    """Caseload in the district template format (CASELOAD_TEMPLATE_COLUMNS).

    Ed-Fi and State IDs are synthetic and deliberately different from Perm ID
    so tests can prove the matcher never picks them up.
    """
    caseload = roster[roster["on_caseload"]].reset_index(drop=True)
    return pd.DataFrame(
        {
            "Student Name": caseload["last_name"] + ", " + caseload["first_name"],
            "Perm ID": caseload["student_id"],
            "Ed-Fi ID": pd.array(
                [f"{550001 + i}" for i in range(len(caseload))], dtype="string"
            ),
            "State ID": pd.array(
                [f"{7700000001 + i}" for i in range(len(caseload))], dtype="string"
            ),
            "Legal Last Name": caseload["last_name"],
            "Legal First Name": caseload["first_name"],
            "Grade": caseload["grade"],
        }
    )


def render_caseload(roster: pd.DataFrame, leading_zeros: bool = False) -> pd.DataFrame:
    """The user's caseload file: one row per caseload student."""
    caseload = roster[roster["on_caseload"]]
    ids = caseload["student_id"]
    if leading_zeros:
        ids = ids.str.zfill(8)
    return pd.DataFrame(
        {
            "Student ID": ids,
            "Last Name": caseload["last_name"],
            "First Name": caseload["first_name"],
            "Grade": caseload["grade"],
            "Case Manager": caseload["case_manager"],
            "Program": caseload["program"],
        }
    ).reset_index(drop=True)


def render_daily_report(
    roster: pd.DataFrame,
    daily_events: pd.DataFrame,
    absences_only: bool = False,
    unknown_code_share: float = 0.0,
    floatify_ids: bool = False,
    seed: int = 42,
) -> pd.DataFrame:
    """Shape (a): one row per student per day."""
    rng = np.random.default_rng(seed + 2)
    names = roster.set_index("student_id")
    report = daily_events.copy()
    if absences_only:
        report = report[report["code"] != "P"]
    report = pd.DataFrame(
        {
            "Student ID": report["student_id"],
            "Student Name": _full_name(names.loc[report["student_id"]]).values,
            "Grade": names.loc[report["student_id"], "grade"].values,
            "Date": report["date"].dt.strftime("%m/%d/%Y"),
            "Attendance Code": report["code"],
        }
    ).reset_index(drop=True)
    if unknown_code_share > 0:
        absent_rows = report.index[report["Attendance Code"] == "A"]
        n_swap = int(len(absent_rows) * unknown_code_share)
        if n_swap:
            swap = rng.choice(absent_rows, size=n_swap, replace=False)
            report.loc[swap, "Attendance Code"] = "Q"
    if floatify_ids:
        report["Student ID"] = report["Student ID"].astype(float)
    return report


def render_summary_report(
    roster: pd.DataFrame, summary: pd.DataFrame
) -> pd.DataFrame:
    """Shape (b): one row per student with totals."""
    names = roster.set_index("student_id")
    return pd.DataFrame(
        {
            "Student ID": summary["student_id"],
            "Student Name": _full_name(names.loc[summary["student_id"]]).values,
            "Grade": names.loc[summary["student_id"], "grade"].values,
            "Days Enrolled": summary["days_enrolled"],
            "Days Absent": summary["days_absent"],
            "Days Tardy": summary["days_tardy"],
            "Attendance %": summary["attendance_pct"],
        }
    ).reset_index(drop=True)


def render_period_report(
    roster: pd.DataFrame, period_events: pd.DataFrame
) -> pd.DataFrame:
    """Shape (c): one row per student per day per period."""
    names = roster.set_index("student_id")
    return pd.DataFrame(
        {
            "Student ID": period_events["student_id"],
            "Student Name": _full_name(names.loc[period_events["student_id"]]).values,
            "Date": period_events["date"].dt.strftime("%m/%d/%Y"),
            "Period": period_events["period"],
            "Code": period_events["code"],
        }
    ).reset_index(drop=True)


#: Letter code -> ATP201 period-cell word.
ATP201_CODE_WORDS = {"A": "Unverified", "E": "Ilness", "T": "Unx.Tardy"}
ATP201_SUFFIX_BY_WEEKDAY = {0: "MFonly", 1: "D2S", 2: "W2122", 3: "D2S", 4: "MFonly"}


def render_atp201_report(
    roster: pd.DataFrame, period_events: pd.DataFrame
) -> pd.DataFrame:
    """Synergy ATP201-style report: one row per student per day with marks,
    one column per period, code words in cells, blank = present.

    Mirrors the real export closely on purpose: dates carry schedule-type
    suffixes like '(D2S)', and the demographic/family-contact columns are
    FILLED with obviously fake values — the real file has them populated, and
    detection must not trip over a Birth Date full of dates or a phone number
    that looks like an ID.
    """
    names = roster.set_index("student_id")
    marks = period_events[period_events["code"] != "P"].copy()
    marks["word"] = marks["code"].map(ATP201_CODE_WORDS)
    wide = marks.pivot_table(
        index=["student_id", "date"], columns="period", values="word", aggfunc="first"
    ).reindex(columns=range(1, PERIODS_PER_DAY + 1))

    rows: list[dict[str, object]] = []
    for (student_id, date), row in wide.iterrows():
        info = names.loc[student_id]
        suffix = ATP201_SUFFIX_BY_WEEKDAY.get(date.weekday(), "D2S")
        record: dict[str, object] = {
            "School Name": "Jefferson Example High",
            "School Year": "2025-2026",
            "Student Name": f"{info['last_name']}, {info['first_name']}",
            "Legal Formatted Name": f"{info['last_name']}, {info['first_name']}",
            "Nick Name": str(info["first_name"]),
            "Last Name Goes By": str(info["last_name"]),
            "Ethnicity": "Declined to state",
            "Original Enter Date": None,
            "Final Withdrawal Date": None,
            "Sis Number": str(student_id),
            "Grade": str(info["grade"]),
            "Date": f"{date.strftime('%m/%d/%Y')} ({suffix})",
            "Period 0": None,
        }
        for period in range(1, PERIODS_PER_DAY + 1):
            value = row[period]
            record[f"Period {period}"] = value if pd.notna(value) else None
        for period in range(PERIODS_PER_DAY + 1, 11):
            record[f"Period {period}"] = None
        record.update(
            {
                "Note": None,
                "Birth Date": "01/15/2012",
                "Gender": "X",
                "Phone": "555-0100",
                "Home Language": "English",
                "Home Address": "1 Example St",
                "Home City": "Sampletown",
                "Home State": "CA",
                "ZIP Code 5": "90000",
                "ZIP Code 4": "0000",
                "Relationship 1": "Parent",
                "Parent Name 1": "Pat Testparent",
                "Phone Type 1": "Cell",
                "Phone 1": "555-0101",
                "Extension 1": None,
                "Contact Allowed 1": "Y",
                "Mailings Allowed1": "Y",
                "Ed. Rights 1": "Y",
                "Lives With 1": "Y",
                "Has Custody 1": "Y",
            }
        )
        rows.append(record)
    return pd.DataFrame(rows)


def with_preamble(frame: pd.DataFrame, lines: list[str]) -> pd.DataFrame:
    """Prepend SIS-style title/preamble rows above the real header.

    Returns a headerless frame (preamble rows, then the original header as a
    data row, then the data) suitable for writing with header=False.
    """
    width = len(frame.columns)
    rows: list[list[object]] = []
    for line in lines:
        rows.append([line] + [None] * (width - 1))
    rows.append(list(frame.columns))
    rows.extend(frame.astype(object).values.tolist())
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Dataset bundle + writers
# ---------------------------------------------------------------------------

PREAMBLE_LINES = [
    "Springfield Unified School District",
    "Attendance Detail Report — generated 03/13/2026",
    "",
]


def build_dataset(
    n_school: int = 300,
    n_caseload: int = 45,
    seed: int = 42,
    start: dt.date = dt.date(2025, 8, 11),
    end: dt.date = dt.date(2026, 3, 13),
) -> dict:
    """Simulate one coherent dataset and return all frames, keyed by name."""
    calendar = school_calendar(start, end)
    roster = make_roster(n_school=n_school, n_caseload=n_caseload, seed=seed)
    period_events = simulate_period_events(roster, calendar, seed=seed)
    daily_events = derive_daily_events(period_events)
    summary = derive_summary(daily_events, calendar)
    return {
        "calendar": calendar,
        "roster": roster,
        "period_events": period_events,
        "daily_events": daily_events,
        "summary": summary,
        "caseload": render_caseload(roster),
        "caseload_template": render_caseload_template(roster),
        "caseload_leading_zeros": render_caseload(roster, leading_zeros=True),
        "report_daily": render_daily_report(roster, daily_events, seed=seed),
        "report_daily_absences_only": render_daily_report(
            roster, daily_events, absences_only=True, seed=seed
        ),
        "report_daily_messy": render_daily_report(
            roster,
            daily_events,
            unknown_code_share=0.05,
            floatify_ids=True,
            seed=seed,
        ),
        "report_summary": render_summary_report(roster, summary),
        "report_period": render_period_report(roster, period_events),
        "report_atp201": render_atp201_report(roster, period_events),
    }


def write_demo_files(outdir: str | Path, seed: int = 42) -> list[Path]:
    """Write the demo file set (CSV + XLSX where practical) into outdir."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    data = build_dataset(seed=seed)
    written: list[Path] = []

    def save(frame: pd.DataFrame, stem: str, xlsx: bool = True, header: bool = True):
        csv_path = outdir / f"{stem}.csv"
        frame.to_csv(csv_path, index=False, header=header)
        written.append(csv_path)
        if xlsx:
            xlsx_path = outdir / f"{stem}.xlsx"
            frame.to_excel(xlsx_path, index=False, header=header)
            written.append(xlsx_path)

    save(data["caseload"], "caseload")
    template_path = outdir / "caseload_template.xlsx"
    data["caseload_template"].to_excel(
        template_path, index=False, sheet_name=CASELOAD_TEMPLATE_SHEET
    )
    written.append(template_path)
    save(data["caseload_leading_zeros"], "caseload_leading_zeros", xlsx=False)
    save(
        with_preamble(data["caseload"], PREAMBLE_LINES),
        "caseload_preamble",
        xlsx=False,
        header=False,
    )
    save(data["report_daily"], "report_daily")
    save(data["report_daily_absences_only"], "report_daily_absences_only", xlsx=False)
    save(
        with_preamble(data["report_daily_messy"], PREAMBLE_LINES),
        "report_daily_messy",
        xlsx=False,
        header=False,
    )
    save(data["report_summary"], "report_summary")
    # Period report is large (~300k rows); CSV only.
    save(data["report_period"], "report_period", xlsx=False)
    atp201_path = outdir / "report_atp201.xlsx"
    data["report_atp201"].to_excel(atp201_path, index=False)
    written.append(atp201_path)
    return written
