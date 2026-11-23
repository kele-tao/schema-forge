"""Tests for the inference engine: types, confidence, enums, PII, streaming."""

from __future__ import annotations

import json
import pathlib

import pytest

from conftest import write_csv
from schema_forge import Options, infer_file
from schema_forge.reader import InputError
from schema_forge.types import canonical_json


def test_infers_core_types(orders_csv: pathlib.Path) -> None:
    result = infer_file(orders_csv)
    kinds = {column.name: column.kind for column in result.contract.columns}
    assert kinds["id"] == "int"
    assert kinds["email"] == "email"
    assert kinds["country"] == "enum"
    assert kinds["amount"] == "currency"
    assert kinds["qty"] == "int"
    assert kinds["active"] == "bool"
    assert kinds["created"] == "date"
    assert result.rows == 40


def test_confidence_is_product_of_parts(orders_csv: pathlib.Path) -> None:
    result = infer_file(orders_csv)
    column = result.contract.column("id")
    assert column is not None
    parts = column.confidence_parts
    product = 1.0
    for value in parts.values():
        product *= value
    assert column.confidence == pytest.approx(round(product, 2), abs=0.01)
    assert column.confidence > 0.9


def test_nullability_and_null_ratio(orders_csv: pathlib.Path) -> None:
    result = infer_file(orders_csv)
    email = result.contract.column("email")
    assert email is not None
    assert email.nullable is True
    assert email.nulls == 2
    assert email.null_ratio == pytest.approx(0.05)
    assert "email" not in result.contract.required_names()


def test_required_columns_are_never_null(orders_csv: pathlib.Path) -> None:
    result = infer_file(orders_csv)
    required = result.contract.required_names()
    assert "id" in required
    assert "email" not in required


def test_numeric_stats(tmp_path: pathlib.Path) -> None:
    path = write_csv(
        tmp_path / "nums.csv",
        ["n"],
        [[str(value)] for value in (5, 10, 15, 20, 25, 30)],
    )
    result = infer_file(path)
    column = result.contract.column("n")
    assert column is not None
    assert column.stats["min"] == 5
    assert column.stats["max"] == 30
    assert column.stats["mean"] == 17.5


def test_float_column_wins_over_int(tmp_path: pathlib.Path) -> None:
    path = write_csv(tmp_path / "f.csv", ["x"], [["1"], ["2"], ["3.5"], ["4"]])
    column = infer_file(path).contract.column("x")
    assert column is not None and column.kind == "float"


def test_enum_detection_with_threshold(tmp_path: pathlib.Path) -> None:
    rows = [[value] for value in ["red", "green", "blue"] * 10]
    path = write_csv(tmp_path / "enum.csv", ["colour"], rows)
    column = infer_file(path).contract.column("colour")
    assert column is not None
    assert column.kind == "enum"
    assert column.enum_values == ["blue", "green", "red"]


def test_high_cardinality_text_stays_text(tmp_path: pathlib.Path) -> None:
    rows = [[("value-%04d" % index)] for index in range(60)]
    path = write_csv(tmp_path / "text.csv", ["token"], rows)
    column = infer_file(path).contract.column("token")
    assert column is not None
    assert column.kind == "text"


def test_enum_typo_detection(tmp_path: pathlib.Path) -> None:
    rows = []
    for index in range(60):
        rows.append(["shipped"] if index % 6 else ["shiped"])
    rows.extend([["pending"], ["pending"], ["cancelled"]])
    path = write_csv(tmp_path / "typo.csv", ["status"], rows)
    column = infer_file(path).contract.column("status")
    assert column is not None
    assert column.enum_typos.get("shiped") == "shipped"


def test_mixed_date_formats_are_recorded(tmp_path: pathlib.Path) -> None:
    rows = [["2026-01-%02d" % day] for day in range(1, 21)]
    rows += [["%02d/01/2026" % day] for day in range(1, 21)]
    path = write_csv(tmp_path / "dates.csv", ["created"], rows)
    column = infer_file(path).contract.column("created")
    assert column is not None
    assert column.kind == "date"
    assert len(column.formats) > 1
    assert any("mixed date formats" in note for note in column.notes)


def test_pii_card_detection_and_masking(tmp_path: pathlib.Path) -> None:
    rows = [["4242 4242 4242 4242"]] * 30
    path = write_csv(tmp_path / "cards.csv", ["card"], rows)
    column = infer_file(path).contract.column("card")
    assert column is not None
    assert column.pii is not None
    assert column.pii.kind == "card"
    assert "4242" in column.pii.mask_example
    assert column.pii.mask_example != "4242 4242 4242 4242"


def test_pii_can_be_disabled(tmp_path: pathlib.Path) -> None:
    rows = [["ada@example.com"]] * 30
    path = write_csv(tmp_path / "emails.csv", ["email"], rows)
    column = infer_file(path, options=Options(detect_pii=False)).contract.column("email")
    assert column is not None
    assert column.pii is None


def test_date_column_is_not_reported_as_phone(tmp_path: pathlib.Path) -> None:
    rows = [["2026-06-%02d" % day] for day in range(1, 29)]
    path = write_csv(tmp_path / "d.csv", ["day"], rows)
    column = infer_file(path).contract.column("day")
    assert column is not None
    assert column.pii is None


def test_pattern_induction_for_structured_text(tmp_path: pathlib.Path) -> None:
    rows = [["ORD-%05d" % index] for index in range(5, 60)]
    path = write_csv(tmp_path / "ids.csv", ["order_id"], rows)
    column = infer_file(path).contract.column("order_id")
    assert column is not None
    assert column.kind == "text"
    assert column.pattern is not None
    assert column.pattern.startswith("^") and column.pattern.endswith("$")


def test_jsonl_input(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "rows.jsonl"
    lines = [
        json.dumps({"id": index, "name": "user%d" % index, "active": index % 2 == 0})
        for index in range(1, 31)
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = infer_file(path)
    kinds = {column.name: column.kind for column in result.contract.columns}
    assert kinds["id"] == "int"
    assert kinds["active"] == "bool"
    assert result.format == "jsonl"


def test_json_array_input(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "rows.json"
    path.write_text(
        json.dumps([{"id": index, "score": index / 2} for index in range(1, 31)]),
        encoding="utf-8",
    )
    result = infer_file(path)
    assert result.format == "json"
    assert result.contract.column("score") is not None


def test_unicode_values_survive_round_trip(tmp_path: pathlib.Path) -> None:
    rows = [["张伟", "祝您购物愉快 🙂"]] * 20
    path = write_csv(tmp_path / "cjk.csv", ["name", "note"], rows)
    result = infer_file(path)
    column = result.contract.column("name")
    assert column is not None
    assert column.distinct == 1
    assert "张伟" in json.dumps(result.contract.to_schema(), ensure_ascii=False)


def test_empty_file_raises_readable_error(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")
    with pytest.raises(InputError):
        infer_file(path)


def test_header_only_file_raises_readable_error(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "header.csv"
    path.write_text("a,b,c\n", encoding="utf-8")
    with pytest.raises(InputError) as excinfo:
        infer_file(path)
    assert "no data rows" in str(excinfo.value)


def test_missing_file_error(tmp_path: pathlib.Path) -> None:
    with pytest.raises(InputError) as excinfo:
        infer_file(tmp_path / "nope.csv")
    assert "no such file" in str(excinfo.value)


def test_ragged_rows_produce_a_warning(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "ragged.csv"
    path.write_text("a,b\n1,2\n3,4,5\n", encoding="utf-8")
    result = infer_file(path)
    assert any("more cells than the header" in warning for warning in result.warnings)


def test_inference_is_deterministic(orders_csv: pathlib.Path) -> None:
    first = infer_file(orders_csv).contract.to_schema()
    second = infer_file(orders_csv).contract.to_schema()
    assert canonical_json(first) == canonical_json(second)


def test_contract_hash_ignores_stats(orders_csv: pathlib.Path) -> None:
    result = infer_file(orders_csv)
    contract = result.contract
    assert contract.contract_hash() == contract.to_lock()["contract_sha256"]
    assert len(contract.contract_hash()) == 64


def test_large_input_streams_and_stays_fast(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "big.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write("id,email,amount\n")
        for index in range(20000):
            handle.write("%d,user%d@example.com,$%d.00\n" % (index, index, index % 500))
    result = infer_file(path)
    assert result.rows == 20000
    assert result.contract.column("id").kind == "int"  # type: ignore[union-attr]
    assert result.contract.to_schema()["x-schema-forge"]["rows"] == 20000


def test_probe_window_mismatch_is_reported(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "drift.csv"
    lines = ["value"] + ["1"] * 10 + ["oops"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    options = Options(probe_rows=5)
    column = infer_file(path, options=options).contract.column("value")
    assert column is not None
    assert column.kind == "int"
    assert any("did not match" in note for note in column.notes)


def test_text_column_never_reports_high_confidence(tmp_path: pathlib.Path) -> None:
    rows = [["free text %d with words" % index] for index in range(80)]
    path = write_csv(tmp_path / "free.csv", ["body"], rows)
    column = infer_file(path).contract.column("body")
    assert column is not None
    assert column.kind == "text"
    assert column.confidence <= 0.6


def test_currency_values_get_numeric_stats(tmp_path: pathlib.Path) -> None:
    rows = [["$10.00"], ["$20.00"], ["$30.00"], ["$40.00"]]
    path = write_csv(tmp_path / "money.csv", ["amount"], rows)
    column = infer_file(path).contract.column("amount")
    assert column is not None
    assert column.kind == "currency"
    assert column.stats["min"] == 10.0
    assert column.stats["max"] == 40.0
    assert column.stats["mean"] == 25.0


def test_boolean_tokens_from_json_and_csv_agree(tmp_path: pathlib.Path) -> None:
    csv_path = write_csv(tmp_path / "b.csv", ["flag"], [["true"], ["false"], ["yes"], ["no"]])
    json_path = tmp_path / "b.jsonl"
    json_path.write_text(
        "\n".join(json.dumps({"flag": value}) for value in (True, False, True, False)) + "\n",
        encoding="utf-8",
    )
    csv_column = infer_file(csv_path).contract.column("flag")
    json_column = infer_file(json_path).contract.column("flag")
    assert csv_column is not None and json_column is not None
    assert csv_column.kind == "bool"
    assert json_column.kind == "bool"
    assert csv_column.confidence == json_column.confidence


def test_delimiter_override(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "pipes.txt"
    path.write_text("a|b\n1|x\n2|y\n3|z\n", encoding="utf-8")
    result = infer_file(path, delimiter="|")
    assert [column.name for column in result.contract.columns] == ["a", "b"]
    first = result.contract.column("a")
    assert first is not None and first.kind == "int"
