# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-11-23

### Added

- `schema-forge infer` streams CSV, TSV, JSON Lines and JSON arrays and infers a
  per-column contract: type, confidence, null ratio, numeric and length stats,
  enum detection, regex pattern induction, PII detection and masking advice.
- Emits JSON Schema draft 2020-12, a human-readable Markdown contract and a
  `schema.lock.json` with stable SHA-256 fingerprints for drift detection.
- `schema-forge validate` with row-level locators, `--max-errors`, `--sample`,
  strict/lenient handling of unknown columns, lock verification and JSON output.
- `schema-forge diff` classifies every change as breaking or compatible and prints
  migration guidance; exits 1 when the contract breaks.
- `schema-forge explain` shows the confidence decomposition and the evidence rows
  behind one column's inferred type.
- Constant-memory streaming inference; deterministic byte-identical output.
