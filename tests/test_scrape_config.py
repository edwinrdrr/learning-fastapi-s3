"""Tests for the upload / control-plane endpoints (scrape-config)."""
import json

import pytest

from app import storage


@pytest.fixture
def mem_store(monkeypatch):
    """In-memory stand-in for S3 so these tests need no MinIO."""
    store: dict = {}

    def get_json(key):
        raw = store.get(key)
        return json.loads(raw) if raw is not None else None

    def put_json(key, data):
        store[key] = json.dumps(data)

    def put_bytes(key, data, content_type="application/octet-stream"):
        store[key] = data

    def get_bytes(key):
        return store.get(key)

    monkeypatch.setattr(storage, "get_json", get_json)
    monkeypatch.setattr(storage, "put_json", put_json)
    monkeypatch.setattr(storage, "put_bytes", put_bytes)
    monkeypatch.setattr(storage, "get_bytes", get_bytes)
    return store


# ---- blacklist / whitelist append ----

def test_append_dedupes_and_accumulates(client, mem_store):
    r = client.post("/scrape-config/blacklist", json={"entries": ["a", "b", "a"]})
    assert r.status_code == 201
    assert r.json()["added"] == 2 and r.json()["total"] == 2

    r2 = client.post("/scrape-config/blacklist", json={"entries": ["b", "c"]})
    assert r2.json()["added"] == 1          # only "c" is new
    assert r2.json()["total"] == 3

    got = client.get("/scrape-config/blacklist").json()
    assert got["entries"] == ["a", "b", "c"]
    assert got["count"] == 3


def test_lists_are_independent(client, mem_store):
    client.post("/scrape-config/blacklist", json={"entries": ["x"]})
    client.post("/scrape-config/whitelist", json={"entries": ["y"]})
    assert client.get("/scrape-config/blacklist").json()["entries"] == ["x"]
    assert client.get("/scrape-config/whitelist").json()["entries"] == ["y"]


def test_unknown_list_name_rejected(client, mem_store):
    assert client.post("/scrape-config/greylist", json={"entries": ["a"]}).status_code == 422


def test_empty_entries_rejected(client, mem_store):
    assert client.post("/scrape-config/blacklist", json={"entries": []}).status_code == 422


# ---- input table upload ----

def test_upload_csv_input_table(client, mem_store):
    csv = b"url,priority\nhttp://a,1\nhttp://b,2\n"
    r = client.post("/scrape-config/input-table",
                    files={"file": ("targets.csv", csv, "text/csv")})
    assert r.status_code == 201
    body = r.json()
    assert body["rows"] == 2
    assert body["columns"] == ["url", "priority"]

    meta = client.get("/scrape-config/input-table").json()
    assert meta["filename"] == "targets.csv" and meta["rows"] == 2


def test_upload_unsupported_type_rejected(client, mem_store):
    r = client.post("/scrape-config/input-table",
                    files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 422


def test_get_input_table_404_when_none(client, mem_store):
    assert client.get("/scrape-config/input-table").status_code == 404
