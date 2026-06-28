# 02 — HTTP basics

**Goal:** learn the "language" a request and response are written in. This is
~80% of understanding APIs.

**HTTP** is the set of rules browsers and servers use to talk. Every request has
a few parts; every response has a few parts. That's it.

---

## A request has 4 parts

```
GET /scrape/2026-03-15?page=1&page_size=100   ← method + path + query
Host: localhost:8000                          ← headers
X-API-Key: secret                             (more headers)
                                              ← (blank line)
(body — usually empty for GET)                ← body
```

### 1. Method (the verb — what you want to *do*)
| Method | Means | Example |
|--------|-------|---------|
| `GET` | **Read** something | "give me the data for this day" |
| `POST` | **Create / send** something | "here's a new record, store it" |
| `PUT`/`PATCH` | **Update** something | "change this record" |
| `DELETE` | **Remove** something | "delete this record" |

Our scrape API only uses **GET** — it's read-only.

### 2. Path (the *what* — names the thing you want)
`/scrape/2026-03-15` — like a file path or an address. It names a resource.

### 3. Query parameters (the *options* — after the `?`)
`?page=1&page_size=100` — extra settings: which page, how many rows.

### 4. Headers & body
- **Headers** = metadata about the request (auth keys, content type, etc.).
- **Body** = the actual data you're sending (used with POST/PUT; empty for GET).

## A response has 3 parts

```
200 OK                              ← status code
content-type: application/json      ← headers
                                    ← (blank line)
[ {"id": 0, "sku": "X"}, ... ]      ← body (the data)
```

### Status codes (the *result*, as a number)
The first digit tells you the category:

| Range | Meaning | Ones you'll see in this project |
|-------|---------|--------------------------------|
| **2xx** | ✅ Success | `200 OK` |
| **4xx** | ❌ *You* (the client) did something wrong | `404` not found, `422` bad input, `405` wrong method, `401` no/bad auth, `429` too many requests |
| **5xx** | 💥 *Server* broke | `503` storage unreachable |

Memorize the vibe: **4xx = your fault, 5xx = my fault.**

### Body
Usually **JSON** — a simple text format for structured data:
```json
{ "day": "2026-03-15", "rows": 20000, "columns": ["id", "sku", "price"] }
```
JSON has objects `{}`, arrays `[]`, strings `"..."`, numbers, `true`/`false`,
`null`. That's the whole format. Our API speaks JSON in and out.

## Try it (with the app running)

```bash
# A successful GET — note the data that comes back
curl http://localhost:8000/scrape/2026-03-15/meta

# Ask for something that doesn't exist — see a 404
curl -i http://localhost:8000/scrape/1999-01-01/meta

# Send a wrong method — see a 405
curl -i -X POST http://localhost:8000/scrape/2026-03-15
```
`-i` makes curl print the **status code + headers**, not just the body. Watch the
first line of each (`HTTP/1.1 200 OK`, `404 Not Found`, `405 Method Not Allowed`).

Or do it visually: open **http://localhost:8000/docs**, expand an endpoint, click
**Try it out** → **Execute**, and read the "Response" section — it shows the exact
status code and JSON body.

## Key takeaways
- A request = **method + path + query + headers + body**.
- A response = **status code + headers + body**.
- **2xx** good, **4xx** your fault, **5xx** server's fault.
- The body is usually **JSON**.

➡️ Next: **[03 — Your first FastAPI endpoint](03-first-fastapi-endpoint.md)** —
now we make the server side.
