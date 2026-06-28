# 06 — Consuming the API

For the full reference (every field, every error), see
[`../docs/client-api.md`](../docs/client-api.md). This page is the quickstart.

## Basics

- **Base URL:** `http://localhost:8000` (local) or your deployed HTTPS URL.
- **Read-only dataset:** `/scrape/*` is `GET` only; `POST/PUT/DELETE` → `405`.
- **Auth:** if the server has `API_KEY` set, send `X-API-Key: <key>` on data routes
  (`/health` is open). No key configured → no header needed.
- **Format:** JSON in (query params), JSON out.

## Endpoints at a glance

| Method & path | Purpose |
|---|---|
| `GET /health` | Liveness + S3 reachability |
| `GET /scrape/{day}/meta` | Row count + column names for a day (cheap) |
| `GET /scrape/{day}?page=&page_size=` | A page of the day's rows (JSON array) |
| `GET /readings?…`, `POST /readings`, … | The readings CRUD demo |
| `GET/POST /scrape-config/…` | Control-plane uploads (API-key protected) |

## Paging rules (important)

- `page_size` is **1–5000** (default **1000**). Responses are size-capped, so you page through
  a day rather than pulling it whole.
- An **empty array `[]`** means you've paged past the end of that day — stop.
- A `404` means that day hasn't been produced yet.

```bash
KEY="-H X-API-Key:yourkey"        # omit if auth is off
DAY=2026-06-26
curl $KEY "http://localhost:8000/scrape/$DAY/meta"
curl $KEY "http://localhost:8000/scrape/$DAY?page=1&page_size=5000"
```

## Fetch a whole day (loop the pages)

A ~20k-row day is ~4 pages at `page_size=5000`:

```python
import requests
API, KEY = "http://localhost:8000", {"X-API-Key": "yourkey"}  # KEY={} if auth off

def fetch_day(day, page_size=5000):
    page = 1
    while True:
        rows = requests.get(f"{API}/scrape/{day}",
                            params={"page": page, "page_size": page_size},
                            headers=KEY).json()
        if not rows:           # [] => past the last page
            break
        yield from rows
        page += 1
```

## Fetch a date range

There's **one request per day** — loop the dates (parallelize if you like). Each request reads
only that day, so it stays fast no matter how much history exists:

```python
from datetime import date, timedelta

def fetch_range(start: date, end: date):
    d = start
    while d <= end:
        yield from fetch_day(d.isoformat())
        d += timedelta(days=1)
```

## Errors

| Status | Meaning | Do |
|---|---|---|
| `200` | OK | — |
| `401` / `403` | Missing/!valid `X-API-Key` | Send the key |
| `404` | Day not produced yet | Check the date; retry later |
| `405` | Wrote to a read-only route | Use `GET` |
| `422` | Bad params (`page<1`, `page_size>5000`, bad date) | Fix params |
| `429` | Rate limited | Back off (`RATE_LIMIT`) |
| `503` | Storage unreachable | Transient; retry with backoff |
