# Security Policy

## Supported versions

The latest minor release on the `main` branch receives security fixes.

## Reporting a vulnerability

Open a private security advisory on GitHub, or email the maintainer at the address
listed on the GitHub profile. Please do not open a public issue for a vulnerability.

## Scope and threat model

`schema-forge` is a local command line tool. It reads files you point it at and
writes only the files you ask for with `--out`, `--markdown` and `--lock`. It makes
no network calls, spawns no subprocesses and executes no code from the input data.

Two things are worth knowing:

- Regex patterns are induced from your data and are printed and written into the
  schema. They are validated at build time by matching every observed value, and
  are capped in length, so a pathological input cannot turn into a regex bomb.
- The schema files are data. If you load a schema produced by someone else,
  `schema-forge` only reads the keywords documented in the README; it does not
  resolve remote `$ref`s and never fetches a URL.
