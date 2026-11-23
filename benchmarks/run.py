"""Benchmark inference, validation and diff; write docs/benchmark.md + results.json.

Every number in the README's benchmark table comes from this script:

    python benchmarks/run.py

The script generates its own input with a fixed seed, so the numbers are
reproducible on any machine (absolute timings differ per machine; the report
records the platform it ran on).
"""

from __future__ import annotations

import json
import pathlib
import platform
import sys
import time
import tracemalloc

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from schema_forge import infer_file, load_schema, validate_file  # noqa: E402
from schema_forge.diff import diff_specs  # noqa: E402

BENCH_DIR = ROOT / "benchmarks"
DOCS = ROOT / "docs"
WORK = BENCH_DIR / "work"

HEADER = [
    "order_id",
    "customer_email",
    "country",
    "status",
    "amount",
    "quantity",
    "created_at",
    "card_number",
    "notes",
]

STATUSES = ["pending", "shipped", "delivered", "cancelled", "refunded"]
COUNTRIES = ["US", "DE", "FR", "GB", "JP", "BR", "IN"]


def build_row(index: int, state: int) -> tuple[str, int]:
    """Return one deterministic CSV line and the next generator state."""

    def next_state(value: int) -> int:
        return (1103515245 * value + 12345) & 0x7FFFFFFF

    state = next_state(state)
    status = STATUSES[state % len(STATUSES)]
    state = next_state(state)
    country = COUNTRIES[state % len(COUNTRIES)]
    state = next_state(state)
    amount = (state % 900000) / 100.0
    quantity = state % 12 + 1
    card = "4" + ("%015d" % (state % 10**15))
    line = (
        "ORD-%07d,buyer%d@example.com,%s,%s,$%0.2f,%d,2026-%02d-%02dT%02d:%02d:00Z,%s,note %d"
        % (
            100000 + index,
            index,
            country,
            status,
            amount,
            quantity,
            index % 12 + 1,
            index % 28 + 1,
            index % 24,
            index % 60,
            card,
            index % 7,
        )
    )
    return line, state


def make_dataset(rows: int) -> tuple[pathlib.Path, float]:
    """Write a CSV with the requested number of rows; return (path, size in MB)."""
    WORK.mkdir(parents=True, exist_ok=True)
    path = WORK / ("orders_%d.csv" % rows)
    if not path.exists():
        with path.open("w", encoding="utf-8", newline="") as handle:
            handle.write(",".join(HEADER) + "\n")
            state = 42
            for index in range(rows):
                line, state = build_row(index, state)
                handle.write(line + "\n")
    return path, path.stat().st_size / (1024 * 1024)


def timed(function, repeats: int = 3):
    """Run function repeats times; return (best_seconds, all_samples, last_value)."""
    samples: list[float] = []
    value = None
    for _ in range(repeats):
        started = time.perf_counter()
        value = function()
        samples.append(time.perf_counter() - started)
    return min(samples), samples, value


def peak_python_memory(callable_) -> dict[str, float]:
    """Return peak tracemalloc footprint (MB) while running callable_."""
    tracemalloc.start()
    callable_()
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {"peak_tracemalloc_mb": round(peak / (1024 * 1024), 2)}


def main() -> int:
    """Run every benchmark and write the Markdown + JSON reports."""
    DOCS.mkdir(parents=True, exist_ok=True)
    results: dict[str, object] = {
        "machine": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor() or "unknown",
        },
        "benchmarks": [],
    }
    schema_path = DOCS / "bench" / "bench.schema.json"
    schema_path.parent.mkdir(parents=True, exist_ok=True)

    for rows in (1000, 10000, 50000):
        path, size_mb = make_dataset(rows)
        best, samples, result = timed(lambda p=path: infer_file(p, name="orders"))
        schema = result.contract.to_schema()
        schema_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
        results["benchmarks"].append(
            {
                "name": "infer",
                "rows": rows,
                "input_mb": round(size_mb, 2),
                "seconds": round(best, 3),
                "rows_per_second": int(rows / best),
                "samples": [round(sample, 3) for sample in samples],
            }
        )
        spec = load_schema(schema_path)
        best_validate, samples_v, report = timed(
            lambda p=path, s=spec: validate_file(p, s), repeats=3
        )
        results["benchmarks"].append(
            {
                "name": "validate",
                "rows": rows,
                "input_mb": round(size_mb, 2),
                "seconds": round(best_validate, 3),
                "rows_per_second": int(rows / best_validate),
                "cells": report.checked_cells,
                "samples": [round(sample, 3) for sample in samples_v],
            }
        )

    baseline = json.loads(schema_path.read_text(encoding="utf-8"))
    changed = json.loads(json.dumps(baseline))
    changed["properties"]["quantity"]["type"] = "string"
    changed_path = DOCS / "bench" / "bench.v2.schema.json"
    changed_path.write_text(json.dumps(changed, indent=2), encoding="utf-8")
    old_spec = load_schema(schema_path)
    new_spec = load_schema(changed_path)
    best_diff, samples_d, diff_result = timed(lambda: diff_specs(old_spec, new_spec))
    results["benchmarks"].append(
        {
            "name": "diff",
            "columns": len(baseline["properties"]),
            "seconds": round(best_diff, 6),
            "changes": len(diff_result.changes),
            "breaking": len(diff_result.breaking),
            "samples": [round(sample, 6) for sample in samples_d],
        }
    )

    big_path, big_mb = make_dataset(50000)
    memory = peak_python_memory(lambda: infer_file(big_path, name="orders"))
    memory["input_mb"] = round(big_mb, 2)
    memory["rows"] = 50000
    results["memory"] = memory

    (BENCH_DIR / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (DOCS / "benchmark.md").write_text(render_markdown(results), encoding="utf-8")
    print("wrote docs/benchmark.md and benchmarks/results.json")
    for entry in results["benchmarks"]:
        print("  " + json.dumps(entry))
    print("  memory: " + json.dumps(memory))
    return 0


def render_markdown(results: dict) -> str:
    """Render the benchmark report committed as docs/benchmark.md."""
    machine = results["machine"]
    lines: list[str] = []
    lines.append("# Benchmark")
    lines.append("")
    lines.append("Generated by `python benchmarks/run.py`. Do not edit by hand.")
    lines.append("")
    lines.append("- Python %s on %s" % (machine["python"], machine["platform"]))
    lines.append(
        "- Timings are the best of three runs on a warm filesystem cache; the input is "
        "generated by the script itself with a fixed seed."
    )
    lines.append("")
    lines.append("## Inference and validation throughput")
    lines.append("")
    lines.append("| Operation | Rows | Input (MB) | Best (s) | Rows/s |")
    lines.append("| --- | --- | --- | --- | --- |")
    for entry in results["benchmarks"]:
        if entry["name"] in {"infer", "validate"}:
            lines.append(
                "| %s | %s | %.2f | %.3f | %s |"
                % (
                    entry["name"],
                    format(entry["rows"], ","),
                    entry["input_mb"],
                    entry["seconds"],
                    format(entry["rows_per_second"], ","),
                )
            )
    lines.append("")
    diff_entry = next(entry for entry in results["benchmarks"] if entry["name"] == "diff")
    lines.append("## Schema diff")
    lines.append("")
    lines.append(
        "Diffing two %d-column contracts takes %.1f microseconds and classifies %d change(s), "
        "%d of them breaking."
        % (
            diff_entry["columns"],
            diff_entry["seconds"] * 1e6,
            diff_entry["changes"],
            diff_entry["breaking"],
        )
    )
    lines.append("")
    memory = results["memory"]
    lines.append("## Memory")
    lines.append("")
    lines.append(
        "Peak Python allocation while streaming the %.2f MB / 50,000-row file is %.2f MB "
        "(measured with tracemalloc). Memory stays flat because inference keeps bounded "
        "per-column counters and a bounded sample, never the rows themselves."
        % (memory["input_mb"], memory["peak_tracemalloc_mb"])
    )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
