# Exercises

Hands-on challenges, easiest first. Do them with the app running
(`docker compose up` from the project root). Hints and solutions are at the bottom
— try first, peek later.

> Tip: keep **http://localhost:8000/docs** open the whole time.

---

## Part A — Just explore (no coding)

**A1.** Use `/docs` to fetch the metadata for `2026-04-01`. How many rows does it
have? What are its columns?

**A2.** With `curl`, fetch page 2 of `2026-03-15` with a page size of 4. How many
rows come back? Now fetch page 999 — what do you get, and why?

**A3.** Trigger each of these on purpose and note the status code:
a 404, a 422, a 405. (Hint: a missing day; a bad date; a POST.)

**A4.** In the MinIO console (http://localhost:9001), find the actual file that
`GET /scrape/2026-04-01` reads. What's its full key (path)?

## Part B — Read the code

**B1.** Open `app/routers/scrape.py`. Which function handles `GET /scrape/{day}`?
Which line turns `page`/`page_size` into the data query?

**B2.** Follow one request through the layers: name the three functions involved,
in order, from router → data → storage. (Hint: Lesson 07.)

**B3.** In `app/schemas.py`, find `ScrapeRecord`. How many fields does it have?
Which two are timestamps?

## Part C — Make a change (small coding)

**C1. Add a trivial endpoint.** In `app/main.py`, below `root()`, add a
`GET /version` that returns `{"version": "0.1.0"}`. Confirm it appears in `/docs`
and returns correctly. Then remove it.

**C2. Add a query parameter.** Give `GET /health` an optional query param
`echo: str | None = None`. If provided, include `"echo": <value>` in the response.
Test: `GET /health?echo=hi`.

**C3. Tighten a rule.** In `scrape.py`, change `page_size`'s maximum from
`5000` to `1000`. Then request `?page_size=5000` and confirm you now get a
`422`. (Change it back after.)

## Part D — Stretch (real feature)

**D1. Add a `fields` filter.** Make `GET /scrape/{day}` accept an optional
`fields` query param (comma-separated column names) and return only those columns.
The plumbing already exists — `daily.export_json` accepts a `columns` argument.
You'll: (a) add the `fields` query param, (b) split it on commas, (c) pass it as
`columns=`. Test with `?fields=sku,price`.
> Security note: `export_json` already validates column names — see why that
> matters in Lesson 08.

**D2. Write a test.** In `tests/`, add a test that asserts `GET /scrape/{day}` with
an invalid `page_size` (e.g. `999999`) returns `422`. Run `pytest`.

---

## Hints & solutions

<details>
<summary>A2</summary>

```bash
curl 'http://localhost:8000/scrape/2026-03-15?page=2&page_size=4'   # 4 rows
curl 'http://localhost:8000/scrape/2026-03-15?page=999&page_size=4' # [] — past the end
```
An empty array means there's no data on that page; the day only has ~20,000 rows.
</details>

<details>
<summary>B2</summary>

`scrape.py: get_day` → `daily.export_json` → DuckDB range-reads the Parquet from
S3 (`storage.exists` gates the 404). Router handles HTTP, daily does the data
logic, storage talks to S3.
</details>

<details>
<summary>C2 — solution</summary>

In `app/routers/health.py`:
```python
@router.get("/health", ...)
def health(echo: str | None = None) -> dict:
    storage.ping()
    result = {"status": "ok", "s3": "reachable", "bucket": storage.BUCKET}
    if echo is not None:
        result["echo"] = echo
    return result
```
(You may need to relax `response_model=HealthOut` or add `echo` to that model,
since the response now has an extra field — a nice lesson in how `response_model`
constrains output!)
</details>

<details>
<summary>D1 — solution sketch</summary>

In `app/routers/scrape.py`, inside `get_day`:
```python
def get_day(day=Depends(valid_day), page=..., page_size=...,
            fields: str | None = Query(None, description="Comma-separated columns")):
    columns = [c.strip() for c in fields.split(",")] if fields else None
    out_path = daily.export_json(day, columns=columns, limit=page_size, offset=offset)
    ...
```
Then: `curl 'http://localhost:8000/scrape/2026-03-15?fields=sku,price&page_size=3'`.
</details>

<details>
<summary>D2 — solution</summary>

In `tests/test_scrape_api.py`:
```python
def test_page_size_too_large_rejected(client):
    assert client.get("/scrape/2026-03-15?page_size=999999").status_code == 422
```
Run: `python -m pytest tests -q`.
</details>

---

Done with these? You understand APIs better than most people who use them daily.
Go build a small one of your own from a blank file — that's the real graduation.
