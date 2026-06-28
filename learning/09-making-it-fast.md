# 09 — Making it fast (the data-engineering part)

**Goal:** understand the tricks that let this API serve big daily files quickly —
the exact question that started this project.

> This is where "building an API" meets "data engineering." The API is the easy
> part; serving large data *fast* is the interesting part.

---

## The problem

The scrape is ~20,000 rows × 20 columns **per day**, with months of history. A
naive API would, on every request:
1. download a big JSON file,
2. parse all of it,
3. send it all back.

That's slow and wasteful — especially repeated for every caller. Four ideas fix it.

## 1. Partitioning — one file per day

Data is stored as **one file per day**, named by date:
```
processed/scrape/dt=2026-03-15/data.parquet
```
A request for one day reads **only that file** — never the other months. The date
in the URL becomes the file path (you saw this in Lesson 07). This is called
**partition pruning**: the cost of a request doesn't grow as history grows.

## 2. Parquet — a faster file format

Internally the data isn't stored as JSON but as **Parquet**:
- **Columnar** — stores each column together, so reading a few columns skips the
  rest.
- **Compressed + typed** — the same 20k rows are ~9 MB as JSON but ~0.4 MB as
  Parquet.

The client still gets **JSON** — Parquet is purely an internal storage choice.
(JSON at the edges, fast format inside.)

## 3. Read straight from S3 — only what's asked for

The app doesn't download whole files or keep a local cache. DuckDB's `httpfs`
extension queries the Parquet **in place in S3** using HTTP range reads, pulling
only the rows/columns a page needs. See `export_json` in
**[`../app/daily.py`](../app/daily.py)**. Bonus: with no local state, the same
code runs unchanged on a serverless runtime (Lambda).

## 4. Streaming + letting the engine do the work

To turn Parquet back into JSON, the app uses **DuckDB** (a tiny embedded database)
to query the file and **serialize the JSON itself, in fast C++** — instead of
Python looping row by row. Then it **streams** the bytes to the client (constant
memory, fast first byte).

> Surprising lesson learned here: once reads were fast, the *JSON serialization*
> became the bottleneck — Python doing it per-row took 2.5 s for a full day;
> handing it to DuckDB dropped it to ~0.1 s.

## Pagination ties in

`page` / `page_size` (Lesson 04) let a client take a slice of a day instead of the
whole thing — and DuckDB pushes that `LIMIT/OFFSET` into the query, so it only
reads what's asked for.

## The numbers (measured locally)

| Request | Time |
|---------|------|
| `GET /scrape/{day}/meta` | ~14 ms |
| `GET /scrape/{day}?page_size=5000` (one page) | ~40 ms |
| a full day (~20k rows) = ~4 pages | looped/parallel client-side |

## How a client reads many days (e.g. 40 days)
Each request is **one day**. To get a range, the client loops over the dates (and
can fetch them in parallel). Because each day is its own file, history size never
slows a single request down.

## Try it
```bash
# cheap metadata — milliseconds
time curl -s http://localhost:8000/scrape/2026-03-15/meta >/dev/null

# one page (max 5000 rows) — fast
time curl -s 'http://localhost:8000/scrape/2026-03-15?page_size=5000' >/dev/null

# only 3 columns, 5 rows — even less work
curl 'http://localhost:8000/scrape/2026-03-15?page=1&page_size=5'
```

## Want more depth?
Read **[../docs/internal-architecture.md](../docs/internal-architecture.md)** — it
covers the request lifecycle, caching, and performance in detail.

## Key takeaways
- **Partitioning** (one file per day) → a request reads only what it needs.
- **Parquet** internally is small + fast; **JSON** stays the client contract.
- **Caching** avoids re-reading immutable daily files.
- Let the **engine (DuckDB)** query + serialize, and **stream** the result.

➡️ Next: **[10 — Production concerns](10-production-concerns.md)** — what it takes
to safely ship an API to the real world.
