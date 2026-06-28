# 04 — Path & query parameters

**Goal:** get inputs from the URL into your function — the two kinds, and when to
use each.

---

## Two ways to pass inputs in a URL

```
/scrape/2026-03-15 ? page=1 & page_size=100
        └────┬────┘   └──────────┬──────────┘
        path param          query params
```

- **Path parameter** — part of the address; identifies *which thing*.
  → "which day?" → `2026-03-15`
- **Query parameter** — options after `?`; tune *how* you want it.
  → "which page, how many rows?" → `page=1`, `page_size=100`

Rule of thumb: **path = which resource, query = options/filters.**

## In FastAPI

```python
@router.get("/scrape/{day}")          # {day} in the path = a path param
def get_day(
    day: str,                         # matched from the {day} in the path
    page: int = 1,                    # query param, default 1
    page_size: int = 1000,            # query param, default 1000
):
    ...
```

Two powerful things happen automatically:
1. **Matching** — `day` comes from the `{day}` slot; `page`/`page_size` come from
   the `?...` part (FastAPI matches by name).
2. **Type conversion + validation** — `page: int` means FastAPI parses it to an
   integer. If a client sends `page=abc`, they get a **422** automatically — your
   function never even runs with bad data.

## The real thing in this project

Open **[`../app/routers/scrape.py`](../app/routers/scrape.py)** and find
`get_day`. It's the same, with extra polish:

```python
def get_day(
    day: str = Depends(valid_day),    # path param, validated (Lesson 06 & 08)
    page: int = Query(1, ge=1, description="1-based page number"),
    page_size: int = Query(1000, ge=1, le=5000, description="Rows per page"),
):
```

- `Query(...)` lets you add rules and docs: `ge=1` means "must be ≥ 1",
  `le=5000` means "≤ 5000". Break a rule → automatic `422`.
- The `description=` text shows up in `/docs`. (Self-documenting!)

## Try it
With the app running:
```bash
# change the page size — fewer rows come back
curl 'http://localhost:8000/scrape/2026-03-15?page=1&page_size=3'

# page past the end — get an empty array []
curl 'http://localhost:8000/scrape/2026-03-15?page=999&page_size=5000'

# break a rule (page must be >= 1) — get a 422 with a helpful message
curl -i 'http://localhost:8000/scrape/2026-03-15?page=0'
```

In `/docs`, the `GET /scrape/{day}` form shows boxes for `day`, `page`,
`page_size` — those are exactly these parameters.

## Why pagination exists
A day has ~20,000 rows. Sometimes a client wants them in chunks instead of all at
once. `page` + `page_size` let them walk through: page 1, page 2, … until they
get `[]` (empty = no more). You'll see *why this is fast* in Lesson 09.

## Key takeaways
- **Path param** = which resource (`{day}`). **Query param** = options (`page`).
- Declaring a type (`page: int`) gives you free parsing + validation (→ 422).
- `Query(..., ge=, le=, description=)` adds rules and docs.

➡️ Next: **[05 — Request bodies & Pydantic](05-request-bodies-and-pydantic.md)** —
sending structured data *in*, and shaping what goes *out*.
