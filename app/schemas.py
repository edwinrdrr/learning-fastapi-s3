"""Pydantic schemas = the data contracts at the API boundary.

These validate everything entering the system. In data engineering this same
idea is called a 'schema contract' — you reject bad records at the door instead
of letting them poison the data lake.
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ---- Input ----

class ReadingCreate(BaseModel):
    sensor_id: str = Field(..., max_length=64, examples=["sensor-001"])
    metric: str = Field(..., max_length=64, examples=["temperature"])
    value: float = Field(..., examples=[21.5])
    unit: str = Field(..., max_length=16, examples=["C"])
    recorded_at: datetime = Field(..., examples=["2026-06-26T10:00:00Z"])


class ReadingBulkCreate(BaseModel):
    """Batch ingest: many readings in one call = far fewer S3 round-trips."""
    readings: list[ReadingCreate] = Field(..., min_length=1, max_length=10_000)


# ---- Output ----

class ReadingOut(ReadingCreate):
    # Same fields as input, plus the S3 key where it lives.
    model_config = ConfigDict(from_attributes=True)
    key: str = Field(..., examples=["sensor-001/2026-06-26/ab12.json"])


class BulkResult(BaseModel):
    inserted: int
    keys: list[str]


class MetricSummary(BaseModel):
    """Aggregated stats per metric — computed by reading many JSON files."""
    metric: str
    count: int
    avg: float
    min: float
    max: float


# ---- Scrape dataset (the daily-scrape product) ----
# These models exist mainly to enrich the auto-generated OpenAPI docs: they give
# /docs full response schemas, field descriptions, and examples.

class HealthOut(BaseModel):
    status: str = Field(..., examples=["ok"])
    s3: str = Field(..., examples=["reachable"])
    bucket: str = Field(..., examples=["readings"])


class DayMeta(BaseModel):
    """Metadata for one scrape day, without downloading the rows."""
    day: str = Field(..., description="Scrape date (YYYY-MM-DD)", examples=["2026-03-15"])
    rows: int = Field(..., description="Number of records in the day", examples=[20000])
    columns: list[str] = Field(
        ..., description="Column names present in the dataset",
        examples=[["id", "scraped_at", "sku", "title", "price"]],
    )


class ScrapeRecord(BaseModel):
    """One product record from a daily scrape. Timestamps are returned exactly as
    scraped: ISO-8601, UTC, trailing `Z`."""
    id: int = Field(..., description="Row index within the day", examples=[0])
    scraped_at: str = Field(..., description="When the scrape ran (ISO-8601 UTC)",
                            examples=["2026-03-15T03:00:00Z"])
    sku: str = Field(..., examples=["SKU-690713"])
    title: str = Field(..., examples=["Stark Lego Set Max"])
    brand: str = Field(..., examples=["Stark"])
    category: str = Field(..., examples=["toys"])
    subcategory: str = Field(..., examples=["lego-set"])
    price: float = Field(..., examples=[436.41])
    currency: str = Field(..., description="ISO-4217 currency code", examples=["EUR"])
    original_price: float = Field(..., description="Pre-discount price", examples=[436.41])
    discount_pct: int = Field(..., description="Discount percentage (0–50)", examples=[0])
    in_stock: bool = Field(..., examples=[True])
    stock_qty: int = Field(..., description="Units in stock (0 if out of stock)", examples=[60])
    rating: float = Field(..., description="Average rating, 1.0–5.0", examples=[1.8])
    review_count: int = Field(..., examples=[4274])
    seller: str = Field(..., examples=["marketplace-a"])
    url: str = Field(..., examples=["https://example-shop.com/toys/lego-set/0"])
    shipping_days: int = Field(..., description="Estimated shipping days", examples=[4])
    warehouse_country: str = Field(..., description="ISO-3166 country code", examples=["ES"])
    updated_at: str = Field(..., description="Listing last-updated (ISO-8601 UTC)",
                            examples=["2026-03-15T01:21:00Z"])


# ---- Scrape config (the upload / control-plane) ----

class AppendEntries(BaseModel):
    """Entries to append to a blacklist/whitelist."""
    entries: list[str] = Field(
        ..., min_length=1, max_length=100_000,
        description="Values to add (deduplicated against existing)",
        examples=[["blocked-seller.com", "SKU-000123"]],
    )


class AppendResult(BaseModel):
    name: str = Field(..., examples=["blacklist"])
    added: int = Field(..., description="How many were newly added", examples=[2])
    total: int = Field(..., description="Total entries after append", examples=[42])
    added_entries: list[str] = Field(..., examples=[["blocked-seller.com"]])


class ListState(BaseModel):
    name: str = Field(..., examples=["blacklist"])
    count: int = Field(..., examples=[42])
    entries: list[str] = Field(..., examples=[["blocked-seller.com", "SKU-000123"]])


class InputTableMeta(BaseModel):
    """Metadata about the current scraping input table."""
    filename: str = Field(..., examples=["targets.csv"])
    rows: int = Field(..., examples=[1500])
    columns: list[str] = Field(..., examples=[["url", "category", "priority"]])
    uploaded_at: str = Field(..., examples=["2026-06-27T09:00:00+00:00"])
    key: str = Field(..., description="S3 key of the stored file",
                     examples=["config/scrape/input_table/history/20260627T090000Z__targets.csv"])
