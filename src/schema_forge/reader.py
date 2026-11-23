"""Streaming readers for CSV, TSV, JSON Lines and JSON array documents.

Every reader yields (location, row) pairs where location is a human locator
such as 'row 42' or 'line 17' and row maps column name to the raw value. Rows
are produced one at a time so memory stays flat for CSV, TSV and JSON Lines,
which is the format family people actually stream from warehouses.
"""

from __future__ import annotations

import csv
import json
import pathlib
import sys
from collections.abc import Iterator
from typing import Any

FORMATS = ("csv", "tsv", "jsonl", "json")

JSONL_EXTENSIONS = {".jsonl", ".ndjson"}
JSON_EXTENSIONS = {".json"}


class InputError(Exception):
    """Raised when an input file cannot be read as the requested format."""


def guess_format(path: pathlib.Path) -> str:
    """Return the format implied by the file extension, defaulting to CSV."""
    suffix = path.suffix.lower()
    if suffix in JSONL_EXTENSIONS:
        return "jsonl"
    if suffix in JSON_EXTENSIONS:
        return "json"
    if suffix == ".tsv":
        return "tsv"
    return "csv"


def normalise_format(path: pathlib.Path, explicit: str | None) -> str:
    """Resolve an explicit format or guess from the path, validating the result."""
    if explicit and explicit != "auto":
        if explicit not in FORMATS:
            raise InputError(
                "unknown format " + repr(explicit) + "; choose one of " + ", ".join(FORMATS)
            )
        return explicit
    return guess_format(path)


def to_text(value: Any) -> str | None:
    """Render a raw cell value as the text the detectors reason about.

    None and empty strings are nulls. Booleans become 'true'/'false' so a JSON
    boolean column and a CSV boolean column infer the same type. Nested arrays
    and objects are rendered as compact JSON.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value if value != "" else None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _read_delimited(
    path: pathlib.Path, delimiter: str, encoding: str
) -> Iterator[tuple[str, dict[str, Any]]]:
    with path.open("r", encoding=encoding, newline="") as handle:
        csv_reader = csv.reader(handle, delimiter=delimiter)
        try:
            header = next(csv_reader)
        except StopIteration:
            return
        header = [name.strip() for name in header]
        if not header or all(name == "" for name in header):
            raise InputError(
                path.name + ": the first row is empty; delimited input needs a header row"
            )
        seen: dict[str, int] = {}
        for index, name in enumerate(header):
            if name in seen:
                seen[name] += 1
                header[index] = name + "_" + str(seen[name])
            else:
                seen[name] = 0
        for line_number, cells in enumerate(csv_reader, start=2):
            if not cells:
                continue
            row: dict[str, Any] = {}
            for index, name in enumerate(header):
                row[name] = cells[index] if index < len(cells) else None
            if len(cells) > len(header):
                row["__extra__"] = cells[len(header) :]
            yield "row " + str(line_number), row


def _read_jsonl(path: pathlib.Path, encoding: str) -> Iterator[tuple[str, dict[str, Any]]]:
    with path.open("r", encoding=encoding) as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise InputError(
                    path.name
                    + ": line "
                    + str(line_number)
                    + " is not valid JSON ("
                    + exc.msg
                    + " at column "
                    + str(exc.colno)
                    + ")"
                ) from exc
            if not isinstance(payload, dict):
                raise InputError(
                    path.name
                    + ": line "
                    + str(line_number)
                    + " holds a JSON "
                    + type(payload).__name__
                    + ", expected an object per line"
                )
            yield "line " + str(line_number), payload


def _read_json_array(path: pathlib.Path, encoding: str) -> Iterator[tuple[str, dict[str, Any]]]:
    with path.open("r", encoding=encoding) as handle:
        try:
            payload = json.load(handle)
        except json.JSONDecodeError as exc:
            raise InputError(
                path.name
                + ": invalid JSON ("
                + exc.msg
                + " at line "
                + str(exc.lineno)
                + " column "
                + str(exc.colno)
                + ")"
            ) from exc
    if isinstance(payload, dict):
        items: list[Any] = [payload]
    elif isinstance(payload, list):
        items = payload
    else:
        raise InputError(path.name + ": expected a JSON array of objects or a single object")
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise InputError(
                path.name
                + ": item "
                + str(index)
                + " is a JSON "
                + type(item).__name__
                + ", expected an object"
            )
        yield "item " + str(index), item


def iter_rows(
    path: pathlib.Path,
    fmt: str | None = None,
    *,
    delimiter: str | None = None,
    encoding: str = "utf-8-sig",
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield (location, row) for every data row of path."""
    if not path.exists():
        raise InputError(str(path) + ": no such file")
    if path.is_dir():
        raise InputError(str(path) + ": is a directory, expected a data file")
    resolved = normalise_format(path, fmt)
    if resolved in {"csv", "tsv"}:
        sep = delimiter or ("\t" if resolved == "tsv" else ",")
        if len(sep) != 1:
            raise InputError("--delimiter must be a single character")
        yield from _read_delimited(path, sep, encoding)
    elif resolved == "jsonl":
        yield from _read_jsonl(path, encoding)
    else:
        yield from _read_json_array(path, encoding)


def read_header(
    path: pathlib.Path, fmt: str | None = None, delimiter: str | None = None
) -> list[str]:
    """Return the column names of path without consuming more than the first row."""
    for _, row in iter_rows(path, fmt, delimiter=delimiter):
        names = [name for name in row if name != "__extra__"]
        if names:
            return names
    return []


def warn(message: str) -> None:
    """Write a warning line to stderr."""
    sys.stderr.write(message + "\n")
