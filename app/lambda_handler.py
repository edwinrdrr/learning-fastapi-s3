"""AWS Lambda entrypoint: wrap the FastAPI app with Mangum.

Deploy this as the Lambda handler `app.lambda_handler.handler` (container-image
Lambda, behind API Gateway). For every other runtime — local dev, App Runner,
ECS, EC2 — this file is unused; those run uvicorn against `app.main:app` directly.

Lambda notes:
  - Build with Dockerfile.lambda (AWS base image + Runtime Interface). It bakes
    DuckDB's httpfs/aws extensions into the image and sets DUCKDB_EXTENSION_DIRECTORY
    + HOME=/tmp, so cold starts load them offline (no egress needed).
  - Memory: 2048 MB (Lambda CPU scales with memory; DuckDB wants the headroom).
  - S3 access uses the function's IAM role (leave S3_ENDPOINT_URL and the static
    AWS keys unset); see app/storage.py and app/daily.py.
"""
from mangum import Mangum

from app.main import app

handler = Mangum(app)
