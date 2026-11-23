# Contract reference

This is the shape of every artifact schema-forge emits.

## Schema document

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://github.com/kele-tao/schema-forge/contracts/orders.schema.json",
  "title": "orders",
  "type": "object",
  "additionalProperties": false,
  "required": ["order_id", "customer_name", "country", "status", "amount", "...14 required columns"],
  "properties": {
    "amount": {
      "type": "string",
      "description": "currency column inferred with confidence 0.93; 200 distinct values",
      "x-schema-forge": {
        "type": "currency",
        "confidence": 0.93,
        "confidence_parts": {
          "fill_rate": 1.0,
          "type_support": 1.0,
          "specificity": 0.93,
          "sample_depth": 1.0
        },
        "nullable": false,
        "null_ratio": 0.0,
        "seen_rows": 200,
        "distinct": 200,
        "sample_size": 200,
        "stats": { "min_length": 6, "max_length": 9, "distinct": 200, "filled": 200,
                   "min": 14.08, "max": 4763.37, "mean": 2391.3623 },
        "candidates": [{ "kind": "currency", "score": 1.0, "matched": 200 }],
        "evidence": [{ "location": "row 2", "value": "$3,417.77", "matched": ["currency"] }],
        "notes": []
      }
    }
  }
}
```

`x-schema-forge` is the only non-standard keyword. It is ignored by every
conforming validator, and it is what `explain --schema` reads in CI.

## Lock file

```json
{
  "lockfile_version": 1,
  "generator": "schema-forge/1.0.0",
  "contract": "orders",
  "source": "orders.csv",
  "format": "csv",
  "rows": 200,
  "column_count": 16,
  "contract_sha256": "27fe41ded6085a60beb94a6ac16d9563a7aafbf10819685f9643ee3a7d01f3f2",
  "enforcement": {
    "additionalProperties": false,
    "properties": { "order_id": { "type": "string", "pattern": "^[A-Z]{3}\\-\\d{5}$" } },
    "required": ["order_id", "..."]
  }
}
```

The hash is over `enforcement` only, with sorted keys and no whitespace. That
means re-inferring the same shape from a larger batch keeps the hash stable,
while renaming a column or changing a type changes it.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | success |
| 1 | findings: violations, a breaking diff, or lock drift |
| 2 | usage error: bad flags, unreadable input, malformed or unsupported schema |