# 11 — Testing the Lambda (before API Gateway)

You can test the Lambda function **without API Gateway in front**. The gateway only translates an
HTTP request into a Lambda "event"; you can hand the function that event yourself and read its
response. Two ways — the AWS one first (testing the real deployed function), then a no-AWS local one.

Both send the function an **API Gateway v2 (HTTP API) event** — because that's the shape Mangum
(`app/lambda_handler.py`) expects. The function returns an API-Gateway-shaped response:
`{"statusCode": 200, "headers": {...}, "body": "<the JSON as a string>", "isBase64Encoded": false}`.

## The test event

Save this as `event.json` — it represents `GET /scrape/2026-06-26/meta`:

```json
{
  "version": "2.0",
  "routeKey": "GET /scrape/{day}/meta",
  "rawPath": "/scrape/2026-06-26/meta",
  "rawQueryString": "",
  "headers": { "host": "localhost", "accept": "*/*" },
  "requestContext": {
    "http": { "method": "GET", "path": "/scrape/2026-06-26/meta", "protocol": "HTTP/1.1", "sourceIp": "127.0.0.1" }
  },
  "isBase64Encoded": false
}
```

To test the **data** endpoint instead, change `rawPath` to `/scrape/2026-06-26` and set
`"rawQueryString": "page=1&page_size=5000"`. For the API key, add `"x-api-key": "<key>"` to `headers`.

---

## Method 1 — On AWS: `aws lambda invoke` (the deployed function)

After `aws lambda create-function` (function exists, **no gateway yet**):

```bash
aws lambda invoke \
  --function-name learning-fastapi-s3 \
  --payload fileb://event.json \
  --cli-binary-format raw-in-base64-out \
  response.json

cat response.json
# {"statusCode":200,"headers":{...},"body":"{\"day\":\"2026-06-26\",\"rows\":20000,\"columns\":[...]}","isBase64Encoded":false}

# pull out just the API response body:
jq -r .body response.json | jq .
```

What a **pass** looks like: `statusCode: 200` and a `body` containing the row count + columns. This
proves the whole function works end to end — Mangum → FastAPI → DuckDB → **S3** (using the function's
**IAM execution role** for credentials) — with no gateway involved.

If it fails, read the logs:
```bash
aws logs tail /aws/lambda/learning-fastapi-s3 --since 5m
```
- `statusCode: 404` → that day isn't in S3 yet (seed it, or use a day that exists).
- An error / `502`-style → usually the **IAM role** can't reach S3, or `S3_BUCKET`/`AWS_REGION` wrong.

---

## Method 2 — Locally, no AWS: the Runtime Interface Emulator (RIE)

The `Dockerfile.lambda` base image ships with the **Lambda Runtime Interface Emulator**, so you can
run the *exact same image* on your machine and invoke it like Lambda would — without deploying. This
tests the image (incl. the baked DuckDB extensions) against your local **MinIO**.

```bash
# 1. build the Lambda image (x86_64, matches the baked extensions)
docker build --platform linux/amd64 -f Dockerfile.lambda -t lambda-test .

# 2. run it on the MinIO network, pointed at the local bucket
docker run --rm -p 9002:8080 \
  --network learning-fastapi-s3_default \
  -e S3_BUCKET=readings -e AWS_REGION=us-east-1 \
  -e S3_ENDPOINT_URL=http://minio:9000 \
  -e AWS_ACCESS_KEY_ID=minioadmin -e AWS_SECRET_ACCESS_KEY=minioadmin \
  lambda-test
# (leave this running; it's the RIE listening on container port 8080 -> host 9002)

# 3. in another shell, invoke it with the same event.json
curl -s "http://localhost:9002/2015-03-31/functions/function/invocations" \
  -d @event.json | jq -r .body | jq .
# -> {"day":"2026-06-26","rows":20000,"columns":[...]}
```

Notes:
- The MinIO stack must be up (`docker compose up -d`) and the day seeded — see
  [04-run-locally.md](04-run-locally.md).
- `--network learning-fastapi-s3_default` puts the Lambda container on the same network as MinIO, so
  `http://minio:9000` resolves. (Run `docker network ls` if your compose project name differs.)
- Here `S3_ENDPOINT_URL` is set, so the app uses the static MinIO keys + the **baked** DuckDB
  extensions (offline) — exactly the cold-start path it'd use on AWS, minus the IAM role.

---

## Which to use

- **Just want to know the image/app works as a Lambda?** → Method 2 (local RIE), no AWS spend.
- **Want to verify the real deployed function + its IAM role + real S3?** → Method 1 (`aws lambda
  invoke`), after `create-function` and before you add API Gateway.

Once both pass, add the gateway ([09-lambda-deployment.md](09-lambda-deployment.md) step 4) and the
same request works over plain HTTPS.
