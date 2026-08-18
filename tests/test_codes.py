"""Tests for code-map proposal, review flags, and JSON persistence."""

from __future__ import annotations

import json

import pytest

from attendance_tracker.codes import (
    ambiguous_codes,
    code_map_from_json,
    code_map_to_json,
    propose_code_map,
    unknown_codes,
)
from attendance_tracker.constants import Category


def test_propose_code_map_defaults_and_unknown():
    code_map = propose_code_map({"A": 10, "E": 5, "T": 2, "Q": 1})
    assert code_map.codes["A"] is Category.ABSENT_UNEXCUSED
    assert code_map.codes["E"] is Category.ABSENT_EXCUSED
    assert code_map.codes["T"] is Category.TARDY
    assert code_map.codes["Q"] is Category.UNKNOWN
    assert code_map.version == 1


def test_propose_code_map_normalizes_case_and_whitespace():
    code_map = propose_code_map({" a ": 3, "iss": 1})
    assert code_map.codes["A"] is Category.ABSENT_UNEXCUSED
    assert code_map.codes["ISS"] is Category.ABSENT_UNEXCUSED


def test_suspension_codes_map_to_absent_unexcused():
    code_map = propose_code_map({"OSS": 1, "ISS": 2, "SUS": 3})
    for code in ("OSS", "ISS", "SUS"):
        assert code_map.codes[code] is Category.ABSENT_UNEXCUSED


def test_unknown_codes_sorted_by_descending_count():
    observed = {"Q": 1, "ZZ": 9, "A": 4}
    code_map = propose_code_map(observed)
    assert unknown_codes(code_map, observed) == ["ZZ", "Q"]


def test_ambiguous_codes_flags_iss():
    assert ambiguous_codes({"ISS": 3, "A": 10}) == ["ISS"]
    assert ambiguous_codes({"A": 10, "E": 2}) == []


def test_json_round_trip_exact():
    original = propose_code_map({"A": 3, "E": 2, "Q": 1})
    text = code_map_to_json(original)

    payload = json.loads(text)
    assert payload["version"] == 1
    assert payload["codes"] == {
        "A": "absent_unexcused",
        "E": "absent_excused",
        "Q": "unknown",
    }

    restored = code_map_from_json(text)
    assert restored.codes == original.codes
    assert restored.version == 1
    # serialization is stable: re-serializing yields the identical string
    assert code_map_to_json(restored) == text


def test_from_json_rejects_bad_version():
    with pytest.raises(ValueError, match="version"):
        code_map_from_json(json.dumps({"version": 2, "codes": {}}))
    with pytest.raises(ValueError, match="version"):
        code_map_from_json(json.dumps({"codes": {"A": "tardy"}}))


def test_from_json_rejects_bad_category_value():
    text = json.dumps({"version": 1, "codes": {"A": "vanished"}})
    with pytest.raises(ValueError, match="vanished"):
        code_map_from_json(text)


def test_from_json_rejects_non_json_text():
    with pytest.raises(ValueError, match="JSON"):
        code_map_from_json("this is not json")


def test_from_json_normalizes_codes_on_load():
    text = json.dumps({"version": 1, "codes": {" a ": "absent_unexcused"}})
    restored = code_map_from_json(text)
    assert restored.codes == {"A": Category.ABSENT_UNEXCUSED}
