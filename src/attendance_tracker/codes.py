"""Attendance-code mapping: default proposal, review flags, JSON persistence.

The setup wizard shows the proposed map for confirmation; confirmed maps can
be saved/reloaded as JSON so a case manager only maps their SIS's codes once.
"""

from __future__ import annotations

import json

from .constants import AMBIGUOUS_CODES, DEFAULT_CODE_MAP, Category
from .model import CodeMap


def _canon(code: str) -> str:
    return str(code).strip().upper()


def _by_count_desc(observed: dict[str, int], codes: list[str]) -> list[str]:
    return sorted(codes, key=lambda code: (-observed[code], str(code)))


def propose_code_map(observed: dict[str, int]) -> CodeMap:
    """Propose categories for observed codes from DEFAULT_CODE_MAP.

    Lookup is case-insensitive and whitespace-stripped; unrecognized codes
    map to Category.UNKNOWN so the UI can ask about them.
    """
    codes: dict[str, Category] = {}
    for code in observed:
        key = _canon(code)
        codes[key] = DEFAULT_CODE_MAP.get(key, Category.UNKNOWN)
    return CodeMap(codes=codes)


def unknown_codes(code_map: CodeMap, observed: dict[str, int]) -> list[str]:
    """Observed codes mapping to Category.UNKNOWN, most frequent first."""
    flagged = [
        code
        for code in observed
        if code_map.category_for(code) is Category.UNKNOWN
    ]
    return _by_count_desc(observed, flagged)


def ambiguous_codes(observed: dict[str, int]) -> list[str]:
    """Observed codes in constants.AMBIGUOUS_CODES, most frequent first."""
    flagged = [code for code in observed if _canon(code) in AMBIGUOUS_CODES]
    return _by_count_desc(observed, flagged)


def code_map_to_json(code_map: CodeMap) -> str:
    """Serialize a CodeMap to versioned JSON with stable (sorted) key order."""
    payload = {
        "version": code_map.version,
        "codes": {
            code: category.value
            for code, category in sorted(code_map.codes.items())
        },
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def code_map_from_json(text: str) -> CodeMap:
    """Parse and validate a saved code map; raise ValueError on any problem.

    Requires a JSON object with a 'version' key equal to 1 and a 'codes'
    object whose values are valid Category values. Codes are upper-cased and
    stripped on load.
    """
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Saved code map is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(
            "Saved code map must be a JSON object with 'version' and 'codes'."
        )
    if "version" not in payload:
        raise ValueError("Saved code map is missing the 'version' key.")
    if payload["version"] != 1:
        raise ValueError(
            f"Unsupported code map version {payload['version']!r}; expected 1."
        )
    raw_codes = payload.get("codes")
    if not isinstance(raw_codes, dict):
        raise ValueError("Saved code map must contain a 'codes' object.")
    codes: dict[str, Category] = {}
    for code, value in raw_codes.items():
        try:
            category = Category(value)
        except ValueError:
            valid = ", ".join(sorted(c.value for c in Category))
            raise ValueError(
                f"Code {code!r} maps to unknown category {value!r}; "
                f"valid categories: {valid}."
            ) from None
        codes[_canon(code)] = category
    return CodeMap(codes=codes, version=1)
