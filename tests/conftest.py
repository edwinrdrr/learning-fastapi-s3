"""Test fixtures.

The TestClient is created WITHOUT a `with` block on purpose, so the app's
lifespan (which calls storage.ensure_bucket → hits S3) does NOT run. Tests stay
hermetic: they monkeypatch the storage/daily layer instead of needing MinIO.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
