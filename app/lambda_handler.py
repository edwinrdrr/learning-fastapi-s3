"""AWS Lambda entrypoint: wrap the FastAPI app with Mangum.

Deploy this as the Lambda handler `app.lambda_handler.handler` (container-image
Lambda, behind API Gateway). For every other runtime — local dev, App Runner,
ECS, EC2 — this file is unused; those run uvicorn against `app.main:app` directly.

Lambda notes:
  - Memory: 2048 MB (Lambda CPU scales with memory; DuckDB wants the headroom).
  - DuckDB downloads the httpfs/aws extensions on first use, so the function
    needs egress (or bundle the extensions into the image). Point DuckDB's home
    at a writable dir, e.g. set HOME=/tmp.
  - S3 access uses the function's IAM role (leave S3_ENDPOINT_URL and the static
    AWS keys unset); see app/storage.py and app/daily.py.
"""
from mangum import Mangum

from app.main import app

handler = Mangum(app)
