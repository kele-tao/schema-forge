"""schema-forge: infer, version and enforce data contracts from CSV and JSON.

Public API:

    from schema_forge import infer_file, diff_schemas, validate_file

The command line interface is the primary product; this module exists so the
engine can be embedded in a CI script without shelling out.
"""

from __future__ import annotations

import pathlib
from typing import Any

from schema_forge.diff import DiffResult, diff_specs
from schema_forge.infer import InferenceResult, Options, infer
from schema_forge.types import Contract
from schema_forge.validate import (
    Report,
    SchemaError,
    SchemaSpec,
    load_schema,
    validate_file,
)

__version__ = "1.0.0"

__all__ = [
    "Contract",
    "DiffResult",
    "InferenceResult",
    "Options",
    "Report",
    "SchemaError",
    "SchemaSpec",
    "__version__",
    "diff_schemas",
    "infer_file",
    "load_schema",
    "validate",
    "validate_file",
]


def infer_file(
    path: str | pathlib.Path,
    *,
    name: str | None = None,
    fmt: str | None = None,
    delimiter: str | None = None,
    options: Options | None = None,
) -> InferenceResult:
    """Infer a data contract from path (see schema_forge.infer.infer)."""
    return infer(pathlib.Path(path), name=name, fmt=fmt, delimiter=delimiter, options=options)


def diff_schemas(old: str | pathlib.Path, new: str | pathlib.Path) -> DiffResult:
    """Diff two schema files and classify each change as breaking or compatible."""
    return diff_specs(load_schema(pathlib.Path(old)), load_schema(pathlib.Path(new)))


def validate(
    path: str | pathlib.Path,
    schema: str | pathlib.Path,
    **kwargs: Any,
) -> Report:
    """Validate a data file against a schema file."""
    return validate_file(pathlib.Path(path), load_schema(pathlib.Path(schema)), **kwargs)
