"""Shared fixtures: small CSVs written to tmp_path, and a CLI invoker."""

from __future__ import annotations

import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"


def write_csv(path: pathlib.Path, header: list[str], rows: list[list[str]]) -> pathlib.Path:
    """Write a CSV file with a header row and return the path."""
    lines = [",".join(header)]
    for row in rows:
        cells = []
        for cell in row:
            if any(char in cell for char in ',"\n'):
                cells.append('"' + cell.replace('"', '""') + '"')
            else:
                cells.append(cell)
        lines.append(",".join(cells))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture()
def orders_csv(tmp_path: pathlib.Path) -> pathlib.Path:
    """A 40-row file with the types the inference engine must recognise."""
    header = ["id", "email", "country", "amount", "qty", "active", "created"]
    rows = []
    countries = ["US", "DE", "FR"]
    for index in range(1, 41):
        rows.append(
            [
                str(index),
                "user%d@example.com" % index if index % 20 else "",
                countries[index % 3],
                "$%d.50" % (index * 7),
                str(index % 5 + 1),
                "true" if index % 2 else "false",
                "2026-%02d-%02d" % (index % 12 + 1, index % 28 + 1),
            ]
        )
    return write_csv(tmp_path / "orders.csv", header, rows)


@pytest.fixture()
def cli():
    """Run the CLI in-process and return (exit_code, stdout, stderr)."""
    from contextlib import redirect_stderr, redirect_stdout
    from io import StringIO

    from schema_forge.cli import main

    def run(*args: str) -> tuple[int, str, str]:
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = main(list(args))
            except SystemExit as exc:
                code = int(exc.code or 0)
        return code, out.getvalue(), err.getvalue()

    return run
