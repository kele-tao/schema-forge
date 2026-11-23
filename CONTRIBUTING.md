# Contributing

Thanks for taking the time to improve `schema-forge`.

## Development setup

```bash
git clone https://github.com/kele-tao/schema-forge
cd schema-forge
python -m pip install -e ".[dev]"
pytest -q
ruff check .
```

Python 3.10 or newer. No runtime dependencies; please keep it that way unless a
dependency removes a large amount of code that would otherwise be risky.

## What a good pull request looks like

- One behaviour change per PR, with a test that fails before and passes after.
- Public functions are typed; line length is 100 (`ruff` enforces it).
- New inference rules need a fixture row in `examples/` or a synthetic case in
  `tests/`, plus a note in `docs/ARCHITECTURE.md` if the rule is non-obvious.
- Output that a user can see is deterministic. If it is not, say why in the PR.
- Numbers in the README must come from `python benchmarks/run.py`. Do not paste a
  benchmark you ran once by hand.

## Adding a type or a format

1. Add the detector in `src/schema_forge/detectors.py` (a pure function).
2. Extend the decision order in `src/schema_forge/infer.py` and the JSON Schema
   mapping in `src/schema_forge/types.py`.
3. Teach `validate` the new type and `diff` how it widens.
4. Add tests: a positive case, a near-miss negative case, and a CLI smoke test.

## Reporting bugs

Use the issue template and include the smallest CSV that reproduces the problem,
plus the output of `schema-forge --version`.
