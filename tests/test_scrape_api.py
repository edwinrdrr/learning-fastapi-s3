"""Tests for the scrape API: validation, 404s, method guards, auth."""
from app import daily, storage
from app.config import settings


# ---- health ----

def test_health_ok(client, monkeypatch):
    monkeypatch.setattr(storage, "ping", lambda: None)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ---- day validation (security: blocks injection / path traversal) ----

def test_day_bad_format_rejected(client):
    assert client.get("/scrape/not-a-date/meta").status_code == 422


def test_day_impossible_date_rejected(client):
    # passes the regex but isn't a real date
    assert client.get("/scrape/2026-02-30/meta").status_code == 422


def test_day_injection_attempt_rejected(client):
    assert client.get("/scrape/2026-01-01';DROP/meta").status_code == 422


# ---- meta ----

def test_meta_404_when_missing(client, monkeypatch):
    monkeypatch.setattr(daily, "meta", lambda day: None)
    assert client.get("/scrape/2026-03-15/meta").status_code == 404


def test_meta_ok(client, monkeypatch):
    monkeypatch.setattr(daily, "meta",
                        lambda day: {"day": day, "rows": 3, "columns": ["id"]})
    r = client.get("/scrape/2026-03-15/meta")
    assert r.status_code == 200
    assert r.json() == {"day": "2026-03-15", "rows": 3, "columns": ["id"]}


# ---- get day ----

def test_get_day_404_when_missing(client, monkeypatch):
    monkeypatch.setattr(daily, "export_json", lambda *a, **k: None)
    assert client.get("/scrape/2026-03-15").status_code == 404


def test_get_day_ok_streams_json(client, monkeypatch, tmp_path):
    out = tmp_path / "out.json"
    out.write_text('[{"id": 0, "sku": "X"}]')
    monkeypatch.setattr(daily, "export_json", lambda *a, **k: str(out))
    r = client.get("/scrape/2026-03-15?page=1&page_size=10")
    assert r.status_code == 200
    assert r.json() == [{"id": 0, "sku": "X"}]


def test_get_day_page_validation(client):
    # page must be >= 1
    assert client.get("/scrape/2026-03-15?page=0").status_code == 422


# ---- read-only API ----

def test_post_not_allowed(client):
    assert client.post("/scrape/2026-03-15", json=[]).status_code == 405


# ---- api-key auth ----

def test_auth_enforced_when_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret")
    monkeypatch.setattr(daily, "meta",
                        lambda day: {"day": day, "rows": 1, "columns": ["id"]})

    assert client.get("/scrape/2026-03-15/meta").status_code == 401
    ok = client.get("/scrape/2026-03-15/meta", headers={"X-API-Key": "secret"})
    assert ok.status_code == 200
