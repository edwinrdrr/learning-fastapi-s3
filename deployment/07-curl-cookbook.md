# 07 — Curl cookbook (copy-paste tests)

Ready-to-run commands for the local API. **Open this file in your editor and copy the lines.**

**Prereqs:** the stack is up (`docker compose up -d`) and the API is on
`http://localhost:8000`. Auth is off locally; if you set `API_KEY`, add
`-H "X-API-Key: <your-key>"` to each data-route command.

---

## Blacklist (the one you're testing)

```bash
# show the current blacklist
curl -s http://localhost:8000/scrape-config/blacklist

# add entries (deduplicated automatically)
curl -s -X POST http://localhost:8000/scrape-config/blacklist \
  -H 'content-type: application/json' \
  -d '{"entries":["spam.com","SKU-42"]}'

# add again, including a duplicate — only the new one is added
curl -s -X POST http://localhost:8000/scrape-config/blacklist \
  -H 'content-type: application/json' \
  -d '{"entries":["spam.com","fraud.net"]}'

# show it again to see the result
curl -s http://localhost:8000/scrape-config/blacklist
```

Expected: the second POST returns `"added":1` (the duplicate `spam.com` is skipped).

---

## Whitelist (same shape, separate list)

```bash
curl -s http://localhost:8000/scrape-config/whitelist

curl -s -X POST http://localhost:8000/scrape-config/whitelist \
  -H 'content-type: application/json' \
  -d '{"entries":["trusted-seller.com"]}'
```

---

## Input table (file upload — replaces the current table)

```bash
# make a tiny sample CSV
printf 'sku,url\nSKU-1,https://example.com/1\nSKU-2,https://example.com/2\n' > /tmp/targets.csv

# upload it (multipart) — replaces any existing input table
curl -s -X POST http://localhost:8000/scrape-config/input-table \
  -F 'file=@/tmp/targets.csv;type=text/csv'

# read back its metadata
curl -s http://localhost:8000/scrape-config/input-table
```

---

## Scrape dataset (read-only)

```bash
# metadata (row count + columns) — 404 until a day is seeded
curl -s http://localhost:8000/scrape/2026-06-26/meta

# one page of rows (page_size max is 5000)
curl -s 'http://localhost:8000/scrape/2026-06-26?page=1&page_size=5000'
```

> No data yet? Seed a day first (the generator lives outside this repo) — see
> [04-run-locally.md](04-run-locally.md).

---

## Readings CRUD demo

```bash
# create one reading
curl -s -X POST http://localhost:8000/readings \
  -H 'content-type: application/json' \
  -d '{"sensor_id":"sensor-001","metric":"temperature","value":21.5,"unit":"C","recorded_at":"2026-06-26T10:00:00Z"}'

# list readings for that sensor
curl -s 'http://localhost:8000/readings?sensor_id=sensor-001'
```

---

## Health

```bash
curl -s http://localhost:8000/health
# {"status":"ok","s3":"reachable","bucket":"readings"}
```

---

## Shortcut: the `~/bl.sh` helper

If typing curls is a hassle, there's a tiny wrapper at `~/bl.sh` (created during testing):

```bash
~/bl.sh                       # show the blacklist
~/bl.sh add spam.com SKU-42   # add entries (space-separated)
~/bl.sh clear                 # empty it
```
