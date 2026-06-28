# 12 — End to end: from a client request to the response

This follows **one real request** across the **whole deployed system** — every component it
touches, in order. To make it concrete we use the **Lambda deployment** (API Gateway + Lambda +
ECR + S3), because that's what this repo builds. The other deployments differ only at the front —
see [Deployed somewhere else?](#deployed-somewhere-else) at the bottom.

The request we'll trace:

```
GET https://your-api.example.com/scrape/2026-06-26?page=2&page_size=5000
Header: X-API-Key: <key>        (only if API_KEY is configured)
```

## The cast (every component involved)

| # | Component | Role |
|---|---|---|
| Client | browser / script | sends the HTTPS request, gets JSON back |
| **API Gateway** | AWS managed HTTPS endpoint | the public front door; receives the request, invokes Lambda |
| **Lambda function** | AWS serverless runner | runs your app; on cold start it loads the image from ECR |
| **ECR** | image registry | **stores** the container image; Lambda **pulls** it (cold start only) |
| Mangum | `app/lambda_handler.py` | adapter: turns the Lambda event into a call your app understands |
| FastAPI app | `app/main.py` + routers | your code: validation, routing, the handler |
| DuckDB | inside `app/daily.py` | reads the Parquet **directly from S3** |
| **S3** | object storage | holds the data file `processed/scrape/dt=2026-06-26/data.parquet` |
| IAM role | the Lambda execution role | how Lambda's code is allowed to read/write S3 (no passwords in code) |

## The whole journey

```
 [ CLIENT ]
     │ ① GET https://your-api…/scrape/2026-06-26?page=2&page_size=5000  (HTTPS)
     ▼
 [ API GATEWAY ]  ── public HTTPS endpoint, terminates TLS
     │ ② invokes the Lambda function with the request as an "event"
     ▼
 ┌─ [ LAMBDA FUNCTION ] ─────────────────────────────────────────────────────┐
 │                                                                            │
 │   (COLD START only, first time:                                            │
 │      Lambda pulls the container image ◀───────── [ ECR ]  (image storage)  │
 │      then runs init: load app + extensions)                                │
 │                                                                            │
 │   ③ Mangum (app/lambda_handler.py)  →  hands the request to the app        │
 │   ④ FastAPI middleware (app/main.py): CORS, rate limit                     │
 │   ⑤ routing → get_day()             (app/routers/scrape.py)                │
 │   ⑥ checks: API key, valid date, page/page_size bounds                     │
 │   ⑦ handler → daily.export_json()   (app/daily.py)                         │
 │   ⑧ DuckDB (httpfs) reads the file from S3 ──────────┐                     │
 │      using the LAMBDA IAM ROLE for credentials       │                     │
 └──────────────────────────────────────────────────────┼─────────────────────┘
                                                         ▼
                                              [ S3 BUCKET ]
                                              processed/scrape/dt=2026-06-26/data.parquet
                                                         │ ⑨ returns ONLY the bytes
                                                         │    for rows 5000–9999
                                                         ▼
 …back up: DuckDB makes JSON → Lambda returns it → API Gateway → CLIENT (200 OK)
```

---

## Step by step

### ① Client → API Gateway
The client makes an HTTPS request to the public URL. DNS resolves it to **API Gateway**, AWS's
managed HTTPS endpoint. API Gateway terminates TLS (decrypts HTTPS) and packages the request as an
**event**.

### ② API Gateway → Lambda
API Gateway **invokes the Lambda function**, passing that event. This is the boundary between "AWS
infrastructure" and "your code" — from here on, what runs is *your* application.

### Cold start: where ECR comes in
The **first** time a Lambda instance handles a request (a "cold start"), Lambda has no code in
memory yet, so it:
1. **Pulls your container image from ECR** (the registry where `docker push` put it), then
2. runs the **init**: imports your app via `app/lambda_handler.py`, and DuckDB loads its pre-baked
   `httpfs`/`aws` extensions (no network, thanks to `Dockerfile.lambda`).

After that, the instance stays **warm** for a while: subsequent requests **skip ECR and init
entirely** and jump straight to step ③. So **ECR is touched at cold start, never during a normal
request** — that's why it isn't in the per-request loop.

### ③ Mangum → your app
**Mangum** (`app/lambda_handler.py`) converts the Lambda event into the standard call a FastAPI app
expects ("ASGI"). On a container deployment this job is done by **uvicorn** instead — but it hands
the app the *identical* request. From here, **everything is your `app/` code, and it runs the same
no matter where it's deployed.**

### ④ Middleware (`app/main.py`)
The request passes two middlewares first:
1. **CORS** — cross-origin rules; only `GET` is allowed.
2. **Rate limiting** — `RATE_LIMIT` (default `120/minute`) per client IP. Over it → **429**, and
   the route never runs.

### ⑤ Routing
FastAPI matches `GET /scrape/{day}` to `get_day` in `app/routers/scrape.py`. `2026-06-26` is the
`day` path param; `page=2`, `page_size=5000` come from the query string.

### ⑥ Checks (dependencies), before the handler runs
- **API key** (`app/security.py`) — if `API_KEY` is set, `X-API-Key` must match, else **401**.
- **valid_day** (`app/routers/scrape.py`) — regex + real-date check; bad/impossible date → **422**.
  (Also blocks injection — `day` goes into the S3 key and DuckDB SQL.)
- **Query bounds** — `page ≥ 1`, `page_size` 1–5000, else **422**.

### ⑦ Handler (`get_day`)
Turns the page into SQL pagination and calls the data layer:
```python
offset = (page - 1) * page_size          # (2-1)*5000 = 5000
out_path = daily.export_json(day, limit=page_size, offset=offset)
if out_path is None:
    raise HTTPException(404, ...)         # that day's file doesn't exist in S3
```

### ⑧ Reading the file from S3 (`app/daily.py`)
This is where it touches the actual data:
1. **Does the file exist?** `storage.exists("processed/scrape/dt=2026-06-26/data.parquet")` — a
   cheap S3 **HEAD**. Missing → **404**.
2. **DuckDB queries the file *in place* in S3.** It runs
   `COPY (SELECT * FROM read_parquet('s3://<bucket>/processed/scrape/dt=2026-06-26/data.parquet') LIMIT 5000 OFFSET 5000) TO <tmp.json> (FORMAT JSON)`.
   Via the `httpfs` extension, DuckDB makes **HTTP range requests** to S3: it reads the Parquet
   *footer* (the index), then downloads **only the bytes for rows 5000–9999** — not the whole file
   — and serializes them to JSON in C++.
3. **Credentials:** DuckDB (and boto3) authenticate to S3 using the **Lambda execution role** —
   no keys in the code. (Locally, against MinIO, it uses the dev keys instead.)

### ⑨ Response back to the client
The handler streams that JSON to Mangum, which returns it to **API Gateway**, which sends it to the
**client**:
```
200 OK
[ {"id":5000,...}, …, {"id":9999,...} ]      ← up to 5000 rows
```
(On Lambda the response is buffered by API Gateway — which is exactly *why* `page_size` is capped at
5000, so a page always fits under the gateway's size limit.) An empty array `[]` means you've paged
past the end of the day.

---

## What can go wrong, and where

| Status | Where | Meaning |
|---|---|---|
| `429` | rate-limit middleware (④) | too many requests from this IP |
| `401` | API-key check (⑥) | missing/invalid `X-API-Key` (only when `API_KEY` set) |
| `422` | validation (⑥) | bad date, `page_size > 5000`, malformed query |
| `404` | data layer (⑧) | that day's `.parquet` isn't in S3 yet |
| `405` | routing (⑤) | wrote to a read-only route (`POST /scrape/…`) |
| `503` | `/health` only | the app can't reach S3 (bad role/bucket) |
| `200` | handler (⑦–⑨) | success |

---

## The write path, briefly: `POST /scrape-config/blacklist`

Same journey through ①–⑥, then the handler does a **read-modify-write of a small JSON file in S3**
(`app/scrape_config.py`): read `config/scrape/blacklist.json` → add the new entries (deduplicated)
→ write it back. Returns `{"added": N, "total": M, …}`. So **reads go DuckDB→S3; writes edit a tiny
JSON object in S3.**

---

## Deployed somewhere else?

Only the **front door + host** change. **ECR, the app, and the S3 read stay the same.**

| Deployment | ① Front door | ② Host + adapter | Pulls image from ECR? |
|---|---|---|---|
| **Lambda** (traced above) | API Gateway | Lambda function + **Mangum** | yes (cold start) |
| App Runner | App Runner URL | container + **uvicorn** | yes |
| ECS Fargate | Load Balancer (ALB) | container + **uvicorn** | yes |
| EC2 | your nginx/Caddy | container + **uvicorn** | yes (or build on the box) |

In every case: the image lives in **ECR**, a host **pulls and runs it**, and steps ③–⑨ (your app
reading the Parquet from **S3**) are **identical**. Swap the front door and host; the rest doesn't
move.

---

## See also
- [`09-making-it-fast.md`](09-making-it-fast.md) — the DuckDB-on-S3 read, in depth.
- [`../deployment/08-images-and-ecr.md`](../deployment/08-images-and-ecr.md) — image vs ECR vs host
  (where the code is stored vs where it runs).
- [`../deployment/03-data-contract.md`](../deployment/03-data-contract.md) — what the S3 files are
  and how they're laid out.
