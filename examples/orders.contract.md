# orders data contract

Inferred by `schema-forge/1.0.0` from `orders.csv` (csv, 200 rows, 16 columns). Regenerate with `schema-forge infer`; do not edit by hand.

Contract hash: `sha256:27fe41ded6085a60beb94a6ac16d9563a7aafbf10819685f9643ee3a7d01f3f2`

| # | Column | Type | Conf | Nulls | Distinct | Constraints |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `order_id` | text | 0.60 | 0.0% | 200 | pattern ^[A-Z]{3}\-\d{5}$ |
| 2 | `customer_name` | text | 0.60 | 0.0% | 156 | pattern ^[A-Z]{1}[a-z]{2,7}\s[A-Z]{1}[a-z]{3,9}$ |
| 3 | `email` | email | 0.98 | 1.0% | 197 | PII email |
| 4 | `country` | enum | 0.90 | 0.0% | 7 | one of 'BR', 'DE', 'FR', 'IN', 'US', 'JP', 'GB' |
| 5 | `status` | enum | 0.90 | 0.0% | 6 | one of 'cancelled', 'pending', 'shipped', 'delivered', 'refunded', 'shiped' |
| 6 | `amount` | currency | 0.93 | 0.0% | 200 | - |
| 7 | `tax` | float | 0.95 | 0.0% | 196 | - |
| 8 | `quantity` | int | 0.97 | 0.0% | 12 | - |
| 9 | `created_at` | date | 0.96 | 0.0% | 180 | formats %Y-%m-%d, %b %d, %Y, %d/%m/%Y, %m/%d/%Y, %B %d, %Y |
| 10 | `updated_at` | datetime | 0.96 | 0.0% | 200 | - |
| 11 | `card_number` | text | 0.60 | 0.0% | 200 | pattern ^\d{4}\s\d{4}\s\d{4}\s\d{4}$; PII card |
| 12 | `phone` | text | 0.60 | 0.0% | 200 | pattern ^\+\d{1}\s\d{3}\s\d{3}\s\d{4}$; PII phone |
| 13 | `is_gift` | bool | 0.98 | 0.0% | 2 | - |
| 14 | `sku` | text | 0.60 | 0.0% | 200 | pattern ^[A-Z]{3}\-[A-Z]{2}\-\d{4}$ |
| 15 | `website` | url | 0.95 | 0.0% | 198 | - |
| 16 | `notes` | enum | 0.66 | 26.5% | 8 | one of 'gift wrap requested', 'buzzer is broken', 'post to neighbour', 'second attempt', 'call before delivery', 'leave at door', 'fragile', 'deliver after 6pm' |

## Required columns

Required means present in the header and never empty across all 200 sampled rows.

`order_id`, `customer_name`, `country`, `status`, `amount`, `tax`, `quantity`, `created_at`, `updated_at`, `card_number`, `phone`, `is_gift`, `sku`, `website`

## Optional columns

`email`, `notes`

## Notes

- `email`: PII email detected in 198/198 values (100%)
- `created_at`: mixed date formats: %Y-%m-%d, %b %d, %Y, %d/%m/%Y, %m/%d/%Y, %B %d, %Y; day/month order is ambiguous, pin one format downstream
- `card_number`: PII card detected in 200/200 values (100%)
- `phone`: PII phone detected in 200/200 values (100%)

## Validate

```bash
schema-forge validate orders.csv --schema orders.schema.json
```
