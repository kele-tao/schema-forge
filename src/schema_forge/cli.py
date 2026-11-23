"""The schema-forge command line interface.

Exit codes (documented in the README and asserted in tests):

  0  success
  1  findings: validation violations, a breaking diff, or contract drift
  2  usage error: bad arguments, unreadable input, malformed schema
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from typing import Any

from schema_forge import __version__
from schema_forge import reader as data_reader
from schema_forge.diff import diff_specs
from schema_forge.diff import render_diff as render_diff_text
from schema_forge.infer import Options, infer
from schema_forge.report import (
    as_json,
    render_contract_markdown,
    render_explain,
    render_infer,
    render_validate,
    use_color,
)
from schema_forge.validate import SchemaError, check_lock, load_schema, validate_file

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2


class UsageError(Exception):
    """A user-facing error that maps to exit code 2."""


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse tree for every subcommand."""
    parser = argparse.ArgumentParser(
        prog="schema-forge",
        description=(
            "Infer JSON Schema data contracts from messy CSV/JSON, validate new data "
            "against them in CI, and diff schema versions for breaking changes."
        ),
        epilog=(
            "examples:\n"
            "  schema-forge infer examples/orders.csv --name orders --lock schema.lock.json\n"
            "  schema-forge validate examples/orders.csv --schema orders.schema.json\n"
            "  schema-forge diff orders.schema.json orders.v2.schema.json\n"
            "  schema-forge explain examples/orders.csv --column amount\n"
            "\nexit codes: 0 ok, 1 findings (violations / breaking diff / drift), 2 usage error"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version="schema-forge " + __version__)
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="disable ANSI colour (also honours the NO_COLOR environment variable)",
    )
    sub = parser.add_subparsers(dest="command", metavar="command")

    infer_parser = sub.add_parser(
        "infer",
        help="infer a data contract from a CSV/TSV/JSON file",
        description="Infer types, nullability, stats, enums, patterns and PII.",
    )
    infer_parser.add_argument("file", help="input data file")
    infer_parser.add_argument(
        "--name", default=None, help="contract name (defaults to the file stem)"
    )
    infer_parser.add_argument("--out", default=None, help="write the JSON Schema here")
    infer_parser.add_argument("--markdown", default=None, help="write the Markdown contract here")
    infer_parser.add_argument("--lock", default=None, help="write the schema.lock.json here")
    infer_parser.add_argument(
        "--format",
        default=None,
        choices=[*data_reader.FORMATS, "auto"],
        help="input format (default: infer from the extension)",
    )
    infer_parser.add_argument("--delimiter", default=None, help="field separator for CSV input")
    infer_parser.add_argument(
        "--enum-threshold",
        type=int,
        default=24,
        help="max distinct values for enum detection (default: 24)",
    )
    infer_parser.add_argument(
        "--enum-max-ratio",
        type=float,
        default=0.2,
        help="max distinct/rows ratio for enum detection (default: 0.2)",
    )
    infer_parser.add_argument(
        "--probe-rows",
        type=int,
        default=2000,
        help="rows used to choose types before verification (default: 2000)",
    )
    infer_parser.add_argument(
        "--evidence-rows", type=int, default=3, help="evidence rows kept per column (default: 3)"
    )
    infer_parser.add_argument("--no-pii", action="store_true", help="skip PII detection")
    infer_parser.add_argument("--json", action="store_true", help="print the contract as JSON")
    infer_parser.add_argument("--quiet", action="store_true", help="print nothing on success")

    validate_parser = sub.add_parser(
        "validate",
        help="validate a data file against a contract",
        description="Check every row against a schema and print row-level locators for violations.",
    )
    validate_parser.add_argument("file", help="input data file")
    validate_parser.add_argument("--schema", required=True, help="JSON Schema contract to enforce")
    validate_parser.add_argument(
        "--format",
        default=None,
        choices=[*data_reader.FORMATS, "auto"],
        help="input format (default: infer from the extension)",
    )
    validate_parser.add_argument("--delimiter", default=None, help="field separator for CSV input")
    validate_parser.add_argument(
        "--max-errors",
        type=int,
        default=50,
        help="stop collecting after N violations (default: 50)",
    )
    validate_parser.add_argument(
        "--sample",
        type=float,
        default=1.0,
        help="validate every Nth row, e.g. 0.1 for a 10%% sample (default: all rows)",
    )
    validate_parser.add_argument(
        "--no-strict",
        dest="strict",
        action="store_false",
        help="allow columns the contract does not declare",
    )
    validate_parser.add_argument(
        "--lock", default=None, help="compare the schema with a schema.lock.json first"
    )
    validate_parser.add_argument("--json", action="store_true", help="print the report as JSON")
    validate_parser.add_argument("--colors", action="store_true", help="force ANSI colour output")
    validate_parser.set_defaults(strict=True)

    diff_parser = sub.add_parser(
        "diff",
        help="classify changes between two contracts as breaking or compatible",
        description="Compare two schema files and explain how to migrate producers.",
    )
    diff_parser.add_argument("old", help="baseline schema")
    diff_parser.add_argument("new", help="candidate schema")
    diff_parser.add_argument("--json", action="store_true", help="print the diff as JSON")
    diff_parser.add_argument(
        "--allow-breaking",
        action="store_true",
        help="exit 0 even when breaking changes are found (not recommended for CI)",
    )

    explain_parser = sub.add_parser(
        "explain",
        help="show why a column got its inferred type",
        description="Print the confidence decomposition, candidate scores and evidence rows.",
    )
    explain_parser.add_argument("file", help="input data file")
    explain_parser.add_argument("--column", required=True, help="column to explain")
    explain_parser.add_argument(
        "--schema", default=None, help="explain from an existing schema instead of re-inferring"
    )
    explain_parser.add_argument(
        "--format",
        default=None,
        choices=[*data_reader.FORMATS, "auto"],
        help="input format (default: infer from the extension)",
    )
    explain_parser.add_argument("--delimiter", default=None, help="field separator for CSV input")
    explain_parser.add_argument("--json", action="store_true", help="print the report as JSON")

    return parser


def _write(path: str, payload: str) -> pathlib.Path:
    target = pathlib.Path(path)
    if target.parent and str(target.parent) not in ("", "."):
        target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload + ("\n" if not payload.endswith("\n") else ""), encoding="utf-8")
    return target


def cmd_infer(args: argparse.Namespace, color: bool) -> int:
    """Run the infer subcommand."""
    path = pathlib.Path(args.file)
    options = Options(
        enum_threshold=args.enum_threshold,
        enum_max_ratio=args.enum_max_ratio,
        probe_rows=args.probe_rows,
        evidence_rows=args.evidence_rows,
        detect_pii=not args.no_pii,
    )
    if options.enum_threshold < 2:
        raise UsageError("--enum-threshold must be at least 2")
    if not 0.0 < options.enum_max_ratio <= 1.0:
        raise UsageError("--enum-max-ratio must be in (0, 1]")
    if options.probe_rows < 1:
        raise UsageError("--probe-rows must be at least 1")
    result = infer(path, name=args.name, fmt=args.format, delimiter=args.delimiter, options=options)
    contract = result.contract
    schema = contract.to_schema()
    if args.json:
        print(as_json(schema))
    elif not args.quiet:
        print(render_infer(result, color=color))
    written: list[str] = []
    if args.out:
        written.append(str(_write(args.out, as_json(schema))))
    if args.markdown:
        written.append(str(_write(args.markdown, render_contract_markdown(contract))))
    if args.lock:
        written.append(str(_write(args.lock, as_json(contract.to_lock()))))
    if written and not args.quiet and not args.json:
        print("")
        for name in written:
            print("wrote " + name)
    return EXIT_OK


def cmd_validate(args: argparse.Namespace, color: bool) -> int:
    """Run the validate subcommand."""
    if not 0.0 < args.sample <= 1.0:
        raise UsageError("--sample must be in (0, 1], e.g. 0.1 to check every tenth row")
    if args.max_errors < 1:
        raise UsageError("--max-errors must be at least 1")
    spec = load_schema(pathlib.Path(args.schema))
    lock_ok = True
    lock_status = "not-checked"
    lock_detail = ""
    if args.lock:
        lock_status, lock_detail = check_lock(spec, pathlib.Path(args.lock))
        lock_ok = lock_status == "ok"
    report = validate_file(
        pathlib.Path(args.file),
        spec,
        fmt=args.format,
        delimiter=args.delimiter,
        max_errors=args.max_errors,
        sample=args.sample,
        strict=args.strict,
    )
    report.lock_status = lock_status
    report.lock_detail = lock_detail
    report.lock_verified = lock_status == "ok"
    if args.json:
        print(as_json(report.to_json()))
    else:
        print(render_validate(report, color=color or args.colors))
    return EXIT_OK if report.ok and lock_ok else EXIT_FINDINGS


def cmd_diff(args: argparse.Namespace, color: bool) -> int:
    """Run the diff subcommand."""
    old = load_schema(pathlib.Path(args.old))
    new = load_schema(pathlib.Path(args.new))
    result = diff_specs(old, new)
    if args.json:
        print(as_json(result.to_json()))
    else:
        print(render_diff_text(result, color=color))
    if result.breaking and not args.allow_breaking:
        return EXIT_FINDINGS
    return EXIT_OK


def _column_from_schema(schema_path: pathlib.Path, column: str) -> dict[str, Any]:
    spec = load_schema(schema_path)
    if column not in spec.properties:
        known = ", ".join(sorted(spec.properties))
        raise UsageError(
            "column " + repr(column) + " is not in " + schema_path.name + "; known: " + known
        )
    return spec.properties[column]


def cmd_explain(args: argparse.Namespace, color: bool) -> int:
    """Run the explain subcommand."""
    if args.schema:
        spec_props = _column_from_schema(pathlib.Path(args.schema), args.column)
        payload = spec_props.get("x-schema-forge") or {}
        if args.json:
            print(as_json({"column": args.column, **payload}))
            return EXIT_OK
        lines = ["column " + repr(args.column) + " -> " + str(payload.get("type"))]
        lines.append("  confidence {:.2f}".format(float(payload.get("confidence", 0.0))))
        lines.append("")
        lines.append("confidence factors:")
        for key, value in (payload.get("confidence_parts") or {}).items():
            lines.append("  %-14s %.3f" % (key, float(value)))
        lines.append("")
        candidates = payload.get("candidates") or []
        if candidates:
            lines.append("candidates considered on the probe sample:")
            for candidate in candidates:
                lines.append(
                    "  %-12s %.3f  (%s values)"
                    % (
                        candidate.get("kind"),
                        float(candidate.get("score", 0)),
                        candidate.get("matched"),
                    )
                )
            lines.append("")
        evidence = payload.get("evidence") or []
        if evidence:
            lines.append("evidence rows:")
            for row in evidence:
                matched = ", ".join(row.get("matched") or []) or "no structural type"
                lines.append(
                    "  "
                    + str(row.get("location")).ljust(9)
                    + repr(row.get("value")).ljust(44)
                    + "matched "
                    + matched
                )
            lines.append("")
        notes = payload.get("notes") or []
        if notes:
            lines.append("notes:")
            for note in notes:
                lines.append("  - " + note)
        print("\n".join(lines))
        return EXIT_OK
    result = infer(
        pathlib.Path(args.file),
        fmt=args.format,
        delimiter=args.delimiter,
        options=Options(detect_pii=False),
    )
    column = result.contract.column(args.column)
    if column is None:
        known = ", ".join(item.name for item in result.contract.columns)
        raise UsageError(
            "column " + repr(args.column) + " is not in " + args.file + "; known: " + known
        )
    if args.json:
        print(as_json(column.to_schema_property()["x-schema-forge"] | {"column": column.name}))
        return EXIT_OK
    print(render_explain(column, result.rows))
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """Entry point for the console script and for python -m schema_forge."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return EXIT_OK
    color = False if args.no_color else use_color(None)
    handlers = {
        "infer": cmd_infer,
        "validate": cmd_validate,
        "diff": cmd_diff,
        "explain": cmd_explain,
    }
    try:
        return handlers[args.command](args, color)
    except UsageError as exc:
        sys.stderr.write("schema-forge: error: " + str(exc) + "\n")
        return EXIT_USAGE
    except data_reader.InputError as exc:
        sys.stderr.write("schema-forge: input error: " + str(exc) + "\n")
        return EXIT_USAGE
    except SchemaError as exc:
        sys.stderr.write("schema-forge: schema error: " + str(exc) + "\n")
        return EXIT_USAGE
    except BrokenPipeError:
        return EXIT_OK
    except OSError as exc:
        sys.stderr.write("schema-forge: error: " + str(exc) + "\n")
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
