# 03 — Your first FastAPI endpoint

**Goal:** see the smallest possible API, understand each piece, and connect it to
the real code in this project.

---

## What is FastAPI?

**FastAPI** is a Python library for building web APIs. You write normal Python
functions; FastAPI turns them into HTTP endpoints, validates inputs, and even
generates documentation. It runs on a server program called **uvicorn**.

> **endpoint** = one URL + method your API answers, backed by one function.
> Also called a **route**.

## The smallest API

```python
# hello.py
from fastapi import FastAPI

app = FastAPI()                 # 1. create the application

@app.get("/hello")              # 2. "when someone does GET /hello..."
def say_hello():                # 3. ...run this function...
    return {"message": "hi!"}   # 4. ...and send back this (as JSON)
```

Run it:
```bash
uvicorn hello:app --reload
#        ^file ^the app object   ^restart on code change
```

Now `GET http://localhost:8000/hello` returns `{"message": "hi!"}`.

Four things to notice:
1. `app = FastAPI()` — the application object everything attaches to.
2. `@app.get("/hello")` — a **decorator** that says "this function handles
   `GET /hello`." (`@app.post(...)` would handle POST, etc.)
3. The function name (`say_hello`) is just for you; the URL is what matters.
4. **You return a Python dict; FastAPI converts it to JSON automatically.**

## The same thing in this project

Open **[`../app/routers/health.py`](../app/routers/health.py)**. Strip the extras
and it's the same shape:

```python
@router.get("/health")
def health() -> dict:
    storage.ping()                       # check the storage is reachable
    return {"status": "ok", ...}         # return a dict → JSON
```

(`router` instead of `app` is just a way to group endpoints — Lesson 06. Same
idea: "GET /health runs this function and returns JSON.")

## The free superpower: auto docs

Because FastAPI knows your routes, it generates interactive documentation with
**zero extra work**. With the project running, open:
- **http://localhost:8000/docs** — Swagger UI (clickable)
- **http://localhost:8000/redoc** — a cleaner reference view
- **http://localhost:8000/openapi.json** — the machine-readable spec behind both

This is a big reason people love FastAPI.

## Try it
1. With the app running, open **http://localhost:8000/docs**.
2. Find **GET /health**, click **Try it out** → **Execute**.
3. Read the response: status `200` and `{"status":"ok",...}`.
4. Now in a terminal: `curl http://localhost:8000/health` — same result, no UI.

## Exercise
Add a tiny new endpoint and see it appear in `/docs`.

1. Open **[`../app/main.py`](../app/main.py)** and find the `root()` function near
   the bottom (it handles `GET /`).
2. Just below it, add:
   ```python
   @app.get("/ping", tags=["root"])
   def ping() -> dict:
       return {"pong": True}
   ```
3. Save. The dev server auto-reloads. Visit `http://localhost:8000/ping` and
   refresh `/docs` — your endpoint is there.
4. (Then delete it — it was just practice.)

## Key takeaways
- An endpoint = a decorated function. `@app.get("/path")` + a function.
- **Return a dict → FastAPI sends JSON.**
- FastAPI auto-generates `/docs` from your code.
- `health.py` in this project is exactly this pattern.

➡️ Next: **[04 — Path & query parameters](04-path-and-query-params.md)** — how the
URL feeds inputs into your function.
