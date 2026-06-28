"""Endpoint 7: aggregation / analytics.

This is the 'transform' step. With no database, we must LIST the objects, GET
each one, and compute stats in Python. It works for a few thousand readings and
is great for learning — but notice it gets slow as data grows, because every
request re-reads every file. That pain is precisely why data warehouses and
query engines (DuckDB, Athena, BigQuery) exist. A natural next exercise: point
DuckDB at these JSON files and run `SELECT metric, avg(value) ... GROUP BY metric`.
"""
from collections import defaultdict

from fastapi import APIRouter, Query

from app import storage
from app.schemas import MetricSummary

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/summary", response_model=list[MetricSummary])
def metric_summary(
    sensor_id: str | None = Query(None, description="Limit to one sensor"),
) -> list[MetricSummary]:
    prefix = "readings/"
    if sensor_id:
        prefix += f"{sensor_id}/"

    # Collect every value, grouped by metric.
    values: dict[str, list[float]] = defaultdict(list)
    for key in storage.list_keys(prefix=prefix, limit=100_000):
        data = storage.get_json(key)
        if data is not None:
            values[data["metric"]].append(float(data["value"]))

    summaries: list[MetricSummary] = []
    for metric, vals in sorted(values.items()):
        summaries.append(
            MetricSummary(
                metric=metric,
                count=len(vals),
                avg=sum(vals) / len(vals),
                min=min(vals),
                max=max(vals),
            )
        )
    return summaries
