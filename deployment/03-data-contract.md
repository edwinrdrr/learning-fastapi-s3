# 03 — Data contract & S3 layout

This is the "folders and files" the service relies on. Everything lives in **one S3 bucket**
(`S3_BUCKET`, default `readings`). There are no real folders in S3 — the `/` in a key is just a
naming convention, and listing by prefix is how the app queries slices.

## Bucket layout

```
s3://<bucket>/
├── processed/scrape/dt=YYYY-MM-DD/data.parquet   ← THE scrape dataset the API serves (read-only)
│
├── readings/<sensor_id>/<YYYY-MM-DD>/<uuid>.json ← /readings CRUD demo (one object per record)
│
└── config/scrape/                                ← /scrape-config control plane
    ├── blacklist.json
    ├── whitelist.json
    └── input_table/
        ├── _latest.json                          ← pointer to the current input table
        └── history/<timestamp>__<filename>       ← every uploaded input table, kept
```

## 1. `processed/scrape/` — what the API consumes (the important one)

- **Who writes it:** a **separate upstream producer** (scraper + ETL). **Out of scope for this
  repo.** Locally, the standalone `generate_dummy.py` (outside the repo) stands in for it.
- **Who reads it:** this API, on `GET /scrape/{day}` and `/scrape/{day}/meta`. DuckDB reads the
  Parquet **directly from S3** (range reads) — see the `httpfs` note in [01-build.md](01-build.md).
- **Key format:** `processed/scrape/dt=<YYYY-MM-DD>/data.parquet` — exactly one object per day.
  The date in the URL maps 1:1 to this key (`GET /scrape/2026-06-26` → `…/dt=2026-06-26/…`).
- **Partitioning:** `dt=YYYY-MM-DD` is Hive-style; a read resolves to a single object, so the
  API never scans other days. History size never slows a request.
- **Missing day → `404`.** The API never creates data.

### Producer requirements (what a valid `data.parquet` must satisfy)

1. **Apache Parquet**, one file per day at the exact key above.
2. **Columns:** the 20 product fields documented in
   [`../docs/client-api.md`](../docs/client-api.md#field-reference) (`id`, `scraped_at`, `sku`,
   `title`, … `updated_at`). The API serves whatever columns are present, so the producer owns
   the schema.
3. **Timestamps as ISO-8601 strings** (`2026-06-26T03:00:00Z`), not Parquet `TIMESTAMP`, if you
   want the `T`/`Z` preserved end-to-end.
4. **Do not bake a `dt` column into the file.** The `dt=…` lives only in the path. (The API
   reads with `hive_partitioning=false` so it won't *invent* one, but a producer that writes an
   actual `dt` column would leak it.)

> Want sample data locally? See [04-run-locally.md](04-run-locally.md) — it runs the external
> `generate_dummy.py`, which produces conformant Parquet and uploads it to this key.

## 2. `readings/` — the `/readings` CRUD demo (read + write)

- One JSON object per record at `readings/<sensor_id>/<YYYY-MM-DD>/<uuid>.json`.
- The public id a client sees is the part after `readings/` (e.g. `sensor-001/2026-06-26/<uuid>.json`).
- Written by `POST /readings` and `/readings/bulk`; read by `GET /readings…`; removed by `DELETE`.
- This is why the IAM role needs **write** (`PutObject`/`DeleteObject`), not just read.

## 3. `config/scrape/` — the `/scrape-config` control plane (read + write)

- `blacklist.json` / `whitelist.json` — JSON arrays, appended to (deduplicated) by
  `POST /scrape-config/{blacklist|whitelist}`.
- `input_table/_latest.json` — metadata pointing at the current input table.
- `input_table/history/<timestamp>__<filename>` — every uploaded CSV/JSON input table, retained.
- Written by `POST /scrape-config/*` (API-key protected); read by the matching `GET`.

## IAM implication

Because of sections 2 and 3, the service's role needs **read and write** on the bucket
(`s3:GetObject`, `s3:PutObject`, `s3:DeleteObject`, `s3:ListBucket`) — even though the headline
`/scrape` dataset is read-only. The exact policy is in [05-deploy-aws.md](05-deploy-aws.md).
