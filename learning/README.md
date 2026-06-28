# Learn to Build APIs — from zero

A self-paced course that teaches you what an API is and how to build one, using
the **real, running project in this repo** as the textbook. Every concept points
at actual code you can read, run, and poke.

## Who this is for
You, assuming you know **nothing** about APIs. A little Python helps but isn't
required for the early lessons. We start from "what even is an API" and build up.

## How to use it
1. Read the lessons **in order** — each builds on the last.
2. Keep the app **running** so you can try things:
   ```bash
   cd ..            # into the project root (learning-fastapi-s3)
   docker compose up --build
   ```
3. Keep two browser tabs open while you learn:
   - **http://localhost:8000/docs** — the interactive API (click "Try it out")
   - **http://localhost:9001** — the storage console (`minioadmin`/`minioadmin`)
4. Do the **"Try it"** and **Exercises** — you learn by doing, not just reading.

## Roadmap

| # | Lesson | You'll understand |
|---|--------|-------------------|
| 01 | [What is an API?](01-what-is-an-api.md) | The core idea, with no code |
| 02 | [HTTP basics](02-http-basics.md) | Methods, URLs, status codes, JSON |
| 03 | [Your first FastAPI endpoint](03-first-fastapi-endpoint.md) | Writing + running an endpoint |
| 04 | [Path & query parameters](04-path-and-query-params.md) | Inputs in the URL |
| 05 | [Request bodies & Pydantic](05-request-bodies-and-pydantic.md) | Validated data in/out |
| 06 | [Structuring an app](06-structuring-the-app.md) | Routers, dependencies, config |
| 07 | [Storage & data](07-storage-and-data.md) | Where the data actually lives |
| 08 | [Errors & status codes](08-errors-and-status-codes.md) | Failing correctly |
| 09 | [Making it fast](09-making-it-fast.md) | The data-engineering speed tricks |
| 10 | [Production concerns](10-production-concerns.md) | Auth, Docker, tests, deployment |
| 11 | [Uploads](11-uploads.md) | Sending data *in* (files, JSON, presigned URLs) |
| 12 | [Request lifecycle](12-request-lifecycle.md) | End-to-end trace: client → response, through the real code |
| — | [Glossary](glossary.md) | Every term, defined plainly |
| — | [Exercises](exercises.md) | Hands-on challenges + hints |

## The one-sentence version
An **API** is a way for programs to talk to each other over the web; **FastAPI**
is a Python tool that makes building one straightforward; this project is an API
that serves daily scrape data — and you're about to learn exactly how it works.

➡️ Start with **[01 — What is an API?](01-what-is-an-api.md)**
