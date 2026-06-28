# Daily Scrape API — Client Guide

A read-only HTTP API for retrieving daily scrape datasets. Each scrape day is a
dataset of product records; you fetch a day (optionally a page of it) and get
back JSON.

- **Base URL (dev):** `http://localhost:8000`
- **Format:** JSON request params in the query string; JSON responses.
- **Auth:** none yet (intended to be added before any non-local deployment).
- **Read-only:** only `GET` is supported. `POST`/`PUT`/`DELETE` return `405`.

---

## Endpoints

### `GET /health`
Liveness check. Returns `200` when the API and its storage are reachable.

```json
{ "status": "ok", "s3": "reachable", "bucket": "readings" }
```

---

### `GET /scrape/{day}/meta`
Metadata for one day, without downloading the rows. Use it to learn the row
count (to size your pagination) and the available columns.

| Param | In | Type | Notes |
|-------|----|------|-------|
| `day` | path | string | The scrape date, `YYYY-MM-DD` |

**200 response**
```json
{
  "day": "2026-03-15",
  "rows": 20000,
  "columns": ["id", "scraped_at", "sku", "title", "brand", "category",
              "subcategory", "price", "currency", "original_price",
              "discount_pct", "in_stock", "stock_qty", "rating",
              "review_count", "seller", "url", "shipping_days",
              "warehouse_country", "updated_at"]
}
```

**404** — that day has not been scraped/processed.

---

### `GET /scrape/{day}`
Returns the day's records as a **JSON array**. Supports paging.

| Param | In | Type | Default | Notes |
|-------|----|------|---------|-------|
| `day` | path | string | — | Scrape date, `YYYY-MM-DD` |
| `page` | query | int ≥ 1 | `1` | 1-based page number |
| `page_size` | query | int 1–5000 | `1000` | Rows per page (max 5000) |

Responses are size-capped, so `page_size` maxes out at **5000**. Page through a
day with `page`; an empty array means you've reached the end.

**200 response** — a JSON array of records:
```json
[
  {
    "id": 0,
    "scraped_at": "2026-03-15T03:00:00Z",
    "sku": "SKU-690713",
    "title": "Stark Lego Set Max",
    "brand": "Stark",
    "category": "toys",
    "subcategory": "lego-set",
    "price": 436.41,
    "currency": "EUR",
    "original_price": 436.41,
    "discount_pct": 0,
    "in_stock": true,
    "stock_qty": 60,
    "rating": 1.8,
    "review_count": 4274,
    "seller": "marketplace-a",
    "url": "https://example-shop.com/toys/lego-set/0",
    "shipping_days": 4,
    "warehouse_country": "ES",
    "updated_at": "2026-03-15T01:21:00Z"
  }
]
```

**An empty array `[]` means you've paged past the end of that day** — stop.

**404** — that day has not been scraped/processed.

#### Field reference

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Row index within the day |
| `scraped_at` | string | When the scrape ran (ISO-8601 UTC, `…Z`) |
| `sku` | string | Stock-keeping unit |
| `title` | string | Product title |
| `brand` | string | Brand name |
| `category` | string | Top-level category |
| `subcategory` | string | Sub-category |
| `price` | number | Current price |
| `currency` | string | ISO-4217 currency code |
| `original_price` | number | Pre-discount price |
| `discount_pct` | integer | Discount percentage (0–50) |
| `in_stock` | boolean | Availability |
| `stock_qty` | integer | Units in stock (0 if out of stock) |
| `rating` | number | Average rating, 1.0–5.0 |
| `review_count` | integer | Number of reviews |
| `seller` | string | Seller / storefront |
| `url` | string | Product URL |
| `shipping_days` | integer | Estimated shipping days |
| `warehouse_country` | string | ISO-3166 country code |
| `updated_at` | string | Listing last-updated (ISO-8601 UTC, `…Z`) |

> Timestamps are returned exactly as scraped (ISO-8601, UTC, trailing `Z`).

---

## Common tasks

### Fetch a whole day
```bash
curl 'http://localhost:8000/scrape/2026-03-15?page=1&page_size=5000'
```

### Page through a day
```bash
curl 'http://localhost:8000/scrape/2026-03-15?page=1&page_size=5000'
curl 'http://localhost:8000/scrape/2026-03-15?page=2&page_size=5000'
# ... until you get []
```

### Fetch a date range (e.g. 40 days)
There is **one request per day** — loop over the dates (and parallelise if you
want). Each request reads only that day, so it stays fast regardless of how much
history exists.

```python
import requests
from datetime import date, timedelta

API = "http://localhost:8000"

def fetch_range(start: date, end: date, page_size: int = 5000):
    day = start
    while day <= end:
        d = day.isoformat()
        page = 1
        while True:
            rows = requests.get(
                f"{API}/scrape/{d}",
                params={"page": page, "page_size": page_size},
            ).json()
            if not rows:           # empty => past the last page of this day
                break
            yield from rows
            page += 1
        day += timedelta(days=1)
```

---

## Errors

| Status | Meaning | What to do |
|--------|---------|------------|
| `200` | OK | — |
| `404` | Day not available (not scraped/processed yet) | Check the date; retry later |
| `405` | Method not allowed (API is read-only) | Use `GET` |
| `422` | Invalid query params (e.g. `page` < 1) | Fix the params |
| `503` | Storage not reachable | Transient; retry with backoff |

## Uploads (control-plane: `/scrape-config`)

Separate from the read-only data API above. These **write** endpoints manage the
inputs that drive scraping (behind `X-API-Key` when auth is enabled).

| Method & path | Body | Semantics |
|---|---|---|
| `POST /scrape-config/input-table` | a CSV/JSON **file** (multipart) | **replace** current table |
| `GET /scrape-config/input-table` | — | current table metadata |
| `POST /scrape-config/{blacklist\|whitelist}` | JSON `{"entries": [...]}` | **append** (deduplicated) |
| `GET /scrape-config/{blacklist\|whitelist}` | — | current list |

```bash
# upload an input table
curl -X POST localhost:8000/scrape-config/input-table -F 'file=@targets.csv;type=text/csv'

# append to the blacklist (dedupes automatically)
curl -X POST localhost:8000/scrape-config/blacklist \
  -H 'content-type: application/json' -d '{"entries":["spam.com","SKU-1"]}'
```
Limits: input-table max 50 MB (`413` over); unsupported type / unparseable → `422`.

## Notes & limits
- Days are **immutable** once published, so responses are safe to cache.
- A full day is ~20,000 rows; at `page_size=5000` that's ~4 requests. Page
  through with `page` until you get an empty array.
- No authentication yet — do not expose this externally until auth is added.
