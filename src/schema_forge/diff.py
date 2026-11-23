"""Semantic schema diff: classify every change as breaking or compatible."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from schema_forge.validate import SchemaSpec

BREAKING = "breaking"
COMPATIBLE = "compatible"

TYPE_WIDENING: dict[str, set[str]] = {
    "integer": {"number"},
    "boolean": {"string", "integer", "number"},
    "string": {"integer", "number", "boolean"},
}

FORMATS = {"date", "date-time", "email", "uri", "uuid"}


@dataclass(slots=True)
class Change:
    """One classified difference between two contracts."""

    column: str
    kind: str
    severity: str
    message: str
    guidance: str

    def to_json(self) -> dict[str, Any]:
        """Return a JSON-ready representation."""
        return {
            "column": self.column,
            "kind": self.kind,
            "severity": self.severity,
            "message": self.message,
            "guidance": self.guidance,
        }


@dataclass(slots=True)
class DiffResult:
    """The full diff between an old and a new schema."""

    old_title: str
    new_title: str
    changes: list[Change] = field(default_factory=list)

    @property
    def breaking(self) -> list[Change]:
        """Changes that will reject previously valid rows."""
        return [change for change in self.changes if change.severity == BREAKING]

    @property
    def compatible(self) -> list[Change]:
        """Changes that keep every previously valid row valid."""
        return [change for change in self.changes if change.severity == COMPATIBLE]

    @property
    def ok(self) -> bool:
        """True when the new contract does not break existing producers."""
        return not self.breaking

    def to_json(self) -> dict[str, Any]:
        """Return a JSON-ready representation."""
        return {
            "old": self.old_title,
            "new": self.new_title,
            "ok": self.ok,
            "breaking": len(self.breaking),
            "compatible": len(self.compatible),
            "changes": [change.to_json() for change in self.changes],
        }


def _format_of(spec: dict[str, Any]) -> str | None:
    fmt = spec.get("format")
    return str(fmt) if isinstance(fmt, str) else None


def _type_of(spec: dict[str, Any]) -> str:
    json_type = spec.get("type")
    return str(json_type) if isinstance(json_type, str) else "any"


def _classify_type_change(old_type: str, new_type: str) -> tuple[str, str, str]:
    if old_type == new_type:
        return "", "", ""
    if new_type in TYPE_WIDENING.get(old_type, set()):
        return (
            "type-widened",
            COMPATIBLE,
            "readers that expected the old type still succeed",
        )
    return (
        "type-narrowed",
        BREAKING,
        "map old values to the new type before switching the contract on",
    )


def diff_specs(old: SchemaSpec, new: SchemaSpec) -> DiffResult:
    """Classify every difference between two schemas."""
    result = DiffResult(old_title=old.title, new_title=new.title)
    old_props = old.properties
    new_props = new.properties
    for name in sorted(set(old_props) | set(new_props)):
        if name not in new_props:
            was_required = name in old.required
            result.changes.append(
                Change(
                    column=name,
                    kind="column-removed",
                    severity=BREAKING if was_required else COMPATIBLE,
                    message="column "
                    + repr(name)
                    + (
                        " was required and is gone" if was_required else " was optional and is gone"
                    ),
                    guidance="keep the column in the contract for one release, then remove it"
                    if was_required
                    else "nothing for producers; stop reading the column",
                )
            )
            continue
        if name not in old_props:
            required_now = name in new.required
            result.changes.append(
                Change(
                    column=name,
                    kind="column-added",
                    severity=BREAKING if required_now else COMPATIBLE,
                    message="column "
                    + repr(name)
                    + " is new"
                    + (" and required" if required_now else " and optional"),
                    guidance="backfill the column in every producer before requiring it"
                    if required_now
                    else "nothing; the column is optional",
                )
            )
            continue
        old_spec = old_props[name]
        new_spec = new_props[name]
        old_required = name in old.required
        new_required = name in new.required
        if old_required != new_required:
            result.changes.append(
                Change(
                    column=name,
                    kind="required-flip",
                    severity=BREAKING if new_required else COMPATIBLE,
                    message="column "
                    + repr(name)
                    + (" became required" if new_required else " became optional"),
                    guidance="fill every null before switching the new contract on"
                    if new_required
                    else "nothing; loosening a contract cannot break old data",
                )
            )
        old_type = _type_of(old_spec)
        new_type = _type_of(new_spec)
        kind, severity, guidance = _classify_type_change(old_type, new_type)
        if kind:
            result.changes.append(
                Change(
                    column=name,
                    kind=kind,
                    severity=severity,
                    message="type changed from "
                    + old_type
                    + " to "
                    + new_type
                    + " for column "
                    + repr(name),
                    guidance=guidance,
                )
            )
        old_fmt = _format_of(old_spec)
        new_fmt = _format_of(new_spec)
        if old_fmt != new_fmt:
            if old_fmt is None:
                result.changes.append(
                    Change(
                        column=name,
                        kind="format-added",
                        severity=BREAKING,
                        message="format " + repr(new_fmt) + " added to column " + repr(name),
                        guidance="verify every producer already emits " + str(new_fmt),
                    )
                )
            elif new_fmt is None:
                result.changes.append(
                    Change(
                        column=name,
                        kind="format-removed",
                        severity=COMPATIBLE,
                        message="format " + repr(old_fmt) + " removed from column " + repr(name),
                        guidance="none; the contract got weaker on purpose",
                    )
                )
            else:
                result.changes.append(
                    Change(
                        column=name,
                        kind="format-changed",
                        severity=BREAKING,
                        message="format changed from "
                        + repr(old_fmt)
                        + " to "
                        + repr(new_fmt)
                        + " for column "
                        + repr(name),
                        guidance="migrate producers to the new format in the same release",
                    )
                )
        old_pattern = old_spec.get("pattern")
        new_pattern = new_spec.get("pattern")
        if old_pattern != new_pattern:
            severity = BREAKING if new_pattern is not None else COMPATIBLE
            result.changes.append(
                Change(
                    column=name,
                    kind="pattern-added" if new_pattern is not None else "pattern-removed",
                    severity=severity,
                    message="pattern "
                    + ("added " if new_pattern is not None else "removed ")
                    + str(new_pattern)
                    + " on column "
                    + repr(name),
                    guidance="spot-check real data against the new pattern before shipping"
                    if severity == BREAKING
                    else "none",
                )
            )
        old_enum = old_spec.get("enum")
        new_enum = new_spec.get("enum")
        old_set = {str(item) for item in old_enum} if isinstance(old_enum, list) else None
        new_set = {str(item) for item in new_enum} if isinstance(new_enum, list) else None
        if old_set is not None and new_set is not None:
            removed = sorted(old_set - new_set)
            added = sorted(new_set - old_set)
            if removed:
                result.changes.append(
                    Change(
                        column=name,
                        kind="enum-shrunk",
                        severity=BREAKING,
                        message="enum on "
                        + repr(name)
                        + " dropped "
                        + ", ".join(map(repr, removed[:6])),
                        guidance="keep reading the old values for one release, "
                        "or migrate them first",
                    )
                )
            if added:
                result.changes.append(
                    Change(
                        column=name,
                        kind="enum-grew",
                        severity=COMPATIBLE,
                        message="enum on "
                        + repr(name)
                        + " gained "
                        + ", ".join(map(repr, added[:6])),
                        guidance="downstream switches may need a new branch",
                    )
                )
        elif old_set is None and new_set is not None:
            # A free-form string column that now has an enum is a tightening. When
            # the type changed as well (boolean -> string in a drifted export) the
            # type change is the real news and the enum just lists what arrived.
            narrowed = old_type == "string"
            result.changes.append(
                Change(
                    column=name,
                    kind="enum-added" if narrowed else "enum-introduced",
                    severity=BREAKING if narrowed else COMPATIBLE,
                    message="an enum was added to column " + repr(name),
                    guidance="confirm every producer emits one of the listed values"
                    if narrowed
                    else "none; the enum lists exactly the values already seen",
                )
            )
        elif old_set is not None and new_set is None:
            result.changes.append(
                Change(
                    column=name,
                    kind="enum-removed",
                    severity=COMPATIBLE,
                    message="the enum on " + repr(name) + " was removed",
                    guidance="none",
                )
            )
    if old.additional_properties and not new.additional_properties:
        result.changes.append(
            Change(
                column="*",
                kind="unknown-columns-rejected",
                severity=BREAKING,
                message="the contract now rejects columns it does not declare",
                guidance=(
                    "declare every column a producer sends, or run validate without --strict"
                ),
            )
        )
    result.changes.sort(
        key=lambda change: (change.severity != BREAKING, change.column, change.kind)
    )
    return result


def render_diff(result: DiffResult, color: bool = True) -> str:
    """Render a DiffResult as the human-readable CLI report."""

    def paint(text: str, code: str) -> str:
        return "\x1b[" + code + "m" + text + "\x1b[0m" if color else text

    lines: list[str] = []
    lines.append(paint("schema-forge diff: " + result.old_title + " -> " + result.new_title, "1"))
    lines.append("")
    if not result.changes:
        lines.append(paint("  no changes: the two contracts are identical", "32"))
        return "\n".join(lines)
    for change in result.changes:
        if change.severity == BREAKING:
            marker = paint("BREAKING ", "31;1")
        else:
            marker = paint("compat   ", "32")
        lines.append("  " + marker + change.kind + " [" + change.column + "]")
        lines.append("           " + change.message)
        if change.guidance and change.guidance != "none":
            lines.append("           fix: " + change.guidance)
    lines.append("")
    if result.breaking:
        lines.append(
            paint(
                str(len(result.breaking))
                + " breaking change(s): this contract breaks existing producers",
                "31;1",
            )
        )
    else:
        lines.append(paint("0 breaking changes: safe to roll out", "32"))
    if result.compatible:
        lines.append(str(len(result.compatible)) + " compatible change(s)")
    return "\n".join(lines)
