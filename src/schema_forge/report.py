"""Human-facing renderers: the infer table, explain report and Markdown contract."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from schema_forge.diff import DiffResult
from schema_forge.infer import InferenceResult
from schema_forge.types import GENERATOR, Column, Contract
from schema_forge.validate import Report

RESET = "\x1b[0m"


class Style:
    """Tiny ANSI helper that can be switched off for plain output."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def paint(self, text: str, code: str) -> str:
        """Wrap text in an ANSI escape when colour is enabled."""
        if not self.enabled:
            return text
        return "\x1b[" + code + "m" + text + RESET

    def bold(self, text: str) -> str:
        """Bold text."""
        return self.paint(text, "1")

    def dim(self, text: str) -> str:
        """Dim text."""
        return self.paint(text, "2")

    def green(self, text: str) -> str:
        """Green text."""
        return self.paint(text, "32")

    def yellow(self, text: str) -> str:
        """Yellow text."""
        return self.paint(text, "33")

    def red(self, text: str) -> str:
        """Red text."""
        return self.paint(text, "31;1")

    def cyan(self, text: str) -> str:
        """Cyan text."""
        return self.paint(text, "36")


def use_color(explicit: bool | None) -> bool:
    """Decide whether to emit ANSI colour, honouring NO_COLOR and FORCE_COLOR."""
    if explicit is not None:
        return explicit
    if "NO_COLOR" in os.environ:
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    try:
        return sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def confidence_text(confidence: float) -> str:
    """Return the two-decimal confidence label."""
    return f"{confidence:.2f}"


def confidence_style(style: Style, confidence: float) -> str:
    """Colour the confidence label by how trustworthy it is."""
    text = confidence_text(confidence)
    if confidence >= 0.9:
        return style.green(text)
    if confidence >= 0.7:
        return style.yellow(text)
    return style.red(text)


def stats_text(column: Column) -> str:
    """Return the short stats column shown in the infer table."""
    stats = column.stats
    kind = column.kind
    if kind in ("int", "float") and "min" in stats:
        return "min {}  max {}  mean {}".format(stats["min"], stats["max"], stats["mean"])
    if kind == "date" and column.formats:
        return "formats " + ", ".join(column.formats)
    if kind == "enum":
        return str(len(column.enum_values)) + " values"
    if kind == "categorical":
        return str(column.distinct) + " values, max len " + str(stats.get("max_length"))
    if kind == "text" and column.pattern:
        return "pattern " + column.pattern
    if stats.get("min_length") == stats.get("max_length"):
        return "len " + str(stats.get("max_length"))
    return "len {}-{}".format(stats.get("min_length"), stats.get("max_length"))


def render_infer(result: InferenceResult, color: bool = True) -> str:
    """Render the inference summary table shown by 'schema-forge infer'."""
    style = Style(color)
    contract = result.contract
    lines: list[str] = []
    lines.append(style.bold("schema-forge infer:") + " " + contract.title)
    lines.append(
        style.dim(
            "%s, %d rows, %d columns, from %s"
            % (contract.fmt, contract.rows, len(contract.columns), contract.source)
        )
    )
    lines.append("")

    name_width = min(26, max(8, max(len(column.name) for column in contract.columns)))
    lines.append(
        "  "
        + style.dim("#".ljust(3))
        + style.dim("column".ljust(name_width + 2))
        + style.dim("type".ljust(12))
        + style.dim("conf".ljust(6))
        + style.dim("nulls".ljust(8))
        + style.dim("distinct".ljust(9))
        + style.dim("stats")
    )
    for index, column in enumerate(contract.columns, start=1):
        name = column.name
        if len(name) > name_width:
            name = name[: name_width - 1] + "~"
        raw_null = "%.1f%%" % (column.null_ratio * 100)
        null_cell = style.yellow(raw_null) if column.nulls else raw_null
        distinct = str(column.distinct) + ("+" if column.distinct_capped else "")
        conf = confidence_style(style, column.confidence)
        lines.append(
            "  "
            + style.dim(str(index).ljust(3))
            + name.ljust(name_width + 2)
            + (column.kind + ("*" if column.pii else "")).ljust(12)
            + conf
            + " " * max(1, 6 - len(confidence_text(column.confidence)))
            + null_cell
            + " " * max(1, 8 - len(raw_null))
            + distinct.ljust(9)
            + style.dim(stats_text(column))
        )
    lines.append(style.dim("  * = PII detected, see the masking advice below"))

    pii_columns = [column for column in contract.columns if column.pii]
    if pii_columns:
        lines.append("")
        lines.append(style.bold("PII findings"))
        for column in pii_columns:
            pii = column.pii
            if pii is None:
                continue
            lines.append(
                "  "
                + style.red(column.name.ljust(18))
                + pii.kind.ljust(7)
                + ("%5.0f%%" % (pii.ratio * 100))
                + "  mask "
                + pii.mask_example.ljust(22)
                + style.dim(pii.advice)
            )

    typo_columns = [column for column in contract.columns if column.enum_typos]
    if typo_columns:
        lines.append("")
        lines.append(style.bold("enum variants to clean up"))
        for column in typo_columns:
            for variant, intended in column.enum_typos.items():
                lines.append(
                    "  "
                    + style.yellow(column.name)
                    + ": "
                    + repr(variant)
                    + " looks like "
                    + repr(intended)
                    + style.dim("  (fix the producer, then re-infer)")
                )

    date_notes = [
        column for column in contract.columns if column.formats and len(column.formats) > 1
    ]
    if date_notes:
        lines.append("")
        lines.append(style.bold("date formats"))
        for column in date_notes:
            lines.append("  " + style.yellow(column.name) + ": " + ", ".join(column.formats))

    if contract.warnings:
        lines.append("")
        lines.append(style.bold("warnings"))
        for warning in contract.warnings:
            lines.append("  " + style.yellow("!") + " " + warning)

    lines.append("")
    lines.append(
        style.bold("contract hash")
        + " sha256:"
        + contract.contract_hash()[:16]
        + style.dim("  (pin it with --lock; drift then fails validate --lock)")
    )
    lines.append(
        style.dim("next: ")
        + "schema-forge validate "
        + contract.source
        + " --schema "
        + contract.title
        + ".schema.json"
    )
    return "\n".join(lines)


def render_explain(column: Column, total_rows: int) -> str:
    """Render the evidence report for one column."""
    lines: list[str] = []
    lines.append("column " + repr(column.name) + " -> " + column.kind)
    lines.append(
        "  confidence %.2f  |  %d rows probed, %d values, %d empty (%.1f%%), %d distinct%s"
        % (
            column.confidence,
            column.sample_size,
            column.seen - column.nulls,
            column.nulls,
            column.null_ratio * 100,
            column.distinct,
            "+" if column.distinct_capped else "",
        )
    )
    lines.append("")
    lines.append("confidence is the product of four factors:")
    labels = {
        "fill_rate": "fill rate       non-empty values / rows seen",
        "type_support": "type support    values matching the chosen type",
        "specificity": "specificity     how specific the chosen type is",
        "sample_depth": "sample depth    how many values backed the call",
    }
    for key in ("fill_rate", "type_support", "specificity", "sample_depth"):
        if key in column.confidence_parts:
            lines.append("  %-50s %.3f" % (labels[key], column.confidence_parts[key]))
    lines.append("")
    if column.candidates:
        lines.append("candidates considered on the probe sample:")
        for candidate in column.candidates:
            lines.append(
                "  %-12s %.3f  (%d/%d values)"
                % (candidate.kind, candidate.score, candidate.matched, column.sample_size)
            )
        lines.append("")
    if column.evidence:
        lines.append("evidence rows:")
        for row in column.evidence:
            shown = column.display_value(row.value)
            matched = ", ".join(row.matched) if row.matched else "no structural type"
            lines.append(
                "  " + row.location.ljust(9) + repr(shown).ljust(44) + "matched " + matched
            )
        lines.append("")
    if column.formats:
        lines.append("date formats that parsed the column, most common first:")
        lines.append("  " + ", ".join(column.formats))
        lines.append("")
    if column.enum_values:
        lines.append("enum values: " + ", ".join(repr(value) for value in column.enum_values))
        lines.append("")
    if column.pii:
        lines.append(
            f"PII: {column.pii.kind} in {column.pii.ratio * 100:.0f}% of values; "
            f"masked example {column.pii.mask_example}"
        )
        lines.append("")
    if column.notes:
        lines.append("notes:")
        for note in column.notes:
            lines.append("  - " + note)
        lines.append("")
    lines.append(
        "stats: " + ", ".join(name + "=" + str(value) for name, value in column.stats.items())
    )
    lines.append("rows in source: " + str(total_rows))
    return "\n".join(lines)


def render_validate(report: Report, color: bool = True, show_sample: int = 10) -> str:
    """Render the validation report; the last line is the verdict."""
    style = Style(color)
    lines: list[str] = []
    lines.append(
        style.bold("schema-forge validate:") + " " + report.source + " against " + report.schema
    )
    lines.append(
        style.dim(
            "%d rows, %d sampled, %d cells checked"
            % (report.rows, report.sampled_rows, report.checked_cells)
        )
    )
    if report.lock_status != "not-checked":
        if report.lock_status == "ok":
            lines.append("lock: " + style.green("ok") + "  " + report.lock_detail)
        else:
            lines.append("lock: " + style.red(report.lock_status) + "  " + report.lock_detail)
    lines.append("")
    if report.missing_columns:
        lines.append(style.red("missing required columns: ") + ", ".join(report.missing_columns))
    if report.unknown_columns:
        lines.append(style.red("unknown columns: ") + ", ".join(report.unknown_columns))
    if report.violations:
        lines.append(
            style.bold(
                "violations (showing %d of %d):"
                % (min(len(report.violations), show_sample), report.violation_count)
            )
        )
        for violation in report.violations[:show_sample]:
            lines.append("  " + style.red("x") + " " + violation.render())
        if len(report.violations) > show_sample:
            lines.append(
                style.dim("  ... %d more suppressed" % (len(report.violations) - show_sample))
            )
        if report.truncated:
            lines.append(style.dim("  error collection stopped at --max-errors"))
    else:
        lines.append(style.green("no violations"))
    lines.append("")
    if report.ok:
        lines.append(style.green("PASS") + "  %d rows conform to %s" % (report.rows, report.schema))
    else:
        lines.append(
            style.red("FAIL")
            + "  %d violation(s) across %d rows" % (report.violation_count, report.rows)
        )
    return "\n".join(lines)


def render_contract_markdown(contract: Contract) -> str:
    """Render the human-readable contract table committed next to the schema."""
    tick = "`"
    lines: list[str] = []
    lines.append("# " + contract.title + " data contract")
    lines.append("")
    lines.append(
        "Inferred by "
        + tick
        + GENERATOR
        + tick
        + " from "
        + tick
        + contract.source
        + tick
        + " (%s, %d rows, %d columns). Regenerate with "
        % (contract.fmt, contract.rows, len(contract.columns))
        + tick
        + "schema-forge infer"
        + tick
        + "; do not edit by hand."
    )
    lines.append("")
    lines.append("Contract hash: " + tick + "sha256:" + contract.contract_hash() + tick)
    lines.append("")
    lines.append("| # | Column | Type | Conf | Nulls | Distinct | Constraints |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for index, column in enumerate(contract.columns, start=1):
        lines.append(
            "| %d | %s%s%s | %s | %.2f | %.1f%% | %s%s | %s |"
            % (
                index,
                tick,
                column.name,
                tick,
                column.kind,
                column.confidence,
                column.null_ratio * 100,
                column.distinct,
                "+" if column.distinct_capped else "",
                column.summary(),
            )
        )
    required = contract.required_names()
    optional = [column.name for column in contract.columns if column.name not in required]
    lines.append("")
    lines.append("## Required columns")
    lines.append("")
    lines.append(
        "Required means present in the header and never empty across all %d sampled rows."
        % contract.rows
    )
    lines.append("")
    lines.append(", ".join(tick + name + tick for name in required) if required else "_none_")
    lines.append("")
    lines.append("## Optional columns")
    lines.append("")
    lines.append(", ".join(tick + name + tick for name in optional) if optional else "_none_")
    notes = [(column.name, note) for column in contract.columns for note in column.notes]
    if notes or contract.warnings:
        lines.append("")
        lines.append("## Notes")
        lines.append("")
        for name, note in notes:
            lines.append("- " + tick + name + tick + ": " + note)
        for warning in contract.warnings:
            lines.append("- " + warning)
    lines.append("")
    lines.append("## Validate")
    lines.append("")
    lines.append(tick * 3 + "bash")
    lines.append(
        "schema-forge validate " + contract.source + " --schema " + contract.title + ".schema.json"
    )
    lines.append(tick * 3)
    return "\n".join(lines)


def render_diff_summary(result: DiffResult) -> str:
    """Compact one-line diff summary used by CI logs."""
    if not result.changes:
        return "no changes"
    return "%d breaking, %d compatible change(s)" % (len(result.breaking), len(result.compatible))


def as_json(payload: Any) -> str:
    """Serialise a JSON-ready payload deterministically."""
    return json.dumps(payload, indent=2, ensure_ascii=False)
