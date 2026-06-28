# 07 — Storage & data

**Goal:** understand where the data lives, and trace a request from URL all the
way to the stored bytes and back.

---

## An API needs data to serve

An endpoint is useless without data behind it. APIs typically read from:
- a **database** (rows and tables), or
- **files in object storage** (like Amazon **S3**) — what this project uses.

Your real work uses **JSON files on S3**, so that's what we built. Locally, S3 is
faked by **MinIO** (an S3-compatible server in a container) — identical code, no
cloud bill. See it at **http://localhost:9001**.

## What S3 actually is

- A **bucket** is a big namespace (ours is `readings`).
- An **object** is one file, named by a **key** — a string that *looks* like a
  path but is really just a name:
  ```
  processed/scrape/dt=2026-03-15/data.parquet
  ```
- There are **no real folders** — the `/`s are just convention. But you can list
  by **prefix** (everything starting with `processed/scrape/dt=2026-03-15/`),
  which is how you grab a slice. This is the basis of **partitioning** (Lesson 09).

## The storage layer

All S3 access is funneled through one file,
**[`../app/storage.py`](../app/storage.py)**, which wraps the AWS library
(`boto3`) into simple helpers:

```python
put_bytes(key, data)   # write a file
get_bytes(key)         # read a file (or None if missing)
list_keys(prefix)      # list files under a prefix
```

The rest of the app never imports `boto3` — it just calls these. (Remember the
layering lesson: swap storage later = change only this file.)

## Trace one request end-to-end

`GET /scrape/2026-03-15` →

1. **Router** (`scrape.py`) — validates the date, calls `daily.export_json("2026-03-15", ...)`.
2. **Data layer** (`daily.py`) — turns the date into a storage key:
   ```python
   processed/scrape/dt=2026-03-15/data.parquet
   ```
   then reads that file (via the storage layer), queries it, and produces JSON.
3. **Storage** (`storage.py`) — fetches the bytes from S3/MinIO.
4. The JSON streams back to the client.

The key insight from earlier: **the date in the URL becomes the file path.** The
API doesn't search — it goes straight to the file named after the day.

## Storage layout in this project

The API reads a single processed layer, partitioned by day:
```
processed/scrape/dt=2026-03-15/data.parquet ← cleaned, fast format; the API reads this
```
- **processed** is the columnar dataset the API serves.

The API only ever reads `processed/`. Producing it is a **separate upstream
concern** (a scraper + ETL) — out of scope for this read-only API. For local
testing the data is generated outside this repo and uploaded to the bucket.

## Try it
1. Open **http://localhost:9001** (`minioadmin`/`minioadmin`).
2. Browse the `readings` bucket → `processed/scrape/` → pick a `dt=...` folder.
   That single `data.parquet` is what `GET /scrape/<that date>` reads.
3. Compare with `raw/scrape/...` — same day, the original JSON.

## Key takeaways
- APIs read from a **database** or **files**; this one reads **files on S3**
  (MinIO locally).
- All storage access lives in **one layer** (`storage.py`).
- A request maps the **URL → a storage key → bytes → JSON**.
- **raw vs processed**: keep the source untouched; serve the cleaned copy.

➡️ Next: **[08 — Errors & status codes](08-errors-and-status-codes.md)** — what
happens when things go wrong (on purpose).
