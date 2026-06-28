# 08 — Errors & status codes

**Goal:** learn to fail *correctly*. Good APIs return the *right* error so clients
know what went wrong and whose fault it is.

---

## Errors are a feature, not an afterthought

When something's off, you don't return data with a `200` — you return an error
status (4xx/5xx) and a helpful message. Clients rely on these to react (retry?
fix their input? give up?).

## The errors this API returns

| Status | When | Example here |
|--------|------|--------------|
| `200` | All good | data returned |
| `404` | The thing doesn't exist | day not scraped yet |
| `422` | Client sent invalid input | `page=0`, bad date format |
| `405` | Wrong method | `POST` to a read-only route |
| `401` | Missing/invalid auth | no `X-API-Key` when one's required |
| `429` | Too many requests | rate limit hit |
| `503` | A dependency is down | storage unreachable |

## Raising an error on purpose: `HTTPException`

When *you* decide something's wrong, you `raise HTTPException`. From
**[`../app/routers/scrape.py`](../app/routers/scrape.py)**:

```python
def day_meta(day: str = Depends(valid_day)):
    info = daily.meta(day)
    if info is None:                       # no data for that day
        raise HTTPException(status_code=404, detail="No data for day ...")
    return info
```

`raise` stops the function and FastAPI sends `404` with your `detail` message as
JSON. Clean and explicit.

## Errors FastAPI raises *for you*

You don't write code for most validation errors — FastAPI handles them:

- **422** — a query/path/body value fails its type or rules (`page=abc`,
  `page_size=999999` when max is 5000, an impossible date). FastAPI checks
  *before* your function runs and returns a detailed 422.
- **405** — someone uses a method you didn't define (POST to a GET-only path).
- **401 / 429** — from the auth dependency and the rate-limiter you added.

This is the payoff of declaring types and using dependencies: a lot of correct
error handling happens automatically.

## Security angle: validation *is* error handling

Remember `valid_day`? It raises `422` for a bad date. That's not just tidiness —
it's **security**. The date is used to build a file path and a database query, so
rejecting weird input at the door prevents injection attacks. **Validating input
and returning 422 is a frontline defense.**

## Try it
```bash
# 404 — real date, but no data for it
curl -i http://localhost:8000/scrape/1999-01-01/meta

# 422 — not a valid date at all (FastAPI rejects it before your code runs)
curl -i http://localhost:8000/scrape/not-a-date/meta

# 422 — looks like a date but isn't real
curl -i http://localhost:8000/scrape/2026-02-30/meta

# 405 — wrong method on a read-only route
curl -i -X DELETE http://localhost:8000/scrape/2026-03-15
```
Read the first line (status) and the JSON `detail` of each.

## Key takeaways
- Return the **right status code**: 4xx = client's fault, 5xx = server's fault.
- `raise HTTPException(status_code=, detail=)` for errors *you* detect (like 404).
- FastAPI auto-returns **422** for invalid inputs and **405** for wrong methods.
- **Input validation = error handling = security.**

➡️ Next: **[09 — Making it fast](09-making-it-fast.md)** — the data-engineering
tricks that make this API quick even with big files.
