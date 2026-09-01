# Attendance Tracker

A local [Streamlit](https://streamlit.io) app for case managers, counselors, and anyone who works
with a student **caseload**. Upload your caseload list and a **schoolwide** attendance report
exported from your student information system (SIS); the tracker joins the two on student ID,
focuses on *your* students, and analyzes:

- **Watch-list & tiers** — chronic-absenteeism tiers (satisfactory / at-risk / chronic / severe)
  with a sortable, filterable watch-list.
- **Breakdowns** — absences sliced by every dimension the uploads allow: day of week, month,
  period, attendance code, grade, race/ethnicity, gender, custom groups, any extra caseload
  column — and by course, teacher, and counselor when the optional course-context report is
  attached. Every table downloads as CSV.
- **Individual trends** — per-student calendar heatmap, weekly attendance-rate trend
  (improving / stable / declining), absence & tardy history.
- **Cohorts** — your caseload vs. the schoolwide baseline, by grade, or by custom groups you assign.
- **Patterns** — Monday/Friday effects, consecutive-absence streaks, tardy clusters, and
  period-skipping (when your report includes period-level data).

## Privacy

This tool is designed for sensitive student data:

- Everything runs **locally on your computer**. No cloud services, no external APIs.
- By default, uploaded files are held **in memory only** for the browser session — nothing is
  written to disk.
- If you turn on **"Remember these files and settings on this computer"** at the end of setup,
  the app keeps copies of your uploads and your setup choices in a `local_data/` folder next to
  the app — local only, never synced, shared, or committed (it's gitignored). Treat that folder
  like any file containing student data, and use **"Forget saved data"** in Upload & Setup to
  erase it at any time. The settings file itself contains no student information.
- You can also save a small **code-mapping JSON** (which attendance codes mean
  absent/tardy/etc.). It contains no student data. Appearance choices (like the menu
  position) live in a tiny settings file in the same folder — also no student data.
- The repo's `.gitignore` blocks all `*.csv` / `*.xlsx` files so real exports can't be
  committed by accident.

## Easiest setup (no command line)

1. Get the project onto your computer: on the GitHub page click **Code → Download ZIP**, then
   unzip it anywhere (Documents is fine).
2. Double-click the installer — **`install_windows.bat`** on Windows,
   **`install_mac.command`** on a Mac. It finds (or installs) Python, sets everything up, and
   on Windows puts an **Attendance Tracker** shortcut on your desktop. The first run takes a
   few minutes; leave the window open until it says Done.
3. Start the app any time by double-clicking the desktop shortcut (Windows) or
   **`run_tracker.command`** (Mac). Your browser opens; keep the black window open while you
   work, close it to stop.

First-time clicks may need a nudge past the safety prompts: on Windows, if SmartScreen appears
choose **More info → Run anyway**; on a Mac, right-click the file and choose **Open** the first
time.

### Updating the app

Replace the app's files with the new version (download the ZIP again and copy everything into
the same folder, or `git pull`), then just launch as usual — the launcher notices the update
and finishes it automatically. Re-running the installer is always safe too — close the app's
window first — and rebuilds the environment from scratch, fixing any half-updated setup.
Your saved data (`local_data/`) is never touched.

## Chromebooks: the browser version (no install)

The tracker also runs **entirely inside a browser tab** — the whole app, including Python,
executes in the browser via WebAssembly ([stlite](https://github.com/whitphx/stlite)). Nothing
to install, works on managed Chromebooks, and the privacy promise is structural: there is no
server, so uploaded files are analyzed on the device and **cannot** be sent anywhere. The page
itself is public like any website, but it contains only the app's code — never student data.

- Built by `scripts/build_webapp.py` into `webapp/` (`--vendor` bundles every asset locally so
  the page works on school networks that block public CDNs).
- Deployed automatically to **GitHub Pages** by `.github/workflows/pages.yml` on every push to
  `main` → https://eseqko.github.io/attendancetracker/ (one-time setup: repo Settings → Pages →
  Source: "GitHub Actions").
- Trade-offs vs. the installed version: the first visit downloads ~85 MB (a minute or two on
  school Wi‑Fi; ~15 seconds after that), and nothing is saved between visits — closing or
  reloading the tab starts fresh, so keep the two export files handy each session.
- **If your network blocks `github.io`**: the same folder deploys to Firebase Hosting
  (`firebase.json` is included; serves from a `*.web.app` Google domain). Build with
  `python scripts/build_webapp.py --vendor`, then `firebase deploy --only hosting` from a
  machine with the [Firebase CLI](https://firebase.google.com/docs/cli) signed in to a free
  Firebase project.

## Setup (command line)

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

## Attendance report formats

Four layouts are auto-detected (and always confirmed by you before anything is computed).
CSV and Excel files both work — including legacy `.xls` files, which is how Synergy typically
exports reports:

1. **One row per student per day** — student ID + date + attendance code.
2. **One row per student** — summary totals (days enrolled / absent / attendance %). Powers
   tiers and cohorts; time-based charts explain they need day-level data.
3. **One row per student per day per period** — long period-level data.
4. **One row per student per day, one column per period** — e.g. **Synergy ATP201**. The
   columns the tracker uses are exactly:
   - `Sis Number` — the student ID; must be the same **Perm ID** as the caseload
   - `Date` — schedule-type suffixes like `08/07/2026 (D2S)` are handled
   - `Period 0` … `Period N` — each cell an attendance code word (`Unverified`, `Ilness`,
     `Unx.Tardy`, `Activity`, …); blank means present
   - `Grade` — recommended, for grade-level comparisons

   Every other ATP201 column — names, birth date, ethnicity, addresses, phone numbers, parent
   and family contacts — is **ignored at parse time and never enters the analysis data**.
   ATP201 is an *exception report* (only days with marks appear), so setup needs the number of
   school days so far — it detects this itself by counting the distinct dates that appear
   anywhere in the schoolwide report (every school day, someone has a mark) and prefills the
   value for you to confirm or adjust. Unlisted days count as present, and a caseload student
   with no marks at all shows as unmatched — that usually just means perfect attendance. Following the
   district's own counting rules, `Activity` and `Office Ex` are treated as present-like, and
   tardies never count as absences. `Ethnicity` and `Gender` columns are used (only) as
   breakdown dimensions when present.

**Optional course-context report**: the per-class export with one row per student per course
section and one count column per code (`CUT - (Unexcused)`, `ILL - (Excused)`, …, plus
`Student ID`, `Course Title`, `Section ID`, `Teacher Name`, `Counselor Name`). Uploading it in
setup unlocks the by-course, by-teacher, and by-counselor breakdowns.

## Usage

1. **Upload your caseload** (CSV or Excel) in the template format above. Extra columns (e.g.
   case manager, program) become group-by options on the Cohorts page.
2. **Upload the attendance report** (CSV or Excel) in any format above. The app auto-detects
   the layout and asks you to confirm the column mapping. Header rows buried under
   title/preamble lines are detected automatically.
3. **Confirm attendance codes** (for day-level reports): map each code your SIS uses (A, U, E,
   T, ISS, …) to a category. Sensible defaults are proposed; you can save the mapping as JSON
   and re-load it next time.
4. **Review matching**: the app shows how many caseload students were found in the report and
   lists anyone unmatched (with hints, e.g. leading-zero ID mismatches).
5. Explore the **Overview**, **Student**, **Cohorts**, and **Patterns** pages. Watch-list and
   per-student summaries can be downloaded as CSV.

The page menu is pinned — it can't be collapsed away. Prefer it somewhere else? **Menu
position** at the bottom of Upload & Setup moves it (left, top, bottom, or right) and
remembers your choice on this computer.

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
