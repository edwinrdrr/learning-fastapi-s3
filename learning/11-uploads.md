# 11 — Uploads: sending data *in*

**Goal:** learn how clients send data *to* an API (the opposite of reading), the
three patterns, and how this project implements two real cases.

> Everything so far was **reading** (GET). "Upload" means the client **sends**
> data, which goes in the request **body** of a **POST** (or PUT).

---

## Three upload patterns

| Pattern | What the client sends | Use when | FastAPI tool |
|---------|----------------------|----------|--------------|
| **1. JSON body** | Structured data as JSON | small records, lists, settings | a Pydantic model |
| **2. File upload** | An actual file (multipart) | CSV/JSON/image files | `UploadFile` / `File` |
| **3. Presigned URL** | Nothing — uploads straight to S3 | **large** files, high volume | `boto3` signed URL |

### Pattern 3 in one picture (the scalable one)
```
client → API:  "I want to upload"          (tiny request)
API → client:  a temporary signed S3 URL
client → S3:   uploads the big file DIRECTLY (API never touches the bytes)
```
For large files this avoids pushing gigabytes through your app. We don't
implement it here, but it's the production choice when files get big.

## The two real cases in this project

This project added a **control-plane** (write side) at `/scrape-config`, separate
from the read-only `/scrape` data API. See
**[`../app/routers/scrape_config.py`](../app/routers/scrape_config.py)** and
**[`../app/scrape_config.py`](../app/scrape_config.py)**.

### Case 1 — Input table (a file → **replace**)
The list of things to scrape is a table (CSV/JSON). The client **uploads a file**
(Pattern 2); a new upload **replaces** the current table (the old one is kept
under `history/` for audit).

```python
@router.post("/input-table")
async def upload_input_table(file: UploadFile = File(...)):
    data = await _read_capped(file, MAX_INPUT_BYTES)   # size limit!
    return scrape_config.set_input_table(file.filename, file.content_type, data)
```
Note: `async def` + `await file.read()`, a **size cap** (reject huge files), and
validation (it must parse as CSV/JSON, else `422`).

### Case 2 — Blacklist / whitelist (JSON → **append**)
Two lists controlling scraping. The client sends a JSON list of entries
(Pattern 1); new entries are **appended** to the existing set, **deduplicated**.

```python
@router.post("/{name}")           # name = blacklist | whitelist
def append_entries(payload: AppendEntries, name: str = Depends(list_name)):
    return scrape_config.append_list(name, payload.entries)
```

**Append, not replace** means read-modify-write:
```python
existing = get_list(name)
added = [e for e in new if e not in set(existing)]   # only the genuinely new
store(existing + added)
```

## Append has a subtle trap: concurrency
Two clients appending at the same time can both read the old list and one
overwrites the other (a lost update). We guard it with a **lock**, but a
process-local lock only helps within one process. Across multiple workers/servers
you need **S3 conditional writes / versioning** or a real database. This is a
genuine production consideration — see the note in `scrape_config.py`.

## Uploads are the riskiest surface — always:
- **Authenticate** — these endpoints sit behind the `X-API-Key` dependency.
- **Limit size** — `_read_capped` rejects anything over 50 MB (→ `413`).
- **Validate** — wrong file type or unparseable content → `422`. Sanitize the
  filename so it can't escape into a weird storage path.
- **Decide replace vs append** — and what a duplicate upload should do.

## Try it
```bash
# Case 1: upload an input table (make a small CSV first)
printf 'url,priority\nhttps://a,1\nhttps://b,2\n' > /tmp/targets.csv
curl -X POST localhost:8000/scrape-config/input-table -F 'file=@/tmp/targets.csv;type=text/csv'
curl localhost:8000/scrape-config/input-table          # see current table meta

# Case 2: append to the blacklist twice — watch dedupe
curl -X POST localhost:8000/scrape-config/blacklist -H 'content-type: application/json' -d '{"entries":["a.com","b.com"]}'
curl -X POST localhost:8000/scrape-config/blacklist -H 'content-type: application/json' -d '{"entries":["b.com","c.com"]}'
curl localhost:8000/scrape-config/blacklist            # -> a.com, b.com, c.com

# Validation
curl -i -X POST localhost:8000/scrape-config/greylist -H 'content-type: application/json' -d '{"entries":["x"]}'  # 422
```
Or do it all visually in **http://localhost:8000/docs** under **scrape-config**
(the file upload even gives you a file picker).

## Key takeaways
- Uploads = client **sends** data in the request **body**, via **POST/PUT**.
- **JSON body** (small data), **file upload** (`UploadFile`), or **presigned URL**
  (large files straight to S3).
- Choose **replace vs append** deliberately; append needs care about concurrency.
- Always **auth + size-limit + validate** uploads — they're the riskiest surface.

⬅️ Back to the **[course README](README.md)** · See the **[Glossary](glossary.md)**.
