# 10 — Production concerns

**Goal:** know what separates "it runs on my laptop" from "it's safe to deploy."
You don't need to master these now — just recognize them and where they live.

---

## The mindset shift

A toy API trusts everyone and runs as one process. A production API assumes the
internet is hostile and busy. Here's what this project added (a "hardening pass")
and why.

## 1. Validate every input
Never trust what comes in. The `valid_day` check (Lesson 08) rejects anything that
isn't a real date — which also blocks injection attacks, since that value builds a
file path and a query. **Rule: validate at the boundary.**

## 2. Authentication — who is calling?
An optional **API key**: if `API_KEY` is set, clients must send a matching
`X-API-Key` header or get `401`. See **[`../app/security.py`](../app/security.py)**.
It's off locally (no key set) and switched on by configuration in production. Real
systems often go further (OAuth/JWT), but an API key is the simplest real auth.

## 3. CORS — which websites may call from a browser?
Browsers block a page on `site-a.com` from calling your API on `api-b.com` unless
the API opts in. **CORS** config declares allowed origins. (Configured in
`main.py`.)

## 4. Rate limiting — don't let one caller flood you
A global limit (e.g. `120/minute`) returns `429` when exceeded, protecting the
service from abuse or runaway clients. (Added via `slowapi` in `main.py`.)

## 5. Packaging — Docker, done right
**[`../Dockerfile`](../Dockerfile)** builds a runnable image. Production touches:
- **Non-root user** — if the app is compromised, the attacker isn't root.
- **Multiple workers, no `--reload`** — `--reload` is a dev convenience; prod runs
  several worker processes for throughput.
- **Healthcheck** — the platform can tell if the app is alive and restart it.
- **Multi-stage build / `.dockerignore`** — small, clean images.

(Locally, `docker-compose.yml` overrides the command back to `--reload` so you get
hot-reloading while learning.)

## 6. Secrets & credentials
No passwords in code. Config comes from **environment variables** (Lesson 06). On
AWS you use an **IAM role** instead of static keys — the app gets temporary
credentials automatically. (`storage.py` supports both.)

## 7. Tests — prove it works, keep it working
**[`../tests/`](../tests)** has automated tests (run with `pytest`) that check the
endpoints behave: valid input → 200, bad input → 422, missing data → 404, etc.
Tests let you change code confidently — if you break something, a test fails.

```bash
pip install -r ../requirements-dev.txt
python -m pytest ../tests -q
```

## 8. Observability — see what's happening
Logs (and later, metrics/tracing) so you can answer "is it slow? is it erroring?"
in production. This app logs via Python's `logging`.

## A handy mental checklist
Before exposing an API publicly: **validated inputs? auth? rate limits? HTTPS
(via a reverse proxy)? no secrets in code? healthcheck? tests? logging?**

## Try it
```bash
# run the tests
cd .. && pip install -r requirements-dev.txt && python -m pytest tests -q

# see auth in action: set a key, restart, then call without/with it
# (edit docker-compose.yml: set API_KEY under the api service's environment)
```

## Key takeaways
- Production = assume hostile + busy: **validate, authenticate, limit, isolate**.
- **Docker** runs non-root with workers + healthcheck; secrets come from the env.
- **Tests** protect you from future mistakes.
- You've already got all of this in the repo — now you know what each piece is for.

---

🎉 **You've finished the core course.** You went from "what is an API" to
understanding a real, hardened, fast API end to end. There's a bonus lesson on the
*write* side — **[11 — Uploads](11-uploads.md)** (how clients send data in). Then
see the **[Glossary](glossary.md)** for any term, and **[Exercises](exercises.md)**
to cement it by doing.

### Where to go next
- Build a tiny API of your own from scratch (the Exercises start you off).
- Read the official **FastAPI tutorial** (excellent): https://fastapi.tiangolo.com/tutorial/
- Revisit **[../docs/internal-architecture.md](../docs/internal-architecture.md)**
  now that the concepts click.
