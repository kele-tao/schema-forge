"""Tests for the validator: locators, limits, sampling, strict mode, lock drift."""

from __future__ import annotations

import json
import pathlib

import pytest

from schema_forge import infer_file, load_schema, validate_file
from schema_forge.validate import SchemaError, check_lock


@pytest.fixture()
def schema_path(orders_csv: pathlib.Path, tmp_path: pathlib.Path) -> pathlib.Path:
    contract = infer_file(orders_csv).contract
    path = tmp_path / "orders.schema.json"
    path.write_text(json.dumps(contract.to_schema()), encoding="utf-8")
    return path


def test_clean_file_passes(orders_csv: pathlib.Path, schema_path: pathlib.Path) -> None:
    report = validate_file(orders_csv, load_schema(schema_path))
    assert report.ok
    assert report.violations == []
    assert report.rows == 40


def test_type_violation_has_row_locator(tmp_path: pathlib.Path, schema_path: pathlib.Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text(
        "id,email,country,amount,qty,active,created\n"
        "1,a@example.com,US,$1.00,5,true,2026-01-01\n"
        "oops,b@example.com,US,$1.00,6,true,2026-01-02\n",
        encoding="utf-8",
    )
    report = validate_file(path, load_schema(schema_path))
    assert not report.ok
    first = report.violations[0]
    assert first.location == "row 3"
    assert first.column == "id"
    assert "expected integer" in first.message


def test_enum_violation_message_lists_values(
    tmp_path: pathlib.Path, schema_path: pathlib.Path
) -> None:
    path = tmp_path / "bad.csv"
    path.write_text(
        "id,email,country,amount,qty,active,created\n1,a@example.com,us,$1.00,5,true,2026-01-01\n",
        encoding="utf-8",
    )
    report = validate_file(path, load_schema(schema_path))
    assert any("is not one of" in violation.message for violation in report.violations)


def test_required_column_empty_is_a_violation(
    tmp_path: pathlib.Path, schema_path: pathlib.Path
) -> None:
    path = tmp_path / "bad.csv"
    path.write_text(
        "id,email,country,amount,qty,active,created\n,a@example.com,US,$1.00,5,true,2026-01-01\n",
        encoding="utf-8",
    )
    report = validate_file(path, load_schema(schema_path))
    assert any("required column is empty" in violation.message for violation in report.violations)


def test_strict_mode_rejects_unknown_columns(
    tmp_path: pathlib.Path, schema_path: pathlib.Path
) -> None:
    path = tmp_path / "extra.csv"
    path.write_text(
        "id,email,country,amount,qty,active,created,extra\n"
        "1,a@example.com,US,$1.00,5,true,2026-01-01,boom\n",
        encoding="utf-8",
    )
    strict = validate_file(path, load_schema(schema_path), strict=True)
    assert not strict.ok
    assert strict.unknown_columns == ["extra"]
    lenient = validate_file(path, load_schema(schema_path), strict=False)
    assert lenient.ok


def test_max_errors_truncates(tmp_path: pathlib.Path, schema_path: pathlib.Path) -> None:
    lines = ["id,email,country,amount,qty,active,created"]
    for _index in range(10):
        lines.append("nope,a@example.com,US,$1.00,5,true,2026-01-01")
    path = tmp_path / "many.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = validate_file(path, load_schema(schema_path), max_errors=3)
    assert report.violation_count == 10
    assert len(report.violations) == 3
    assert report.truncated is True


def test_sample_validates_a_subset(orders_csv: pathlib.Path, tmp_path: pathlib.Path) -> None:
    contract = infer_file(orders_csv).contract
    schema = tmp_path / "s.json"
    schema.write_text(json.dumps(contract.to_schema()), encoding="utf-8")
    path = tmp_path / "mixed.csv"
    lines = ["id,email,country,amount,qty,active,created"]
    for index in range(10):
        good = "1" if index % 2 == 0 else "oops"
        lines.append(f"{good},a@example.com,US,$1.00,5,true,2026-01-01")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    sampled = validate_file(path, load_schema(schema), sample=0.5)
    assert sampled.sampled_rows < sampled.rows
    assert all(
        violation.location in {"row %d" % row for row in range(2, 12)}
        for violation in sampled.violations
    )


def test_missing_schema_file_raises(tmp_path: pathlib.Path) -> None:
    with pytest.raises(SchemaError) as excinfo:
        load_schema(tmp_path / "absent.json")
    assert "no such schema" in str(excinfo.value)


def test_malformed_schema_raises(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(SchemaError) as excinfo:
        load_schema(path)
    assert "invalid JSON" in str(excinfo.value)


def test_schema_without_properties_raises(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "empty.json"
    path.write_text(json.dumps({"type": "object"}), encoding="utf-8")
    with pytest.raises(SchemaError) as excinfo:
        load_schema(path)
    assert "properties" in str(excinfo.value)


def test_schema_with_bad_pattern_raises(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "badpat.json"
    path.write_text(
        json.dumps({"properties": {"a": {"type": "string", "pattern": "("}}}), encoding="utf-8"
    )
    with pytest.raises(SchemaError) as excinfo:
        load_schema(path)
    assert "invalid pattern" in str(excinfo.value)


def test_schema_with_unknown_format_raises(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "badfmt.json"
    path.write_text(
        json.dumps({"properties": {"a": {"type": "string", "format": "hostname"}}}),
        encoding="utf-8",
    )
    with pytest.raises(SchemaError) as excinfo:
        load_schema(path)
    assert "unsupported format" in str(excinfo.value)


def test_lock_matches_and_detects_drift(
    orders_csv: pathlib.Path, schema_path: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    contract = infer_file(orders_csv).contract
    lock = tmp_path / "schema.lock.json"
    lock.write_text(json.dumps(contract.to_lock()), encoding="utf-8")
    spec = load_schema(schema_path)
    assert check_lock(spec, lock)[0] == "ok"
    payload = json.loads(schema_path.read_text(encoding="utf-8"))
    payload["properties"]["id"]["type"] = "string"
    drifted = tmp_path / "drifted.json"
    drifted.write_text(json.dumps(payload), encoding="utf-8")
    status, detail = check_lock(load_schema(drifted), lock)
    assert status == "drift"
    assert "does not match" in detail


def test_lock_missing_reports_missing(schema_path: pathlib.Path, tmp_path: pathlib.Path) -> None:
    status, detail = check_lock(load_schema(schema_path), tmp_path / "none.lock.json")
    assert status == "missing"
    assert "not found" in detail
