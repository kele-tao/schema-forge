"""Tests for the schema diff classifier and its migration guidance."""

from __future__ import annotations

import copy
import json
import pathlib

from schema_forge import diff_schemas, infer_file

BASE = {
    "title": "base",
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "status"],
    "properties": {
        "id": {"type": "integer"},
        "status": {"type": "string", "enum": ["new", "shipped"]},
        "amount": {"type": "number"},
    },
}


def write_schema(path: pathlib.Path, payload: dict) -> pathlib.Path:
    """Write a schema document to path."""
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def mutate(**changes: object) -> dict:
    """Return a deep copy of BASE with top-level keys replaced."""
    payload = copy.deepcopy(BASE)
    payload.update(changes)
    return payload


def test_identical_schemas_have_no_changes(tmp_path: pathlib.Path) -> None:
    old = write_schema(tmp_path / "a.json", BASE)
    new = write_schema(tmp_path / "b.json", BASE)
    result = diff_schemas(old, new)
    assert result.changes == []
    assert result.ok


def test_integer_to_number_is_compatible(tmp_path: pathlib.Path) -> None:
    old = write_schema(tmp_path / "a.json", BASE)
    widened = copy.deepcopy(BASE)
    widened["properties"]["id"]["type"] = "number"
    new = write_schema(tmp_path / "b.json", widened)
    result = diff_schemas(old, new)
    assert result.ok
    assert [change.kind for change in result.changes] == ["type-widened"]


def test_number_to_integer_is_breaking(tmp_path: pathlib.Path) -> None:
    old = write_schema(tmp_path / "a.json", BASE)
    narrowed = copy.deepcopy(BASE)
    narrowed["properties"]["amount"]["type"] = "integer"
    new = write_schema(tmp_path / "b.json", narrowed)
    result = diff_schemas(old, new)
    assert not result.ok
    assert result.breaking[0].kind == "type-narrowed"


def test_optional_to_required_is_breaking(tmp_path: pathlib.Path) -> None:
    old = write_schema(tmp_path / "a.json", BASE)
    strict = mutate(required=["id", "status", "amount"])
    new = write_schema(tmp_path / "b.json", strict)
    result = diff_schemas(old, new)
    assert not result.ok
    assert result.breaking[0].kind == "required-flip"


def test_required_to_optional_is_compatible(tmp_path: pathlib.Path) -> None:
    old = write_schema(tmp_path / "a.json", BASE)
    new = write_schema(tmp_path / "b.json", mutate(required=["id"]))
    result = diff_schemas(old, new)
    assert result.ok
    assert result.compatible[0].kind == "required-flip"


def test_enum_shrink_is_breaking(tmp_path: pathlib.Path) -> None:
    old = write_schema(tmp_path / "a.json", BASE)
    shrunk = copy.deepcopy(BASE)
    shrunk["properties"]["status"]["enum"] = ["new"]
    new = write_schema(tmp_path / "b.json", shrunk)
    result = diff_schemas(old, new)
    assert not result.ok
    assert result.breaking[0].kind == "enum-shrunk"
    assert "shipped" in result.breaking[0].message


def test_enum_growth_is_compatible(tmp_path: pathlib.Path) -> None:
    old = write_schema(tmp_path / "a.json", BASE)
    grown = copy.deepcopy(BASE)
    grown["properties"]["status"]["enum"] = ["new", "shipped", "returned"]
    new = write_schema(tmp_path / "b.json", grown)
    result = diff_schemas(old, new)
    assert result.ok
    assert result.compatible[0].kind == "enum-grew"


def test_removed_required_column_is_breaking(tmp_path: pathlib.Path) -> None:
    old = write_schema(tmp_path / "a.json", BASE)
    removed = copy.deepcopy(BASE)
    del removed["properties"]["id"]
    removed["required"] = ["status"]
    new = write_schema(tmp_path / "b.json", removed)
    result = diff_schemas(old, new)
    assert any(
        change.kind == "column-removed" and change.severity == "breaking"
        for change in result.changes
    )


def test_new_required_column_is_breaking(tmp_path: pathlib.Path) -> None:
    old = write_schema(tmp_path / "a.json", BASE)
    added = copy.deepcopy(BASE)
    added["properties"]["currency"] = {"type": "string"}
    added["required"] = ["currency", "id", "status"]
    new = write_schema(tmp_path / "b.json", added)
    result = diff_schemas(old, new)
    assert any(
        change.kind == "column-added" and change.severity == "breaking" for change in result.changes
    )


def test_pattern_added_is_breaking(tmp_path: pathlib.Path) -> None:
    old = write_schema(tmp_path / "a.json", BASE)
    patterned = copy.deepcopy(BASE)
    patterned["properties"]["status"]["pattern"] = "^[a-z]+$"
    new = write_schema(tmp_path / "b.json", patterned)
    result = diff_schemas(old, new)
    assert any(
        change.kind == "pattern-added" and change.severity == "breaking"
        for change in result.changes
    )


def test_additional_properties_tightened_is_breaking(tmp_path: pathlib.Path) -> None:
    old = write_schema(tmp_path / "a.json", mutate(additionalProperties=True))
    new = write_schema(tmp_path / "b.json", BASE)
    result = diff_schemas(old, new)
    assert any(change.kind == "unknown-columns-rejected" for change in result.changes)


def test_diff_of_real_contracts(orders_csv: pathlib.Path, tmp_path: pathlib.Path) -> None:
    schema = infer_file(orders_csv).contract.to_schema()
    old = write_schema(tmp_path / "v1.json", schema)
    payload = copy.deepcopy(schema)
    payload["properties"]["qty"]["type"] = "string"
    payload["required"] = [name for name in payload["required"] if name != "qty"]
    new = write_schema(tmp_path / "v2.json", payload)
    result = diff_schemas(old, new)
    assert not result.ok
    assert any(change.column == "qty" for change in result.breaking)


def test_json_rendering_of_diff(orders_csv: pathlib.Path, tmp_path: pathlib.Path) -> None:
    schema = infer_file(orders_csv).contract.to_schema()
    old = write_schema(tmp_path / "v1.json", schema)
    payload = copy.deepcopy(schema)
    payload["properties"]["qty"]["type"] = "string"
    payload["required"] = [name for name in payload["required"] if name != "qty"]
    new = write_schema(tmp_path / "v2.json", payload)
    payload_json = diff_schemas(old, new).to_json()
    assert payload_json["ok"] is False
    assert payload_json["breaking"] >= 1
    assert payload_json["changes"][0]["guidance"]
