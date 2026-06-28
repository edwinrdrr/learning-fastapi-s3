# 06 — Structuring an app

**Goal:** see how a real API is organized into pieces instead of one giant file —
routers, dependencies, config, and layers.

---

## Why not one big file?

A toy API is one file. A real one has many endpoints, storage, config, auth — put
it all in `main.py` and it becomes unmanageable. So we split by responsibility.
Here's this project's layout:

```
app/
├── main.py          ← creates the app, wires everything together
├── config.py        ← settings (read from environment variables)
├── security.py      ← the API-key check
├── storage.py       ← all S3/file access lives here
├── daily.py         ← the "read a day fast" data logic
├── routers/
│   ├── health.py    ← GET /health
│   ├── scrape.py    ← GET /scrape/... (the product)
│   ├── readings.py  ← the learning-scaffold endpoints
│   └── stats.py
└── jobs/            ← scripts run on a schedule (not part of the API)
```

## Routers — grouping endpoints

A **router** is a mini-collection of related endpoints. Instead of `@app.get`, you
use `@router.get`, then plug the router into the app.

In **[`../app/routers/scrape.py`](../app/routers/scrape.py)**:
```python
router = APIRouter(prefix="/scrape", tags=["scrape"])

@router.get("/{day}")        # actually becomes /scrape/{day} because of prefix
def get_day(...): ...
```

In **[`../app/main.py`](../app/main.py)** they get connected:
```python
app.include_router(health.router)
app.include_router(scrape.router, dependencies=[Depends(require_api_key)])
```

`prefix="/scrape"` means every route in that file starts with `/scrape`. `tags`
group them into sections in `/docs`.

## Dependencies — reusable pre-steps (`Depends`)

A **dependency** is a function FastAPI runs *before* your endpoint, to provide a
value or enforce a rule. It's how you avoid copy-pasting the same checks.

Two real examples in this project:

```python
# 1. Validate the date (security). Runs before get_day / day_meta.
def get_day(day: str = Depends(valid_day), ...): ...

# 2. Require an API key on a whole router.
app.include_router(scrape.router, dependencies=[Depends(require_api_key)])
```

- `valid_day` (in `scrape.py`) checks the date is real, then returns it.
- `require_api_key` (in `security.py`) blocks the request if the key is wrong.

You write the check **once**, attach it with `Depends`, and every endpoint gets
it. This pattern is called **dependency injection** — the framework "injects" what
your function needs.

## Config — settings from the environment

Hard-coding values (bucket names, keys, limits) is bad. Instead they come from
**environment variables**, read in **[`../app/config.py`](../app/config.py)**:

```python
class Settings(BaseSettings):
    s3_bucket: str = "readings"
    api_key: str | None = None
    rate_limit: str = "120/minute"
```

Same code runs locally and in the cloud — only the env values change. (This is the
"12-factor" principle: config lives in the environment, not the code.)

## Layers — keep concerns separate

Notice the **separation**:
- **Routers** (`scrape.py`) handle HTTP: parse inputs, return responses. Thin.
- **Data logic** (`daily.py`) knows how to read/convert data. No HTTP here.
- **Storage** (`storage.py`) is the *only* file that talks to S3.

Why: if you later swap S3 for Google Cloud Storage, you change **one file**
(`storage.py`). The routers don't care. This is the single most valuable habit for
keeping a codebase maintainable.

## Try it
- Open `main.py` and read it top to bottom — it's a map of the whole app: create
  app → add rate limiting → add CORS → include routers. ~80 lines.
- Follow one request in your head: `GET /scrape/2026-03-15` → `scrape.py:get_day`
  → calls `daily.export_json` → which calls `storage.get_bytes`. Three layers.

## Key takeaways
- **Routers** group endpoints; `include_router` wires them into the app.
- **Dependencies (`Depends`)** = reusable pre-checks/values (validation, auth).
- **Config** comes from environment variables, not hard-coded.
- **Layering** (router → data → storage) keeps changes local and code clean.

➡️ Next: **[07 — Storage & data](07-storage-and-data.md)** — where the data
actually lives and how a request reaches it.
