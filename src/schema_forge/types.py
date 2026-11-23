"""Data model for inferred contracts plus JSON Schema and lock-file emission."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

GENERATOR = "schema-forge/1.0.0"
DIALECT = "https://json-schema.org/draft/2020-12/schema"
ID_BASE = "https://github.com/kele-tao/schema-forge/contracts"
LOCKFILE_VERSION = 1

STRING_KINDS = {
    "date",
    "datetime",
    "email",
    "url",
    "uuid",
    "currency",
    "enum",
    "categorical",
    "text",
}
NUMERIC_KINDS = {"int", "float"}
PATTERN_KINDS = {"text", "categorical", "currency"}


def slugify(text: str) -> str:
    """Return a lower-case url-safe slug for *text*."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "contract"


@dataclass(slots=True)
class Pii:
    """A sensitive-data finding for one column."""

    kind: str
    ratio: float
    mask_example: str
    advice: str

    def to_json(self) -> dict[str, Any]:
        """Return a JSON-ready representation."""
        return {
            "kind": self.kind,
            "match_ratio": round(self.ratio, 4),
            "mask_example": self.mask_example,
            "advice": self.advice,
        }


@dataclass(slots=True)
class Candidate:
    """One type candidate considered for a column, with its sample score."""

    kind: str
    score: float
    matched: int

    def to_json(self) -> dict[str, Any]:
        """Return a JSON-ready representation."""
        return {"kind": self.kind, "score": round(self.score, 4), "matched": self.matched}


@dataclass(slots=True)
class Evidence:
    """One sampled row that supports (or contradicts) the inferred type."""

    location: str
    value: str
    matched: list[str]

    def to_json(self) -> dict[str, Any]:
        """Return a JSON-ready representation."""
        return {"location": self.location, "value": self.value, "matched": self.matched}


@dataclass(slots=True)
class Column:
    """Everything schema-forge knows about one inferred column."""

    name: str
    kind: str = "text"
    confidence: float = 0.0
    nullable: bool = True
    nulls: int = 0
    seen: int = 0
    distinct: int = 0
    distinct_capped: bool = False
    sample_size: int = 0
    stats: dict[str, Any] = field(default_factory=dict)
    enum_values: list[str] = field(default_factory=list)
    enum_typos: dict[str, str] = field(default_factory=dict)
    formats: list[str] = field(default_factory=list)
    pattern: str | None = None
    pii: Pii | None = None
    candidates: list[Candidate] = field(default_factory=list)
    confidence_parts: dict[str, float] = field(default_factory=dict)
    evidence: list[Evidence] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def null_ratio(self) -> float:
        """Fraction of seen rows where this column was empty."""
        return round(self.nulls / self.seen, 4) if self.seen else 0.0

    @property
    def required(self) -> bool:
        """True when the column is non-nullable and present in every row."""
        return not self.nullable

    def display_value(self, value: str) -> str:
        """Return *value*, masked when the column carries PII."""
        from schema_forge.detect import mask_value

        return mask_value(self.pii.kind, value) if self.pii else value

    def summary(self) -> str:
        """Return a one-line constraint summary used in the Markdown contract."""
        bits: list[str] = []
        if self.pattern:
            bits.append(f"pattern {self.pattern}")
        if self.kind == "enum" and self.enum_values:
            shown = ", ".join(repr(value) for value in self.enum_values[:8])
            extra = (
                "" if len(self.enum_values) <= 8 else " (+%d more)" % (len(self.enum_values) - 8)
            )
            bits.append("one of " + shown + extra)
        if self.formats:
            bits.append("formats " + ", ".join(self.formats))
        if self.pii:
            bits.append("PII " + self.pii.kind)
        return "; ".join(bits) if bits else "-"

    def _description(self) -> str:
        percent = self.null_ratio * 100
        parts = [f"{self.kind} column inferred with confidence {self.confidence:.2f}"]
        parts.append("%d%s distinct values" % (self.distinct, "+" if self.distinct_capped else ""))
        if self.nulls:
            parts.append(f"{percent:.1f}% empty")
        if self.pii:
            parts.append(f"PII ({self.pii.kind}): {self.pii.advice}")
        return "; ".join(parts)

    def to_schema_property(self) -> dict[str, Any]:
        """Return the JSON Schema fragment plus the x-schema-forge evidence."""
        kind = self.kind
        spec: dict[str, Any]
        if kind == "int":
            spec = {"type": "integer"}
        elif kind == "float":
            spec = {"type": "number"}
        elif kind == "bool":
            spec = {"type": "boolean"}
        elif kind == "date":
            spec = {"type": "string"}
            if self.formats == ["%Y-%m-%d"]:
                spec["format"] = "date"
        elif kind == "datetime":
            spec = {"type": "string", "format": "date-time"}
        elif kind == "email":
            spec = {"type": "string", "format": "email"}
        elif kind == "url":
            spec = {"type": "string", "format": "uri"}
        elif kind == "uuid":
            spec = {"type": "string", "format": "uuid"}
        elif kind == "enum":
            spec = {"type": "string", "enum": list(self.enum_values)}
        else:
            spec = {"type": "string"}
        if self.pattern and kind in PATTERN_KINDS:
            spec["pattern"] = self.pattern
        spec["description"] = self._description()
        payload: dict[str, Any] = {
            "generator": GENERATOR,
            "type": kind,
            "confidence": self.confidence,
            "confidence_parts": dict(self.confidence_parts),
            "nullable": self.nullable,
            "null_ratio": self.null_ratio,
            "seen_rows": self.seen,
            "distinct": self.distinct,
            "sample_size": self.sample_size,
            "stats": dict(self.stats),
            "candidates": [candidate.to_json() for candidate in self.candidates],
            "evidence": [row.to_json() for row in self.evidence],
            "notes": list(self.notes),
        }
        if self.distinct_capped:
            payload["distinct_capped"] = True
        if self.enum_values:
            payload["enum"] = list(self.enum_values)
        if self.enum_typos:
            payload["enum_typos"] = dict(self.enum_typos)
        if self.formats:
            payload["formats"] = list(self.formats)
        if self.pattern:
            payload["pattern"] = self.pattern
        if self.pii:
            payload["pii"] = self.pii.to_json()
        spec["x-schema-forge"] = payload
        return spec


@dataclass(slots=True)
class Contract:
    """A whole inferred data contract for one table."""

    title: str
    source: str
    fmt: str
    rows: int
    columns: list[Column]
    warnings: list[str] = field(default_factory=list)

    def column(self, name: str) -> Column | None:
        """Return the column called *name*, if it exists."""
        for column in self.columns:
            if column.name == name:
                return column
        return None

    def required_names(self) -> list[str]:
        """Return required column names in contract order."""
        return [
            column.name for column in self.columns if column.required and column.seen == self.rows
        ]

    def enforcement(self) -> dict[str, Any]:
        """Return only the enforced part of the contract (no stats or evidence)."""
        properties: dict[str, Any] = {}
        for column in self.columns:
            spec = column.to_schema_property()
            entry: dict[str, Any] = {}
            for key in ("type", "format", "pattern", "enum"):
                if key in spec:
                    value = spec[key]
                    entry[key] = sorted(value) if key == "enum" else value
            properties[column.name] = entry
        return {
            "additionalProperties": False,
            "properties": properties,
            "required": sorted(self.required_names()),
        }

    def contract_hash(self) -> str:
        """Return the stable SHA-256 of the enforced contract."""
        return hash_enforcement(self.enforcement())

    def to_schema(self) -> dict[str, Any]:
        """Return the JSON Schema draft 2020-12 document."""
        enforcement = self.enforcement()
        digest = hash_enforcement(enforcement)
        description = (
            "Data contract inferred by %s from %s (%d rows, %d columns). "
            "Statistics and the contract hash are deterministic for identical input."
            % (GENERATOR, self.source, self.rows, len(self.columns))
        )
        return {
            "$schema": DIALECT,
            "$id": ID_BASE + "/" + slugify(self.title) + ".schema.json",
            "title": self.title,
            "description": description,
            "type": "object",
            "additionalProperties": False,
            "required": self.required_names(),
            "properties": {column.name: column.to_schema_property() for column in self.columns},
            "x-schema-forge": {
                "generator": GENERATOR,
                "source": self.source,
                "format": self.fmt,
                "rows": self.rows,
                "column_count": len(self.columns),
                "contract_hash": digest,
                "warnings": list(self.warnings),
            },
        }

    def to_lock(self) -> dict[str, Any]:
        """Return the lock document that pins the enforced contract."""
        return {
            "lockfile_version": LOCKFILE_VERSION,
            "generator": GENERATOR,
            "contract": self.title,
            "source": self.source,
            "format": self.fmt,
            "rows": self.rows,
            "column_count": len(self.columns),
            "contract_sha256": self.contract_hash(),
            "enforcement": self.enforcement(),
        }


def enforcement_from_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Extract the enforced projection from any JSON Schema object document."""
    properties: dict[str, Any] = {}
    raw_properties = schema.get("properties") or {}
    if not isinstance(raw_properties, dict):
        raw_properties = {}
    for name, spec in raw_properties.items():
        if not isinstance(spec, dict):
            continue
        entry: dict[str, Any] = {}
        for key in ("type", "format", "pattern", "enum"):
            if key in spec:
                value = spec[key]
                entry[key] = sorted(str(item) for item in value) if key == "enum" else value
        properties[str(name)] = entry
    required = schema.get("required") or []
    return {
        "additionalProperties": bool(schema.get("additionalProperties", True)),
        "properties": properties,
        "required": sorted(str(name) for name in required),
    }


def hash_enforcement(enforcement: dict[str, Any]) -> str:
    """Return the SHA-256 of a canonical JSON rendering of *enforcement*."""
    canonical = json.dumps(enforcement, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def canonical_json(payload: Any) -> str:
    """Return a stable JSON rendering of *payload* (used for hashing and tests)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
