"""Row-level validation of data files against a JSON Schema contract.

The validator understands the JSON Schema subset schema-forge emits:
object/properties/required/additionalProperties, type, enum, format and
pattern. It is intentionally small: a contract should be readable by a human,
and a validator that quietly accepts keywords it does not implement is worse
than one that rejects them.
"""

from __future__ import annotations

import json
import pathlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from schema_forge import detect, reader
from schema_forge.types import hash_enforcement

KNOWN_FORMATS = {"date", "date-time", "email", "uri", "uuid"}

TYPE_CHECKS = {
    "integer": detect.is_int,
    "number": lambda value: detect.is_float(value) or detect.is_int(value),
}


class SchemaError(Exception):
    """Raised when a schema file is missing, malformed or unsupported."""


@dataclass(slots=True)
class SchemaSpec:
    """The subset of a JSON Schema document that validation enforces."""

    title: str
    properties: dict[str, dict[str, Any]]
    required: list[str]
    additional_properties: bool
    contract_hash: str | None = None
    source: str = ""

    def to_enforcement(self) -> dict[str, Any]:
        """Return the canonical enforcement projection for drift comparison."""
        properties: dict[str, Any] = {}
        for name, spec in self.properties.items():
            entry: dict[str, Any] = {}
            for key in ("type", "format", "pattern", "enum"):
                if key in spec:
                    entry[key] = sorted(spec[key]) if key == "enum" else spec[key]
            properties[name] = entry
        return {
            "additionalProperties": self.additional_properties,
            "properties": properties,
            "required": sorted(self.required),
        }

    def computed_hash(self) -> str:
        """Return the SHA-256 of this schema's enforced projection."""
        return hash_enforcement(self.to_enforcement())


def load_schema(path: pathlib.Path) -> SchemaSpec:
    """Load and sanity-check a JSON Schema document from path."""
    if not path.exists():
        raise SchemaError(str(path) + ": no such schema file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SchemaError(str(path) + ": invalid JSON (" + exc.msg + ")") from exc
    except OSError as exc:
        raise SchemaError(str(path) + ": cannot read schema (" + str(exc.strerror) + ")") from exc
    if not isinstance(payload, dict):
        raise SchemaError(str(path) + ": expected a JSON object at the top level")
    properties = payload.get("properties")
    if not isinstance(properties, dict) or not properties:
        raise SchemaError(str(path) + ": no properties object; is this a schema-forge schema?")
    for name, spec in properties.items():
        if not isinstance(spec, dict):
            raise SchemaError(str(path) + ": property " + repr(name) + " is not an object")
        json_type = spec.get("type")
        if json_type not in {"string", "integer", "number", "boolean", "object", "array", "null"}:
            raise SchemaError(
                str(path) + ": property " + repr(name) + " has unsupported type " + repr(json_type)
            )
        fmt = spec.get("format")
        if fmt is not None and fmt not in KNOWN_FORMATS:
            raise SchemaError(
                str(path) + ": property " + repr(name) + " uses unsupported format " + repr(fmt)
            )
        pattern = spec.get("pattern")
        if pattern is not None:
            try:
                re.compile(pattern)
            except (re.error, TypeError) as exc:
                raise SchemaError(
                    str(path) + ": property " + repr(name) + " has an invalid pattern: " + str(exc)
                ) from exc
    required = payload.get("required") or []
    if not isinstance(required, list):
        raise SchemaError(str(path) + ": required must be a list of property names")
    unknown_required = [name for name in required if name not in properties]
    if unknown_required:
        raise SchemaError(
            str(path)
            + ": required names columns that are not in properties: "
            + ", ".join(map(str, unknown_required))
        )
    x_schema_forge = payload.get("x-schema-forge") or {}
    if not isinstance(x_schema_forge, dict):
        x_schema_forge = {}
    return SchemaSpec(
        title=str(payload.get("title") or path.stem),
        properties={str(name): dict(spec) for name, spec in properties.items()},
        required=[str(name) for name in required],
        additional_properties=bool(payload.get("additionalProperties", True)),
        contract_hash=x_schema_forge.get("contract_hash"),
        source=path.name,
    )


@dataclass(slots=True)
class Violation:
    """One row-level contract violation with a precise locator."""

    location: str
    column: str
    message: str
    value: str = ""

    def render(self) -> str:
        """Return the one-line CLI rendering of this violation."""
        if self.column:
            return self.location + ", column " + self.column + ": " + self.message
        return self.location + ": " + self.message

    def to_json(self) -> dict[str, Any]:
        """Return a JSON-ready representation."""
        return {
            "location": self.location,
            "column": self.column,
            "message": self.message,
            "value": self.value,
        }


def _type_ok(json_type: str, text: str) -> bool:
    check = TYPE_CHECKS.get(json_type)
    if check is not None:
        return check(text)
    if json_type == "boolean":
        return detect.is_bool(text)
    return True


def _format_ok(fmt: str, text: str) -> bool:
    if fmt == "date":
        return detect.is_date(text)
    if fmt == "date-time":
        return detect.is_datetime(text) or detect.is_date(text)
    if fmt == "email":
        return detect.is_email(text)
    if fmt == "uri":
        return detect.is_url(text)
    if fmt == "uuid":
        return detect.is_uuid(text)
    return True


def check_value(column: str, spec: dict[str, Any], text: str) -> str | None:
    """Return the first violation message for text, or None when it conforms."""
    json_type = spec.get("type")
    if isinstance(json_type, str) and not _type_ok(json_type, text):
        return "expected " + json_type + ", got " + repr(text)
    enum = spec.get("enum")
    if isinstance(enum, list) and enum and text not in [str(item) for item in enum]:
        shown = ", ".join(repr(str(item)) for item in enum[:6])
        more = "" if len(enum) <= 6 else " (+" + str(len(enum) - 6) + " more)"
        return "value " + repr(text) + " is not one of " + shown + more
    pattern = spec.get("pattern")
    if isinstance(pattern, str):
        compiled = re.compile(pattern)
        if compiled.fullmatch(text) is None:
            return "expected pattern " + pattern + ", got " + repr(text)
    fmt = spec.get("format")
    if isinstance(fmt, str) and not _format_ok(fmt, text):
        return "expected format " + fmt + ", got " + repr(text)
    return None


@dataclass(slots=True)
class Report:
    """The outcome of validating one file against one schema."""

    schema: str
    source: str
    rows: int
    checked_cells: int
    violations: list[Violation] = field(default_factory=list)
    violation_count: int = 0
    missing_columns: list[str] = field(default_factory=list)
    unknown_columns: list[str] = field(default_factory=list)
    truncated: bool = False
    sampled_rows: int = 0
    lock_status: str = "not-checked"
    lock_detail: str = ""
    lock_verified: bool = False

    @property
    def ok(self) -> bool:
        """True when no violations and no structural problems were found."""
        return not self.violation_count and not self.missing_columns and not self.unknown_columns

    def to_json(self) -> dict[str, Any]:
        """Return a JSON-ready representation used by --json."""
        return {
            "schema": self.schema,
            "source": self.source,
            "ok": self.ok,
            "rows": self.rows,
            "sampled_rows": self.sampled_rows,
            "checked_cells": self.checked_cells,
            "violation_count": self.violation_count,
            "missing_columns": self.missing_columns,
            "unknown_columns": self.unknown_columns,
            "truncated": self.truncated,
            "lock": {"status": self.lock_status, "detail": self.lock_detail},
            "violations": [violation.to_json() for violation in self.violations],
        }


def _sample_stride(sample: float) -> int:
    if sample >= 1.0:
        return 1
    return max(1, int(round(1.0 / sample)))


def validate_rows(
    spec: SchemaSpec,
    rows: Iterable[tuple[str, dict[str, Any]]],
    *,
    max_errors: int = 50,
    sample: float = 1.0,
    strict: bool = True,
) -> Report:
    """Validate an iterable of (location, row) pairs against spec."""
    report = Report(schema=spec.source, source="", rows=0, checked_cells=0)
    stride = _sample_stride(sample)
    for location, row in rows:
        report.rows += 1
        if stride > 1 and (report.rows - 1) % stride != 0:
            continue
        report.sampled_rows += 1
        room = len(report.violations) < max_errors
        if strict:
            for name in row:
                if name in spec.properties or name == "__extra__":
                    continue
                if name not in report.unknown_columns:
                    report.unknown_columns.append(name)
                    report.violation_count += 1
                    if len(report.violations) < max_errors:
                        report.violations.append(
                            Violation(
                                location=location,
                                column=name,
                                message=(
                                    "unknown column (strict mode rejects columns the contract "
                                    "does not declare)"
                                ),
                            )
                        )
                    else:
                        report.truncated = True
        for name, raw in row.items():
            if name == "__extra__" or name not in spec.properties:
                continue
            text = reader.to_text(raw)
            report.checked_cells += 1
            if text is None:
                if name in spec.required:
                    report.violation_count += 1
                    if len(report.violations) < max_errors:
                        report.violations.append(
                            Violation(
                                location=location,
                                column=name,
                                message="required column is empty but the contract marks "
                                "it required",
                            )
                        )
                    else:
                        report.truncated = True
                continue
            message = check_value(name, spec.properties[name], text)
            if message is None:
                continue
            report.violation_count += 1
            if len(report.violations) < max_errors:
                report.violations.append(
                    Violation(location=location, column=name, message=message, value=text)
                )
            else:
                report.truncated = True
        if not room:
            report.truncated = True
    return report


def validate_file(
    path: pathlib.Path,
    spec: SchemaSpec,
    *,
    fmt: str | None = None,
    delimiter: str | None = None,
    max_errors: int = 50,
    sample: float = 1.0,
    strict: bool = True,
) -> Report:
    """Validate one data file against one schema, including its header row."""
    header = reader.read_header(path, fmt, delimiter)
    report = validate_rows(
        spec,
        reader.iter_rows(path, fmt, delimiter=delimiter),
        max_errors=max_errors,
        sample=sample,
        strict=strict,
    )
    report.source = path.name
    missing = [name for name in spec.required if name not in header]
    if missing:
        report.missing_columns = missing
        report.violation_count += len(missing)
        for name in missing:
            report.violations.insert(
                0,
                Violation(
                    location="header",
                    column=name,
                    message="required column is missing from this file",
                ),
            )
    return report


def check_lock(spec: SchemaSpec, lock_path: pathlib.Path) -> tuple[str, str]:
    """Compare a schema file with a lock file; return (status, detail)."""
    if not lock_path.exists():
        return "missing", str(lock_path) + " not found; generate one with infer --lock"
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return "invalid", str(lock_path) + ": " + str(exc)
    if not isinstance(payload, dict):
        return "invalid", str(lock_path) + ": expected a JSON object"
    recorded = payload.get("contract_sha256")
    current = spec.computed_hash()
    if recorded == current:
        return "ok", "schema matches the lock (" + current[:12] + ")"
    return (
        "drift",
        "schema hash "
        + current[:12]
        + " does not match the lock "
        + str(recorded)[:12]
        + "; the contract changed since it was pinned",
    )
