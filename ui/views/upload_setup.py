"""Upload & Setup: caseload upload -> report upload -> code mapping -> match &
finish. Sections unlock in order; editing an earlier section resets the later
ones. All data stays in session state."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from attendance_tracker import codes as codes_mod
from attendance_tracker import detection, io_utils, joining, normalize, pipeline
from attendance_tracker.constants import (
    DEFAULT_ABSENT_DAY_THRESHOLD,
    EXCEPTION_REPORT_PRESENT_SHARE,
    PRESENT_LIKE_CATEGORIES,
    Category,
    Shape,
)
from attendance_tracker.model import CodeMap, ColumnMapping
from ui import components, state

NONE_OPTION = "(none)"

SHAPE_LABELS = {
    Shape.DAILY: "One row per student per day",
    Shape.SUMMARY: "One row per student (summary totals)",
    Shape.PERIOD: "One row per student per day per period",
}

CATEGORY_LABELS = {
    Category.PRESENT.value: "Present",
    Category.ABSENT_EXCUSED.value: "Absent — excused",
    Category.ABSENT_UNEXCUSED.value: "Absent — unexcused",
    Category.TARDY.value: "Tardy",
    Category.OTHER_PRESENT.value: "Present-like (activity/field trip)",
    Category.UNKNOWN.value: "Unknown — needs review",
}
LABEL_TO_CATEGORY = {v: k for k, v in CATEGORY_LABELS.items()}

REPORT_ROLE_LABELS = {
    "student_id": "Student ID",
    "date": "Date",
    "code": "Attendance code",
    "period": "Period",
    "name": "Student name",
    "grade": "Grade",
    "days_enrolled": "Days enrolled",
    "days_absent": "Days absent",
    "days_excused": "Excused absences",
    "days_unexcused": "Unexcused absences",
    "days_tardy": "Tardies",
    "attendance_pct": "Attendance %",
}


@st.cache_data(show_spinner="Reading file…")
def _cached_detect_caseload(data: bytes, filename: str, sheet, header_row):
    return detection.detect_caseload(data, filename, sheet=sheet, header_row=header_row)


@st.cache_data(show_spinner="Reading report…")
def _cached_detect_report(data: bytes, filename: str, sheet, header_row):
    return detection.detect_report(data, filename, sheet=sheet, header_row=header_row)


def _uploaded_file(section: str, label: str, help_text: str):
    """File uploader whose bytes persist in setup state; returns
    (data, filename) or (None, None). A new upload resets downstream state and
    this section's widget state (its options may no longer exist)."""
    uploaded = st.file_uploader(
        label, type=["csv", "xlsx", "xls"], key=f"up_{section}", help=help_text
    )
    if uploaded is not None:
        data = uploaded.getvalue()
        if state.get_setup(f"{section}_bytes") != data:
            _reset_from(section)
            _clear_widget_state(WIDGET_RESET_ON_NEW_FILE[section])
            state.set_setup(f"{section}_bytes", data)
            state.set_setup(f"{section}_name", uploaded.name)
    return state.get_setup(f"{section}_bytes"), state.get_setup(f"{section}_name")


DOWNSTREAM: dict[str, list[str]] = {
    # editing X invalidates these confirmation flags (+ the bundle, always)
    "caseload": ["caseload_done", "report_done", "codes_done"],
    "report": ["report_done", "codes_done"],
    "codes": ["codes_done"],
}

#: Widget-state keys/prefixes to drop when a section's FILE changes — their
#: options belong to the old file. (Kept on plain "Edit" so choices survive.)
WIDGET_RESET_ON_NEW_FILE: dict[str, list[str]] = {
    "caseload": ["caseload_map_", "caseload_header_override", "caseload_sheet"],
    "report": [
        "report_map_", "report_header_override", "report_sheet",
        "report_shape_radio", "code_editor", "treat_unknown",
    ],
}


def _clear_widget_state(prefixes: list[str]) -> None:
    for key in list(st.session_state.keys()):
        if any(str(key).startswith(prefix) for prefix in prefixes):
            del st.session_state[key]


def _reset_from(section: str) -> None:
    state.clear_setup_from(DOWNSTREAM.get(section, []))


def _sheet_and_header(section: str, data: bytes, filename: str):
    """Sheet picker (multi-sheet Excel) + header-row override. Returns
    (sheet, header_row_or_None)."""
    sheet = None
    sheets = io_utils.list_sheets(data, filename)
    if len(sheets) > 1:
        sheet = st.selectbox(
            "Worksheet", sheets, key=f"{section}_sheet",
            help="This Excel file has multiple sheets — pick the one with the data.",
        )
    override = st.session_state.get(f"{section}_header_override")
    return sheet, override


def _header_override_widget(section: str, detected_row: int) -> None:
    with st.expander("Header row not right? Override it"):
        st.number_input(
            "Header row (0 = first row of the file)",
            min_value=0,
            max_value=39,
            value=detected_row,
            key=f"{section}_header_override",
            help="The row that contains the column names. Rows above it are ignored.",
        )


def _role_selectbox(
    label: str,
    columns: list[str],
    default: str | None,
    key: str,
    required: bool = False,
) -> str | None:
    options = ([] if required else [NONE_OPTION]) + columns
    if default in columns:
        index = options.index(default)
    else:
        index = 0 if required or default is None else 0
    choice = st.selectbox(label + (" *" if required else ""), options, index=index, key=key)
    return None if choice == NONE_OPTION else choice


# ---------------------------------------------------------------------------
# Section 1 — caseload
# ---------------------------------------------------------------------------


def _caseload_section() -> bool:
    st.subheader("1 · Your caseload")
    done = state.get_setup("caseload_done", False)
    if done:
        students = state.get_setup("students")
        name = state.get_setup("caseload_name")
        st.success(f"Caseload loaded: **{len(students)} students** from `{name}`.")
        components.warnings_panel(state.get_setup("students_warnings", []))
        if st.button("Edit caseload", key="edit_caseload"):
            _reset_from("caseload")
            st.rerun()
        return True

    data, filename = _uploaded_file(
        "caseload",
        "Caseload file (CSV or Excel)",
        "Your list of students. Needs a student ID column; name and grade are "
        "used when present. Extra columns become group-by options.",
    )
    if data is None:
        st.info(
            "Upload the list of students you work with. Only these students "
            "will be analyzed — the schoolwide report is filtered down to them.",
            icon="👥",
        )
        return False

    sheet, override = _sheet_and_header("caseload", data, filename)
    frame, result = _cached_detect_caseload(data, filename, sheet, override)
    _header_override_widget("caseload", result.header_row)
    components.warnings_panel(result.warnings)
    st.dataframe(frame.head(10), hide_index=True)

    columns = [str(c) for c in frame.columns]
    st.markdown("**Which column is which?**")
    col1, col2, col3 = st.columns(3)
    with col1:
        id_col = _role_selectbox(
            "Student ID", columns, result.mapping.get("student_id"),
            "caseload_map_id", required=True,
        )
    with col2:
        name_col = _role_selectbox(
            "Student name (single column)", columns, result.mapping.get("name"),
            "caseload_map_name",
        )
        grade_col = _role_selectbox(
            "Grade", columns, result.mapping.get("grade"), "caseload_map_grade"
        )
    with col3:
        last_col = _role_selectbox(
            "Last name", columns, result.mapping.get("last_name"), "caseload_map_last"
        )
        first_col = _role_selectbox(
            "First name", columns, result.mapping.get("first_name"), "caseload_map_first"
        )

    if st.button("Confirm caseload", type="primary", key="confirm_caseload"):
        mapping_columns = {"student_id": id_col}
        if name_col:
            mapping_columns["name"] = name_col
        if last_col and first_col:
            mapping_columns["last_name"] = last_col
            mapping_columns["first_name"] = first_col
        if grade_col:
            mapping_columns["grade"] = grade_col
        mapping = ColumnMapping(shape=Shape.UNKNOWN, columns=mapping_columns)
        students, warnings = normalize.build_students(frame, mapping)
        if students.empty:
            st.error("No students with a usable ID were found — check the ID column.")
            return False
        state.set_setup("students", students)
        state.set_setup("students_warnings", warnings)
        state.set_setup("caseload_done", True)
        st.rerun()
    return False


# ---------------------------------------------------------------------------
# Section 2 — attendance report
# ---------------------------------------------------------------------------


def _required_roles_ok(shape: Shape, chosen: dict[str, str | None]) -> str | None:
    """Returns an error message or None."""
    if not chosen.get("student_id"):
        return "A Student ID column is required."
    if shape in (Shape.DAILY, Shape.PERIOD):
        if not chosen.get("date"):
            return "A Date column is required for day-level reports."
        if not chosen.get("code"):
            return "An attendance-code column is required for day-level reports."
    if shape == Shape.PERIOD and not chosen.get("period"):
        return "A Period column is required for period-level reports."
    if shape == Shape.SUMMARY:
        value_roles = [
            "days_enrolled", "days_absent", "days_excused", "days_unexcused",
            "days_tardy", "attendance_pct",
        ]
        if not any(chosen.get(r) for r in value_roles):
            return (
                "A summary report needs at least one totals column "
                "(days enrolled / days absent / attendance %)."
            )
    return None


def _report_section() -> bool:
    st.subheader("2 · Schoolwide attendance report")
    done = state.get_setup("report_done", False)
    if done:
        shape = state.get_setup("report_shape")
        name = state.get_setup("report_name")
        frame = state.get_setup("report_frame")
        st.success(
            f"Report loaded: `{name}` — {SHAPE_LABELS[shape]}, "
            f"{len(frame):,} rows."
        )
        if st.button("Edit report", key="edit_report"):
            _reset_from("report")
            st.rerun()
        return True

    data, filename = _uploaded_file(
        "report",
        "Attendance report (CSV or Excel)",
        "The schoolwide export from your SIS (PowerSchool, Aeries, Infinite "
        "Campus, …). The app auto-detects the layout; you confirm it below.",
    )
    if data is None:
        st.info(
            "Upload the attendance report for the whole school — it will be "
            "filtered down to your caseload, and the rest is used only for the "
            "schoolwide baseline.",
            icon="🏫",
        )
        return False

    sheet, override = _sheet_and_header("report", data, filename)
    frame, result = _cached_detect_report(data, filename, sheet, override)
    _header_override_widget("report", result.header_row)

    confidence_icon = {"high": "✅", "medium": "🟡", "low": "⚠️"}.get(
        result.confidence, "⚠️"
    )
    if result.shape == Shape.UNKNOWN:
        st.warning(
            "Couldn't auto-detect this report's layout — pick it below and map "
            "the columns.",
            icon="⚠️",
        )
    else:
        st.markdown(
            f"{confidence_icon} **Detected: {SHAPE_LABELS[result.shape]}** "
            f"({result.confidence} confidence)"
        )
    components.warnings_panel(result.warnings)
    st.dataframe(frame.head(10), hide_index=True)

    shape_options = [Shape.DAILY, Shape.SUMMARY, Shape.PERIOD]
    default_index = (
        shape_options.index(result.shape) if result.shape in shape_options else None
    )
    shape = st.radio(
        "What does each row of this report represent?",
        shape_options,
        index=default_index,
        format_func=lambda s: SHAPE_LABELS[s],
        key="report_shape_radio",
    )
    if shape is None:
        return False

    columns = [str(c) for c in frame.columns]
    st.markdown("**Which column is which?**")
    chosen: dict[str, str | None] = {}
    if shape in (Shape.DAILY, Shape.PERIOD):
        roles_required = ["student_id", "date", "code"] + (
            ["period"] if shape == Shape.PERIOD else []
        )
        roles_optional = ["name", "grade"]
    else:
        roles_required = ["student_id"]
        roles_optional = [
            "days_enrolled", "days_absent", "days_tardy", "attendance_pct",
            "days_excused", "days_unexcused", "name", "grade",
        ]
    cols = st.columns(3)
    for i, role in enumerate(roles_required + roles_optional):
        with cols[i % 3]:
            chosen[role] = _role_selectbox(
                REPORT_ROLE_LABELS[role],
                columns,
                result.mapping.get(role),
                f"report_map_{role}",
                required=role in roles_required,
            )

    if st.button("Confirm report", type="primary", key="confirm_report"):
        error = _required_roles_ok(shape, chosen)
        if error:
            st.error(error)
            return False
        mapping = ColumnMapping(
            shape=shape,
            columns={role: col for role, col in chosen.items() if col},
        )
        state.set_setup("report_frame", frame)
        state.set_setup("report_mapping", mapping)
        state.set_setup("report_shape", shape)
        if shape == Shape.SUMMARY:
            state.set_setup("observed_codes", {})
            state.set_setup("codes_done", True)
        else:
            observed = detection.observed_code_counts(frame[chosen["code"]])
            state.set_setup("observed_codes", observed)
        state.set_setup("report_done", True)
        st.rerun()
    return False


# ---------------------------------------------------------------------------
# Section 3 — attendance codes
# ---------------------------------------------------------------------------


def _codes_section() -> bool:
    shape = state.get_setup("report_shape")
    if shape == Shape.SUMMARY:
        return True  # summary reports have no codes

    st.subheader("3 · What do the attendance codes mean?")
    done = state.get_setup("codes_done", False)
    if done:
        code_map: CodeMap = state.get_setup("code_map")
        n = len(code_map.codes)
        st.success(f"Code mapping confirmed ({n} codes).")
        if st.button("Edit code mapping", key="edit_codes"):
            _reset_from("codes")
            st.rerun()
        return True

    observed: dict[str, int] = state.get_setup("observed_codes", {})
    if not observed:
        st.error("No attendance codes found in the report's code column.")
        return False

    loaded = st.file_uploader(
        "Load a saved code-mapping JSON (optional)",
        type=["json"],
        key="up_codemap",
        help="Re-use the mapping you saved last time. It contains no student data.",
    )
    base_map = codes_mod.propose_code_map(observed)
    if loaded is not None:
        try:
            saved = codes_mod.code_map_from_json(loaded.getvalue().decode("utf-8"))
            for code, category in saved.codes.items():
                if code in base_map.codes:
                    base_map.codes[code] = category
            st.success("Saved mapping applied to the codes below.")
        except ValueError as exc:
            st.error(f"That mapping file couldn't be used: {exc}")

    editor_frame = pd.DataFrame(
        {
            "Code": list(observed.keys()),
            "Times seen": list(observed.values()),
            "Meaning": [
                CATEGORY_LABELS[base_map.codes.get(c, Category.UNKNOWN).value]
                for c in observed
            ],
        }
    ).sort_values("Times seen", ascending=False, ignore_index=True)

    edited = st.data_editor(
        editor_frame,
        column_config={
            "Code": st.column_config.TextColumn(disabled=True),
            "Times seen": st.column_config.NumberColumn(disabled=True),
            "Meaning": st.column_config.SelectboxColumn(
                options=list(CATEGORY_LABELS.values()), required=True
            ),
        },
        hide_index=True,
        key="code_editor",
    )

    edited_map = CodeMap(
        codes={
            str(row["Code"]): Category(LABEL_TO_CATEGORY[row["Meaning"]])
            for _, row in edited.iterrows()
        }
    )
    unknown = codes_mod.unknown_codes(edited_map, observed)
    ambiguous = codes_mod.ambiguous_codes(observed)
    if ambiguous:
        st.caption(
            f"⚠️ Code(s) {', '.join(ambiguous)}: in-school suspension is counted "
            "as **absent** by the federal chronic-absenteeism convention, but "
            "some schools count it present — double-check your school's policy."
        )
    treat_unknown = False
    if unknown:
        st.warning(
            f"Unrecognized code(s): **{', '.join(unknown)}** — set a meaning "
            "for each above, or use the checkbox to treat them as present-like.",
            icon="❓",
        )
        treat_unknown = st.checkbox(
            "Treat remaining unknown codes as present-like",
            key="treat_unknown",
            help="Unknown codes won't count as absences. Only use this if "
            "they're rare bookkeeping codes.",
        )

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("Confirm codes", type="primary", key="confirm_codes"):
            final_map = edited_map
            if unknown:
                if not treat_unknown:
                    st.error("There are still unknown codes — resolve them first.")
                    return False
                final_map = CodeMap(
                    codes={
                        c: (
                            Category.OTHER_PRESENT
                            if cat == Category.UNKNOWN
                            else cat
                        )
                        for c, cat in edited_map.codes.items()
                    }
                )
            state.set_setup("code_map", final_map)
            state.set_setup("codes_done", True)
            st.rerun()
    with col_b:
        st.download_button(
            "Download this mapping as JSON",
            data=codes_mod.code_map_to_json(edited_map),
            file_name="attendance_code_mapping.json",
            mime="application/json",
            key="dl_codemap",
        )
    return False


# ---------------------------------------------------------------------------
# Section 4 — match & finish
# ---------------------------------------------------------------------------


def _present_like_share(observed: dict[str, int], code_map: CodeMap) -> float:
    total = sum(observed.values())
    if total == 0:
        return 1.0
    present = sum(
        count
        for code, count in observed.items()
        if code_map.category_for(code) in PRESENT_LIKE_CATEGORIES
    )
    return present / total


def _finish_section() -> None:
    st.subheader("4 · Match & finish")
    students: pd.DataFrame = state.get_setup("students")
    frame: pd.DataFrame = state.get_setup("report_frame")
    mapping: ColumnMapping = state.get_setup("report_mapping")
    shape: Shape = state.get_setup("report_shape")
    code_map: CodeMap | None = state.get_setup("code_map")

    ignore_zeros = st.toggle(
        "Ignore leading zeros when matching IDs",
        value=True,
        key="ignore_zeros",
        help="Recommended: treats 004512 and 4512 as the same student. Turn "
        "off only if your school's IDs really differ by leading zeros.",
    )
    report_ids = normalize.normalize_id_series(
        frame[mapping.columns["student_id"]]
    ).dropna()
    join = joining.join_caseload(students, report_ids, force_exact=not ignore_zeros)
    components.warnings_panel(join.warnings)

    matched = int(join.students["matched"].sum())
    total = len(join.students)
    if matched == 0:
        st.error(
            "None of your caseload students were found in the report. Check "
            "that both files use the same student-ID system."
        )
    elif matched < total:
        st.warning(f"**{matched} of {total}** caseload students matched.")
    else:
        st.success(f"All **{total}** caseload students were found in the report.")
    if not join.unmatched.empty:
        st.dataframe(
            join.unmatched.rename(
                columns={"student_id": "Student ID", "name": "Name", "hint": "Hint"}
            ),
            hide_index=True,
        )
    st.caption(
        f"Schoolwide baseline will be computed from "
        f"{join.report_only_count + matched:,} students in the report."
    )

    enrolled_override = None
    threshold = DEFAULT_ABSENT_DAY_THRESHOLD
    if shape in (Shape.DAILY, Shape.PERIOD):
        observed = state.get_setup("observed_codes", {})
        share = _present_like_share(observed, code_map)
        if share < EXCEPTION_REPORT_PRESENT_SHARE:
            st.warning(
                "This report looks like an **absences-only** export (it has "
                "almost no 'present' rows), so total school days can't be "
                "counted from it. Enter how many school days there have been "
                "so far this year.",
                icon="📅",
            )
            enrolled_override = int(
                st.number_input(
                    "School days so far this year",
                    min_value=1,
                    max_value=260,
                    value=90,
                    key="enrolled_override",
                )
            )
        if shape == Shape.PERIOD:
            with st.expander("Advanced: what counts as an absent day?"):
                threshold = st.slider(
                    "A day counts as absent when at least this share of the "
                    "day's periods were missed",
                    min_value=0.1,
                    max_value=1.0,
                    value=DEFAULT_ABSENT_DAY_THRESHOLD,
                    step=0.05,
                    key="absent_threshold",
                    help="The federal chronic-absenteeism convention uses 50%.",
                )

    if st.button("Finish setup", type="primary", key="finish_setup"):
        with st.spinner("Crunching the numbers…"):
            bundle, warnings = pipeline.assemble_bundle(
                report_frame=frame,
                report_mapping=mapping,
                code_map=code_map,
                force_exact=not ignore_zeros,
                absent_day_threshold=threshold,
                enrolled_override=enrolled_override,
                prebuilt_students=students,
            )
        state.set_bundle(bundle, warnings)
        overview = st.session_state.get("_pages", {}).get("overview")
        if overview is not None:
            st.switch_page(overview)
        st.rerun()


# ---------------------------------------------------------------------------


def render() -> None:
    st.title("📥 Upload & Setup")
    st.caption(
        "Everything runs locally and stays in memory — uploaded student data "
        "is never written to disk or sent anywhere."
    )
    if state.bundle() is not None:
        st.success(
            "Setup is complete — the analysis pages are in the sidebar. "
            "Upload a different file below at any time."
        )
    if _caseload_section():
        st.divider()
        if _report_section():
            st.divider()
            if _codes_section():
                st.divider()
                _finish_section()
    st.divider()
    if st.button("Start over (clear all uploaded data)", key="start_over"):
        state.clear_all()
        st.rerun()
