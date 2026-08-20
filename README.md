# Attendance Tracker

A local [Streamlit](https://streamlit.io) app for case managers, counselors, and anyone who works
with a student **caseload**. Upload your caseload list and a **schoolwide** attendance report
exported from your student information system (SIS); the tracker joins the two on student ID,
focuses on *your* students, and analyzes:

- **Watch-list & tiers** — chronic-absenteeism tiers (satisfactory / at-risk / chronic / severe)
  with a sortable, filterable watch-list.
- **Individual trends** — per-student calendar heatmap, weekly attendance-rate trend
  (improving / stable / declining), absence & tardy history.
- **Cohorts** — your caseload vs. the schoolwide baseline, by grade, or by custom groups you assign.
- **Patterns** — Monday/Friday effects, consecutive-absence streaks, tardy clusters, and
  period-skipping (when your report includes period-level data).

## Privacy

This tool is designed for sensitive student data:

- Everything runs **locally on your computer**. No cloud services, no external APIs.
- Uploaded files are held **in memory only** for the browser session — the app never writes
  student data to disk.
- The only thing you can save is a small **code-mapping JSON** (which attendance codes mean
  absent/tardy/etc.). It contains no student data.
- The repo's `.gitignore` blocks all `*.csv` / `*.xlsx` files so real exports can't be
  committed by accident.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
streamlit run app.py
```

Your browser opens the app. Start on **Upload & Setup**.

## Caseload file format

Use the district caseload template: an Excel file whose **first row is the header row** with
these fields:

| # | Header field | What the tracker does with it |
|---|--------------|-------------------------------|
| 1 | `Student Name` | display name ("Last, First") |
| 2 | `Perm ID` | **required — the matching key.** Must be the same student ID your attendance report uses |
| 3 | `Ed-Fi ID` | kept for reference; never used for matching |
| 4 | `State ID` | kept for reference; never used for matching |
| 5 | `Legal Last Name` | name fallback when `Student Name` is blank |
| 6 | `Legal First Name` | name fallback when `Student Name` is blank |
| 7 | `Grade` | powers the by-grade cohort comparison and grade filters — add this column to your export |

One row per student below the header. `Perm ID` is the only strictly required field — a file
with just that column still works — but include the rest (especially `Grade`) to get names and
grade-level analyses. Any additional columns you add (case manager, program, …) are kept and
become group-by options on the Cohorts page. The setup wizard always shows you which column it
mapped to which field so you can correct it before anything is computed.

## Usage

1. **Upload your caseload** (CSV or Excel) in the template format above. Extra columns (e.g.
   case manager, program) become group-by options on the Cohorts page.
2. **Upload the attendance report** (CSV or Excel). The app auto-detects the report's shape —
   one row per student-day, a per-student summary, or period-by-period — and asks you to confirm
   the column mapping. Header rows buried under title/preamble lines are detected automatically.
3. **Confirm attendance codes** (for day-level reports): map each code your SIS uses (A, U, E,
   T, ISS, …) to a category. Sensible defaults are proposed; you can save the mapping as JSON
   and re-load it next time.
4. **Review matching**: the app shows how many caseload students were found in the report and
   lists anyone unmatched (with hints, e.g. leading-zero ID mismatches).
5. Explore the **Overview**, **Student**, **Cohorts**, and **Patterns** pages. Watch-list and
   per-student summaries can be downloaded as CSV.

A per-student **summary-style** report (totals only, no dates) still powers the watch-list,
tiers, and cohort comparisons — the time-based charts explain what they need and stay hidden.

## Try it with fake data

Generate an obviously-synthetic demo dataset (fake names, fake IDs) in all three report shapes:

```bash
python scripts/generate_sample_data.py --outdir sample_data --seed 42
```

Then upload `sample_data/caseload.csv` and any of the generated reports.

## Development

Core logic (parsing, shape detection, ID matching, metrics) lives in `src/attendance_tracker/`
as plain pandas functions with no Streamlit imports; the UI in `app.py` + `ui/` is a thin layer
over it.

```bash
pytest
```
