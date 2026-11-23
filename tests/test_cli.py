"""End-to-end CLI tests: every documented flag, exit codes, friendly errors."""

from __future__ import annotations

import json
import pathlib

import pytest


def test_version_flag(cli) -> None:
    code, out, err = cli("--version")
    assert code in (0, 2)
    assert "schema-forge" in out or "schema-forge" in err


def test_help_lists_every_command(cli) -> None:
    code, out, _err = cli("--help")
    assert code == 0
    for command in ("infer", "validate", "diff", "explain"):
        assert command in out


def test_infer_prints_table(cli, orders_csv: pathlib.Path) -> None:
    code, out, err = cli("infer", str(orders_csv))
    assert code == 0, err
    assert "schema-forge infer" in out
    assert "contract hash" in out
    assert "email" in out


def test_infer_writes_schema_markdown_and_lock(
    cli, orders_csv: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    out_schema = tmp_path / "orders.schema.json"
    out_md = tmp_path / "orders.md"
    out_lock = tmp_path / "schema.lock.json"
    code, out, err = cli(
        "infer",
        str(orders_csv),
        "--name",
        "orders",
        "--out",
        str(out_schema),
        "--markdown",
        str(out_md),
        "--lock",
        str(out_lock),
    )
    assert code == 0, err
    assert out_schema.exists() and out_md.exists() and out_lock.exists()
    schema = json.loads(out_schema.read_text(encoding="utf-8"))
    assert schema["title"] == "orders"
    assert schema["$schema"].endswith("2020-12/schema")
    assert "| Column |" in out_md.read_text(encoding="utf-8")
    assert len(json.loads(out_lock.read_text(encoding="utf-8"))["contract_sha256"]) == 64


def test_infer_json_flag_is_pure_json(cli, orders_csv: pathlib.Path) -> None:
    code, out, err = cli("infer", str(orders_csv), "--json", "--name", "orders")
    assert code == 0, err
    payload = json.loads(out)
    assert payload["title"] == "orders"
    assert payload["properties"]["id"]["type"] == "integer"


def test_infer_quiet_prints_nothing(cli, orders_csv: pathlib.Path) -> None:
    code, out, err = cli("infer", str(orders_csv), "--quiet")
    assert code == 0
    assert out == ""


def test_infer_no_pii_disables_findings(cli, orders_csv: pathlib.Path) -> None:
    code, out, _err = cli("infer", str(orders_csv), "--no-pii", "--json")
    assert code == 0
    payload = json.loads(out)
    for column in payload["properties"].values():
        assert "pii" not in column["x-schema-forge"]


def test_infer_rejects_bad_enum_threshold(cli, orders_csv: pathlib.Path) -> None:
    code, _out, err = cli("infer", str(orders_csv), "--enum-threshold", "1")
    assert code == 2
    assert "--enum-threshold" in err


def test_infer_missing_file_is_usage_error(cli, tmp_path: pathlib.Path) -> None:
    code, _out, err = cli("infer", str(tmp_path / "nope.csv"))
    assert code == 2
    assert "no such file" in err
    assert "Traceback" not in err


def test_infer_empty_file_is_usage_error(cli, tmp_path: pathlib.Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")
    code, _out, err = cli("infer", str(path))
    assert code == 2
    assert "Traceback" not in err


def test_validate_clean_file_exit_zero(
    cli, orders_csv: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    schema = tmp_path / "s.json"
    cli("infer", str(orders_csv), "--out", str(schema), "--quiet")
    code, out, err = cli("validate", str(orders_csv), "--schema", str(schema))
    assert code == 0, err
    assert "PASS" in out


def test_validate_violations_exit_one(
    cli, orders_csv: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    schema = tmp_path / "s.json"
    cli("infer", str(orders_csv), "--out", str(schema), "--quiet")
    bad = tmp_path / "bad.csv"
    bad.write_text(
        "id,email,country,amount,qty,active,created\n"
        "nope,x@example.com,US,$1.00,5,true,2026-01-01\n",
        encoding="utf-8",
    )
    code, out, err = cli("validate", str(bad), "--schema", str(schema))
    assert code == 1, err
    assert "row 2" in out
    assert "FAIL" in out


def test_validate_max_errors_limits_output(
    cli, orders_csv: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    schema = tmp_path / "s.json"
    cli("infer", str(orders_csv), "--out", str(schema), "--quiet")
    lines = ["id,email,country,amount,qty,active,created"]
    lines += ["nope,x@example.com,US,$1.00,5,true,2026-01-01"] * 8
    bad = tmp_path / "bad.csv"
    bad.write_text("\n".join(lines) + "\n", encoding="utf-8")
    code, out, _err = cli("validate", str(bad), "--schema", str(schema), "--max-errors", "2")
    assert code == 1
    assert out.count("expected integer") == 2


def test_validate_json_report(cli, orders_csv: pathlib.Path, tmp_path: pathlib.Path) -> None:
    schema = tmp_path / "s.json"
    cli("infer", str(orders_csv), "--out", str(schema), "--quiet")
    code, out, _err = cli("validate", str(orders_csv), "--schema", str(schema), "--json")
    assert code == 0
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["rows"] == 40


def test_validate_sample_flag(cli, orders_csv: pathlib.Path, tmp_path: pathlib.Path) -> None:
    schema = tmp_path / "s.json"
    cli("infer", str(orders_csv), "--out", str(schema), "--quiet")
    code, out, _err = cli(
        "validate", str(orders_csv), "--schema", str(schema), "--sample", "0.25", "--json"
    )
    assert code == 0
    payload = json.loads(out)
    assert payload["sampled_rows"] < payload["rows"]


def test_validate_rejects_bad_sample(cli, orders_csv: pathlib.Path, tmp_path: pathlib.Path) -> None:
    schema = tmp_path / "s.json"
    cli("infer", str(orders_csv), "--out", str(schema), "--quiet")
    code, _out, err = cli("validate", str(orders_csv), "--schema", str(schema), "--sample", "2")
    assert code == 2
    assert "--sample" in err


def test_validate_lock_drift_exits_one(
    cli, orders_csv: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    schema = tmp_path / "s.json"
    lock = tmp_path / "schema.lock.json"
    cli("infer", str(orders_csv), "--out", str(schema), "--lock", str(lock), "--quiet")
    payload = json.loads(schema.read_text(encoding="utf-8"))
    payload["properties"]["id"]["type"] = "string"
    schema.write_text(json.dumps(payload), encoding="utf-8")
    code, out, _err = cli("validate", str(orders_csv), "--schema", str(schema), "--lock", str(lock))
    assert code == 1
    assert "drift" in out


def test_validate_bad_schema_is_usage_error(
    cli, orders_csv: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    code, _out, err = cli("validate", str(orders_csv), "--schema", str(bad))
    assert code == 2
    assert "properties" in err


def test_validate_no_strict_allows_extra_columns(
    cli, orders_csv: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    schema = tmp_path / "s.json"
    cli("infer", str(orders_csv), "--out", str(schema), "--quiet")
    lines = pathlib.Path(orders_csv).read_text(encoding="utf-8").splitlines()
    augmented = [lines[0] + ",extra"] + [line + ",x" for line in lines[1:]]
    path = tmp_path / "extra.csv"
    path.write_text("\n".join(augmented) + "\n", encoding="utf-8")
    assert cli("validate", str(path), "--schema", str(schema))[0] == 1
    assert cli("validate", str(path), "--schema", str(schema), "--no-strict")[0] == 0


def test_diff_identical_exit_zero(cli, orders_csv: pathlib.Path, tmp_path: pathlib.Path) -> None:
    schema = tmp_path / "s.json"
    cli("infer", str(orders_csv), "--out", str(schema), "--quiet")
    code, out, _err = cli("diff", str(schema), str(schema))
    assert code == 0
    assert "no changes" in out


def test_diff_breaking_exit_one(cli, orders_csv: pathlib.Path, tmp_path: pathlib.Path) -> None:
    schema = tmp_path / "s.json"
    cli("infer", str(orders_csv), "--out", str(schema), "--quiet")
    payload = json.loads(schema.read_text(encoding="utf-8"))
    payload["properties"]["qty"]["type"] = "string"
    changed = tmp_path / "s2.json"
    changed.write_text(json.dumps(payload), encoding="utf-8")
    code, out, _err = cli("diff", str(schema), str(changed))
    assert code == 1
    assert "BREAKING" in out
    assert "fix:" in out


def test_diff_allow_breaking_exit_zero(
    cli, orders_csv: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    schema = tmp_path / "s.json"
    cli("infer", str(orders_csv), "--out", str(schema), "--quiet")
    payload = json.loads(schema.read_text(encoding="utf-8"))
    payload["properties"]["qty"]["type"] = "string"
    changed = tmp_path / "s2.json"
    changed.write_text(json.dumps(payload), encoding="utf-8")
    assert cli("diff", str(schema), str(changed), "--allow-breaking")[0] == 0


def test_diff_json(cli, orders_csv: pathlib.Path, tmp_path: pathlib.Path) -> None:
    schema = tmp_path / "s.json"
    cli("infer", str(orders_csv), "--out", str(schema), "--quiet")
    payload = json.loads(schema.read_text(encoding="utf-8"))
    payload["properties"]["qty"]["type"] = "string"
    changed = tmp_path / "s2.json"
    changed.write_text(json.dumps(payload), encoding="utf-8")
    code, out, _err = cli("diff", str(schema), str(changed), "--json")
    assert code == 1
    assert json.loads(out)["breaking"] >= 1


def test_explain_prints_evidence(cli, orders_csv: pathlib.Path) -> None:
    code, out, err = cli("explain", str(orders_csv), "--column", "amount")
    assert code == 0, err
    assert "confidence is the product of four factors" in out
    assert "evidence rows:" in out
    assert "currency" in out


def test_explain_from_schema(cli, orders_csv: pathlib.Path, tmp_path: pathlib.Path) -> None:
    schema = tmp_path / "s.json"
    cli("infer", str(orders_csv), "--out", str(schema), "--quiet")
    code, out, _err = cli("explain", str(orders_csv), "--column", "amount", "--schema", str(schema))
    assert code == 0
    assert "confidence factors:" in out


def test_explain_unknown_column_is_usage_error(cli, orders_csv: pathlib.Path) -> None:
    code, _out, err = cli("explain", str(orders_csv), "--column", "nope")
    assert code == 2
    assert "not in" in err


def test_explain_json(cli, orders_csv: pathlib.Path) -> None:
    code, out, _err = cli("explain", str(orders_csv), "--column", "qty", "--json")
    assert code == 0
    payload = json.loads(out)
    assert payload["type"] == "int"


def test_no_color_output_has_no_escapes(cli, orders_csv: pathlib.Path) -> None:
    code, out, _err = cli("--no-color", "infer", str(orders_csv))
    assert code == 0
    assert "\x1b[" not in out


def test_jsonl_cli_flow(cli, tmp_path: pathlib.Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(
        "\n".join(
            json.dumps({"id": index, "email": "u%d@example.com" % index, "ok": index % 2 == 0})
            for index in range(1, 31)
        )
        + "\n",
        encoding="utf-8",
    )
    schema = tmp_path / "events.schema.json"
    code, _out, err = cli("infer", str(path), "--out", str(schema), "--quiet")
    assert code == 0, err
    code, out, _err = cli("validate", str(path), "--schema", str(schema))
    assert code == 0
    assert "PASS" in out


@pytest.mark.parametrize("bad_format", ["xml"])
def test_unknown_format_is_usage_error(cli, orders_csv: pathlib.Path, bad_format: str) -> None:
    code, _out, err = cli("infer", str(orders_csv), "--format", bad_format)
    assert code == 2
    assert err
