"""Tests for JSON Schema and lock-file emission."""

from __future__ import annotations

import json
import pathlib

from schema_forge import infer_file
from schema_forge.types import DIALECT, LOCKFILE_VERSION, enforcement_from_schema, hash_enforcement


def test_schema_is_draft_2020_12(orders_csv: pathlib.Path) -> None:
    schema = infer_file(orders_csv, name="orders").contract.to_schema()
    assert schema["$schema"] == DIALECT
    assert schema["type"] == "object"
    assert schema["title"] == "orders"
    assert schema["additionalProperties"] is False


def test_schema_maps_types(orders_csv: pathlib.Path) -> None:
    schema = infer_file(orders_csv).contract.to_schema()
    props = schema["properties"]
    assert props["id"]["type"] == "integer"
    assert props["email"]["format"] == "email"
    assert props["active"]["type"] == "boolean"
    assert props["created"]["format"] == "date"
    assert props["country"]["enum"] == ["DE", "FR", "US"]


def test_schema_carries_confidence_metadata(orders_csv: pathlib.Path) -> None:
    schema = infer_file(orders_csv).contract.to_schema()
    payload = schema["properties"]["amount"]["x-schema-forge"]
    assert payload["type"] == "currency"
    assert 0.0 < payload["confidence"] <= 1.0
    assert set(payload["confidence_parts"]) == {
        "fill_rate",
        "type_support",
        "specificity",
        "sample_depth",
    }
    assert payload["evidence"]


def test_nullable_columns_are_not_required(orders_csv: pathlib.Path) -> None:
    schema = infer_file(orders_csv).contract.to_schema()
    assert "email" not in schema["required"]
    assert "id" in schema["required"]


def test_required_list_is_a_subset_of_properties(orders_csv: pathlib.Path) -> None:
    schema = infer_file(orders_csv).contract.to_schema()
    assert set(schema["required"]) <= set(schema["properties"])


def test_lock_document_shape(orders_csv: pathlib.Path) -> None:
    lock = infer_file(orders_csv).contract.to_lock()
    assert lock["lockfile_version"] == LOCKFILE_VERSION
    assert len(lock["contract_sha256"]) == 64
    assert lock["enforcement"]["additionalProperties"] is False
    assert lock["rows"] == 40


def test_enforcement_round_trips_from_schema(orders_csv: pathlib.Path) -> None:
    contract = infer_file(orders_csv).contract
    schema = contract.to_schema()
    assert enforcement_from_schema(schema) == contract.enforcement()
    assert hash_enforcement(enforcement_from_schema(schema)) == contract.contract_hash()


def test_schema_is_json_serialisable(orders_csv: pathlib.Path) -> None:
    schema = infer_file(orders_csv).contract.to_schema()
    rendered = json.dumps(schema)
    assert json.loads(rendered)["title"] == "orders.csv".removesuffix(".csv")


def test_schema_title_defaults_to_file_stem(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "invoices.csv"
    path.write_text("a\n1\n2\n3\n", encoding="utf-8")
    assert infer_file(path).contract.to_schema()["title"] == "invoices"
