# Roadmap

Ordered by what users of the tool ask for most. Nothing here is claimed in the
README; it is what is missing from v1.0.0.

## Next

1. **Parquet and Arrow input.** The reader abstraction already yields
   `(location, row)` pairs, so a `pyarrow` reader can slot in behind an
   optional extra. This is the single biggest request for warehouse users.
2. **`validate --baseline`.** Fail only on violations that are *new* compared
   with a recorded baseline, so a team can adopt the contract on a data set that
   already has known-bad rows without a flag day.
3. **Per-column overrides.** A small `overrides.json` (`force type`,
   `ignore column`, `regex`) so a human can correct an inferred type without
   forking the tool.
4. **`validate --explain`.** For a failing cell, print the inferred value, the
   expected type, and the nearest conforming rows, which is what a data producer
   needs to fix their side.
5. **`anyOf` / nullable unions.** A column that is sometimes an integer and
   sometimes an empty string is currently `text` with a low confidence. A
   union type would express that properly, once the validator supports it.

## Deliberately cut from v1.0.0

- **Full JSON Schema support** (`$ref`, `anyOf`, `oneOf`, `allOf`, remote
  resolution). The enforced subset is documented and closed; a validator that
  silently ignores keywords is worse than one that refuses them.
- **Parquet / Excel input.** Both need a dependency, and the project's selling
  point is a zero-dependency install.
- **Assigning PII severity levels or doing full column-level redaction.** The
  tool reports PII and gives masking advice; it does not rewrite data.
- **A web UI.** The artifacts (JSON Schema, Markdown, lock) are the interface.
- **Multi-file contracts** (one schema for a directory of shards). The reader
  takes one path; a shell loop covers the common case today.
