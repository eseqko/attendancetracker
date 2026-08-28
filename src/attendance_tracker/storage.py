"""Optional local persistence: remember uploads and settings between launches.

Everything lives in a ``local_data/`` folder next to the app (gitignored, never
synced or committed). ``profile.json`` holds only settings — column mappings,
the code map, toggles, filenames, a saved-on date. The student data itself is
byte-for-byte copies of the user's own uploaded files (``<slot>.bin``), written
only when the user turns on "Remember on this computer" and erased by "Forget
saved data". Loading is deliberately forgiving: anything unexpected returns
``None`` so the app falls back to the normal upload wizard.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path

from .constants import Shape
from .model import CodeMap, ColumnMapping
from .codes import code_map_from_json, code_map_to_json

PROFILE_VERSION = 1
PROFILE_FILENAME = "profile.json"
FILE_SLOTS = ("caseload", "report", "course")
UI_PREFS_FILENAME = "ui_prefs.json"


def default_dir() -> Path:
    """The save location: local_data/ under the app's working directory."""
    return Path.cwd() / "local_data"


def load_ui_prefs(directory: Path | None = None) -> dict:
    """UI preferences (menu position, …) — settings only, never student data.

    Kept separate from the profile so they survive "Forget saved data" and
    exist even when the user never opts into remembering uploads.
    """
    directory = default_dir() if directory is None else Path(directory)
    try:
        data = json.loads((directory / UI_PREFS_FILENAME).read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_ui_prefs(prefs: dict, directory: Path | None = None) -> None:
    directory = default_dir() if directory is None else Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / UI_PREFS_FILENAME).write_text(
        json.dumps(prefs, indent=2), "utf-8"
    )


@dataclass
class SavedProfile:
    saved_on: str
    files: dict[str, tuple[bytes, str]]  # slot -> (bytes, original filename)
    caseload_mapping: ColumnMapping
    report_mapping: ColumnMapping
    course_mapping: ColumnMapping | None = None
    code_map: CodeMap | None = None
    settings: dict = field(default_factory=dict)


def _mapping_to_json(mapping: ColumnMapping) -> dict:
    return {"shape": mapping.shape.value, "columns": dict(mapping.columns)}


def _mapping_from_json(payload: dict) -> ColumnMapping:
    return ColumnMapping(
        shape=Shape(payload["shape"]),
        columns={str(k): str(v) for k, v in payload["columns"].items()},
    )


def save_profile(
    directory: Path | None = None,
    *,
    files: dict[str, tuple[bytes, str]],
    caseload_mapping: ColumnMapping,
    report_mapping: ColumnMapping,
    course_mapping: ColumnMapping | None = None,
    code_map: CodeMap | None = None,
    settings: dict | None = None,
) -> None:
    """Write the profile. ``files`` maps slots ('caseload'/'report'/'course')
    to (bytes, original filename); missing slots are simply absent."""
    directory = default_dir() if directory is None else Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": PROFILE_VERSION,
        "saved_on": dt.date.today().isoformat(),
        "files": {slot: name for slot, (_, name) in files.items()},
        "caseload_mapping": _mapping_to_json(caseload_mapping),
        "report_mapping": _mapping_to_json(report_mapping),
        "course_mapping": (
            _mapping_to_json(course_mapping) if course_mapping is not None else None
        ),
        "code_map": (
            json.loads(code_map_to_json(code_map)) if code_map is not None else None
        ),
        "settings": settings or {},
    }
    for slot in FILE_SLOTS:
        blob = directory / f"{slot}.bin"
        if slot in files:
            blob.write_bytes(files[slot][0])
        elif blob.exists():
            blob.unlink()
    (directory / PROFILE_FILENAME).write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )


def load_profile(directory: Path | None = None) -> SavedProfile | None:
    """Read a saved profile, or None when absent, incompatible, or corrupt."""
    directory = default_dir() if directory is None else Path(directory)
    try:
        payload = json.loads(
            (directory / PROFILE_FILENAME).read_text(encoding="utf-8")
        )
        if payload.get("version") != PROFILE_VERSION:
            return None
        files: dict[str, tuple[bytes, str]] = {}
        for slot, name in payload["files"].items():
            files[slot] = ((directory / f"{slot}.bin").read_bytes(), str(name))
        if "caseload" not in files or "report" not in files:
            return None
        code_map = None
        if payload.get("code_map") is not None:
            code_map = code_map_from_json(json.dumps(payload["code_map"]))
        course_mapping = None
        if payload.get("course_mapping") is not None:
            course_mapping = _mapping_from_json(payload["course_mapping"])
        return SavedProfile(
            saved_on=str(payload.get("saved_on", "")),
            files=files,
            caseload_mapping=_mapping_from_json(payload["caseload_mapping"]),
            report_mapping=_mapping_from_json(payload["report_mapping"]),
            course_mapping=course_mapping,
            code_map=code_map,
            settings=dict(payload.get("settings", {})),
        )
    except Exception:
        return None


def has_profile(directory: Path | None = None) -> bool:
    directory = default_dir() if directory is None else Path(directory)
    return (directory / PROFILE_FILENAME).exists()


def clear_profile(directory: Path | None = None) -> None:
    """Erase the saved profile and every saved file copy."""
    directory = default_dir() if directory is None else Path(directory)
    if not directory.exists():
        return
    for name in [PROFILE_FILENAME, *(f"{slot}.bin" for slot in FILE_SLOTS)]:
        target = directory / name
        if target.exists():
            target.unlink()
