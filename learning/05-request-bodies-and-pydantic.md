# 05 — Request bodies & Pydantic

**Goal:** understand how structured data comes *into* an API (request body) and
how you describe the shape of data with **Pydantic** — the heart of FastAPI.

> Our scrape API is read-only (GET, no body). For this lesson we use the
> `readings` endpoints in the repo, which *do* accept bodies — same ideas.

---

## What's a request body?

For `GET`, inputs ride in the URL. But to **send data** (create a record), you put
it in the **body** — usually JSON:

```
POST /readings
content-type: application/json

{ "sensor_id": "sensor-001", "metric": "temperature", "value": 21.5,
  "unit": "C", "recorded_at": "2026-06-26T10:00:00Z" }
```

The body is the payload. How does the server know what shape to expect, and that
the client didn't send garbage? **Pydantic.**

## Pydantic = data shapes with validation

A **Pydantic model** is a Python class that describes the fields and types of some
data. FastAPI uses it to **validate** incoming JSON automatically.

Open **[`../app/schemas.py`](../app/schemas.py)**:

```python
class ReadingCreate(BaseModel):
    sensor_id: str
    metric: str
    value: float
    unit: str
    recorded_at: datetime
```

Now an endpoint can just ask for it:

```python
@router.post("/readings")
def create_reading(reading: ReadingCreate):   # body parsed into this model
    ...
```

What you get for free:
- The JSON body is parsed into a `ReadingCreate` object.
- **Validation:** missing `value`? `value` is `"hello"` not a number? → automatic
  **422** with a precise error. Your code only runs on *valid* data.
- Autocomplete + types in your editor (`reading.value` is a float).

This "validate at the door" idea is also a core **data-engineering** habit: reject
bad records before they enter your system.

## Shaping the output too: `response_model`

You can also declare what goes *out*, so responses are consistent and documented:

```python
class DayMeta(BaseModel):
    day: str
    rows: int
    columns: list[str]

@router.get("/scrape/{day}/meta", response_model=DayMeta)
def day_meta(...):
    ...
```

`response_model=DayMeta` tells FastAPI (and `/docs`) the exact response shape. See
the real `ScrapeRecord` and `DayMeta` models near the bottom of `schemas.py` —
they're why `/docs` shows full field lists with examples.

## Input model vs output model — keep them separate
Notice we have `ReadingCreate` (what comes in) and `ReadingOut` (what goes out).
Keeping them separate is good practice: you don't want internal fields leaking
out, and the in/out shapes often differ (e.g. the output adds an `id`).

## Try it
1. Open **http://localhost:8000/docs**, find **POST /readings**.
2. **Try it out** — it pre-fills an example body (from the model!). Execute it.
3. Now delete a required field (e.g. remove `value`) and Execute again → **422**,
   and the message tells you exactly what's wrong.

## Key takeaways
- **Body** = structured data sent in (mostly with POST/PUT), usually JSON.
- **Pydantic models** describe data shape; FastAPI uses them to **validate** input
  automatically (bad data → 422).
- `response_model` documents and shapes the output.
- Separate **input** and **output** models.

➡️ Next: **[06 — Structuring an app](06-structuring-the-app.md)** — how a real
project is organized beyond one file.
