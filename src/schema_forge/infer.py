"""The inference engine: bounded probe pass, verification pass, one contract."""

from __future__ import annotations

import pathlib
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from schema_forge import detect, reader
from schema_forge.types import Candidate, Column, Contract, Evidence, Pii

TYPE_SPECIFICITY = {
    "uuid": 0.99,
    "email": 0.99,
    "bool": 0.98,
    "url": 0.95,
    "int": 0.97,
    "date": 0.96,
    "datetime": 0.96,
    "float": 0.95,
    "currency": 0.93,
    "enum": 0.90,
    "categorical": 0.80,
    "text": 0.60,
}

# Order in which structural candidates are tested when picking a winner.
PRIORITY = ("uuid", "email", "url", "datetime", "date", "bool", "currency")

PII_KINDS = ("card", "iban", "ssn", "email", "phone")

# Columns that are already a well-defined type cannot also be phone numbers etc.
PII_INCOMPATIBLE = {
    "date": {"card", "iban", "ssn", "email", "phone"},
    "datetime": {"card", "iban", "ssn", "email", "phone"},
    "bool": {"card", "iban", "ssn", "email", "phone"},
    "uuid": {"card", "iban", "ssn", "email", "phone"},
    "url": {"card", "iban", "ssn", "email", "phone"},
    "email": {"card", "iban", "ssn", "phone"},
    "int": {"iban", "email", "phone"},
    "float": {"iban", "email", "phone"},
    "currency": {"iban", "email", "phone"},
}

DEPTH_FLOOR = 20

# A column whose distinct/rows ratio is below this is a dictionary, not free text.
DICTIONARY_RATIO = 0.05


@dataclass(slots=True)
class Options:
    """Tunable inference knobs, all exposed on the CLI."""

    enum_threshold: int = 24
    enum_max_ratio: float = 0.2
    enum_min_rows: int = 20
    categorical_max_distinct: int = 64
    probe_rows: int = 2000
    max_distinct: int = 5000
    detect_pii: bool = True
    evidence_rows: int = 3
    pattern_sample: int = 300


@dataclass(slots=True)
class Accumulator:
    """Bounded-memory per-column statistics collected while streaming."""

    name: str
    seen: int = 0
    nulls: int = 0
    filled: int = 0
    counts: Counter = field(default_factory=Counter)
    value_counts: Counter = field(default_factory=Counter)
    distinct: set = field(default_factory=set)
    distinct_capped: bool = False
    enum_overflow: bool = False
    length_min: int | None = None
    length_max: int = 0
    num_min: float | None = None
    num_max: float | None = None
    num_sum: float = 0.0
    num_count: int = 0
    formats: Counter = field(default_factory=Counter)
    pii: Counter = field(default_factory=Counter)
    samples: list[tuple[str, str]] = field(default_factory=list)
    sample_values: list[str] = field(default_factory=list)
    pattern_values: list[str] = field(default_factory=list)
    mismatches: list[tuple[str, str]] = field(default_factory=list)
    mismatch_count: int = 0
    verify_matched: int = 0
    verify_total: int = 0
    allowed: set[str] | None = None
    numeric_values: list[float] = field(default_factory=list)

    def observe_null(self) -> None:
        """Record a missing value."""
        self.seen += 1
        self.nulls += 1

    def observe_probe(self, location: str, value: str, options: Options) -> None:
        """Record every candidate match for one value during the probe phase."""
        self.seen += 1
        self.filled += 1
        self._observe_shape(value, options)
        matches = detect.structural_matches(value)
        for kind in matches:
            self.counts[kind] += 1
        parsed = detect.parse_number(value)
        if parsed is not None:
            self.num_count += 1
            self.num_sum += parsed
            self.num_min = parsed if self.num_min is None else min(self.num_min, parsed)
            self.num_max = parsed if self.num_max is None else max(self.num_max, parsed)
        if len(self.samples) < 5:
            self.samples.append((location, value))
            self.sample_values.append(value)
        if "date" in matches:
            for fmt in detect.date_formats_of(value):
                self.formats[fmt] += 1
        if options.detect_pii:
            self.collect_pii(value)

    def _observe_shape(self, value: str, options: Options) -> None:
        length = len(value)
        self.length_min = length if self.length_min is None else min(self.length_min, length)
        self.length_max = max(self.length_max, length)
        if value not in self.distinct:
            if len(self.distinct) < options.max_distinct:
                self.distinct.add(value)
            else:
                self.distinct_capped = True
            if len(self.distinct) > options.enum_threshold:
                self.enum_overflow = True
        self.value_counts[value] += 1
        if len(self.pattern_values) < options.pattern_sample:
            self.pattern_values.append(value)

    def collect_pii(self, value: str) -> None:
        """Count a PII hit for a non-empty value; the first matcher wins."""
        for kind in PII_KINDS:
            if detect.PII_MATCHERS[kind](value):
                self.pii[kind] += 1
                return

    def observe_verify(self, location: str, value: str, kind: str, options: Options) -> None:
        """Verify the provisionally chosen kind against every later value.

        This is the hot loop: it runs once per cell of the file, so it keeps a
        tight local-variable core and avoids helper calls that allocate.
        """
        filled = self.filled + 1
        self.filled = filled
        self.verify_total += 1
        length = len(value)
        low = self.length_min
        if low is None or length < low:
            self.length_min = length
        if length > self.length_max:
            self.length_max = length
        counts = self.value_counts
        if value in self.distinct:
            counts[value] += 1
        elif len(self.distinct) < options.max_distinct:
            self.distinct.add(value)
            counts[value] += 1
        else:
            self.distinct_capped = True
        if kind in ("int", "float"):
            if detect.is_int(value):
                parsed = float(int(value))
            elif detect.is_float(value):
                parsed = float(value)
            else:
                parsed = detect.parse_currency(value) if kind == "float" else None
            if parsed is not None:
                self.verify_matched += 1
                self.num_count += 1
                self.num_sum += parsed
                if self.num_min is None or parsed < self.num_min:
                    self.num_min = parsed
                if self.num_max is None or parsed > self.num_max:
                    self.num_max = parsed
                return
        elif kind in ("enum", "categorical") and self.allowed is not None:
            if value in self.allowed:
                self.verify_matched += 1
                return
        else:
            matcher = VERIFIERS.get(kind)
            if matcher is None or matcher(value):
                self.verify_matched += 1
                return
        self.mismatch_count += 1
        if len(self.mismatches) < options.evidence_rows:
            self.mismatches.append((location, value))

    def stats(self) -> dict[str, Any]:
        """Return the compact statistics block written into the schema."""
        payload: dict[str, Any] = {
            "min_length": self.length_min,
            "max_length": self.length_max,
            "distinct": len(self.distinct),
            "filled": self.filled,
        }
        if self.num_count > 0 and self.num_min is not None and self.num_max is not None:
            payload["min"] = _clean_number(self.num_min)
            payload["max"] = _clean_number(self.num_max)
            payload["mean"] = round(self.num_sum / self.num_count, 6)
        return payload


def _clean_number(value: float) -> int | float:
    return int(value) if float(value).is_integer() else round(value, 6)


VERIFIERS = {
    "int": detect.is_int,
    "float": detect.is_float,
    "bool": detect.is_bool,
    "date": detect.is_date,
    "datetime": detect.is_datetime,
    "email": detect.is_email,
    "url": detect.is_url,
    "uuid": detect.is_uuid,
    "currency": detect.is_currency,
}


def verifier(kind: str, value: str) -> bool:
    """Return True when value satisfies the structural kind."""
    matcher = VERIFIERS.get(kind)
    return True if matcher is None else matcher(value)


def choose_kind(acc: Accumulator, options: Options) -> str:
    """Pick the most specific type whose matcher accepted every probed value."""
    filled = acc.filled
    if filled == 0:
        return "text"
    counts = acc.counts
    if counts["int"] == filled:
        return "int"
    if counts["int"] + counts["float"] == filled:
        return "float"
    for kind in PRIORITY:
        if counts[kind] == filled:
            return kind
    if counts["currency"] == filled:
        return "currency"
    distinct = len(acc.distinct)
    if (
        filled >= options.enum_min_rows
        and not acc.enum_overflow
        and distinct >= 2
        and distinct <= options.enum_threshold
        and distinct / filled <= options.enum_max_ratio
    ):
        return "enum"
    if (
        filled >= options.enum_min_rows
        and not acc.distinct_capped
        and distinct <= options.categorical_max_distinct
        and distinct / filled <= DICTIONARY_RATIO
    ):
        return "categorical"
    return "text"


def _levenshtein_within_one(left: str, right: str) -> bool:
    if abs(len(left) - len(right)) > 1:
        return False
    if left == right:
        return True
    if len(left) == len(right):
        return sum(1 for a, b in zip(left, right, strict=False) if a != b) == 1
    short, long = (left, right) if len(left) < len(right) else (right, left)
    index = 0
    while index < len(short) and short[index] == long[index]:
        index += 1
    return short[index:] == long[index + 1 :]


def detect_typos(counts: Counter) -> dict[str, str]:
    """Return a mapping of a rare enum variant to the likely intended value."""
    typos: dict[str, str] = {}
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    for rare, rare_count in ordered:
        for frequent, frequent_count in ordered:
            if rare == frequent or len(rare) < 4 or len(frequent) < 4:
                continue
            if frequent_count < 3 * max(1, rare_count):
                continue
            if _levenshtein_within_one(rare, frequent):
                typos[rare] = frequent
                break
    return typos


def confidence_parts(acc: Accumulator, kind: str, support: float, filled: int) -> dict[str, float]:
    """Return the four factors multiplied into one column's confidence."""
    fill_rate = round((filled / acc.seen) if acc.seen else 0.0, 4)
    depth = 1.0 if filled >= DEPTH_FLOOR else round(0.8 + 0.2 * (filled / DEPTH_FLOOR), 4)
    return {
        "fill_rate": fill_rate,
        "type_support": round(support, 4),
        "specificity": TYPE_SPECIFICITY.get(kind, 0.6),
        "sample_depth": depth,
    }


def pick_pii(acc: Accumulator, kind: str, options: Options) -> tuple[str, int] | None:
    """Choose the PII kind worth reporting for a column, if any."""
    if not options.detect_pii or not acc.pii:
        return None
    blocked = PII_INCOMPATIBLE.get(kind, set())
    for pii_kind, hits in acc.pii.most_common():
        if pii_kind in blocked:
            continue
        if hits / max(1, acc.filled) < 0.5:
            continue
        return pii_kind, hits
    return None


def finalize_column(acc: Accumulator, kind: str, options: Options) -> Column:
    """Turn accumulated counters into a Column with confidence and evidence."""
    filled = max(acc.filled, 1)
    if acc.verify_total:
        support = acc.verify_matched / acc.verify_total
    elif kind in ("int", "float"):
        support = (acc.counts["int"] + acc.counts["float"]) / filled
    elif kind in ("enum", "categorical", "text"):
        support = 1.0
    else:
        support = acc.counts[kind] / filled
    support = min(1.0, max(0.0, support))
    parts = confidence_parts(acc, kind, support, acc.filled)
    confidence = 1.0
    for value in parts.values():
        confidence *= value
    confidence = round(min(1.0, max(0.0, confidence)), 2)

    candidates = [
        Candidate(kind=name, score=count / filled, matched=count)
        for name, count in sorted(acc.counts.items(), key=lambda item: (-item[1], item[0]))
        if count > 0
    ]
    evidence = [
        Evidence(location=location, value=value, matched=detect.structural_matches(value))
        for location, value in acc.samples[: options.evidence_rows]
    ]

    column = Column(
        name=acc.name,
        kind=kind,
        confidence=confidence,
        nullable=acc.nulls > 0,
        nulls=acc.nulls,
        seen=acc.seen,
        distinct=len(acc.distinct),
        distinct_capped=acc.distinct_capped,
        sample_size=min(acc.seen, options.probe_rows),
        stats=acc.stats(),
        candidates=candidates,
        confidence_parts=parts,
        evidence=evidence,
    )

    if kind == "enum":
        ordered = sorted(acc.distinct, key=lambda value: (-acc.value_counts[value], value))
        column.enum_values = ordered
        column.enum_typos = detect_typos(acc.value_counts)
    if kind == "date" and acc.formats:
        column.formats = [fmt for fmt, _count in acc.formats.most_common()]
        if len(column.formats) > 1:
            column.notes.append(
                "mixed date formats: "
                + ", ".join(column.formats)
                + "; day/month order is ambiguous, pin one format downstream"
            )
    if kind in ("text", "categorical"):
        pattern = detect.induce_pattern(acc.pattern_values)
        if pattern:
            column.pattern = pattern
    if acc.mismatch_count:
        sample = ", ".join(location + "=" + repr(value) for location, value in acc.mismatches)
        column.notes.append(
            str(acc.mismatch_count)
            + " value(s) after the "
            + str(options.probe_rows)
            + "-row probe did not match "
            + kind
            + " ("
            + sample
            + "); the producer may be drifting"
        )
    pii = pick_pii(acc, kind, options)
    if pii is not None:
        pii_kind, hits = pii
        ratio = hits / filled
        example = ""
        for value in acc.sample_values:
            if detect.PII_MATCHERS[pii_kind](value):
                example = detect.mask_value(pii_kind, value)
                break
        column.pii = Pii(
            kind=pii_kind,
            ratio=ratio,
            mask_example=example or "*" * 8,
            advice=detect.MASK_ADVICE[pii_kind],
        )
        column.notes.append(
            "PII "
            + pii_kind
            + " detected in "
            + str(hits)
            + "/"
            + str(filled)
            + " values ("
            + str(round(ratio * 100))
            + "%)"
        )
    return column


@dataclass(slots=True)
class InferenceResult:
    """The inferred contract plus the provenance a reviewer needs."""

    contract: Contract
    path: pathlib.Path
    format: str
    rows: int
    warnings: list[str] = field(default_factory=list)


def infer(
    path: pathlib.Path,
    *,
    name: str | None = None,
    fmt: str | None = None,
    delimiter: str | None = None,
    options: Options | None = None,
) -> InferenceResult:
    """Infer a Contract from path in one streaming pass with bounded memory."""
    opts = options or Options()
    accumulators: dict[str, Accumulator] = {}
    order: list[str] = []
    probe_done = False
    kinds: dict[str, str] = {}
    warnings: list[str] = []
    rows = 0
    ragged = 0

    for location, raw in reader.iter_rows(path, fmt, delimiter=delimiter):
        rows += 1
        for column_name in raw:
            if column_name == "__extra__":
                ragged += 1
                continue
            if column_name not in accumulators:
                accumulators[column_name] = Accumulator(name=column_name)
                order.append(column_name)
                if probe_done:
                    warnings.append(
                        "column "
                        + repr(column_name)
                        + " first appeared at "
                        + location
                        + "; it was absent from the probe window"
                    )
        if not probe_done:
            for column_name in order:
                acc = accumulators[column_name]
                value = reader.to_text(raw.get(column_name))
                if value is None:
                    acc.observe_null()
                else:
                    acc.observe_probe(location, value, opts)
            if rows >= opts.probe_rows:
                probe_done = True
                kinds = {
                    column_name: choose_kind(accumulators[column_name], opts)
                    for column_name in order
                }
                for column_name in order:
                    if kinds[column_name] in ("enum", "categorical"):
                        accumulators[column_name].allowed = set(accumulators[column_name].distinct)
        else:
            for column_name in order:
                acc = accumulators[column_name]
                value = reader.to_text(raw.get(column_name))
                if value is None:
                    acc.observe_null()
                else:
                    acc.observe_verify(location, value, kinds[column_name], opts)

    if rows == 0:
        raise reader.InputError(str(path) + ": no data rows found (is the file empty?)")
    if not probe_done:
        kinds = {column_name: choose_kind(accumulators[column_name], opts) for column_name in order}
    if ragged:
        warnings.append(
            str(ragged) + " row(s) had more cells than the header; the extras were ignored"
        )
    columns = [
        finalize_column(accumulators[column_name], kinds[column_name], opts)
        for column_name in order
    ]
    contract = Contract(
        title=name or path.stem,
        source=path.name,
        fmt=reader.normalise_format(path, fmt),
        rows=rows,
        columns=columns,
        warnings=warnings,
    )
    return InferenceResult(
        contract=contract, path=path, format=contract.fmt, rows=rows, warnings=warnings
    )
