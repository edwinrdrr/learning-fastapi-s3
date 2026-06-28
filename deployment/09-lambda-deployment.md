# 09 — The Lambda deployment (focused: just Lambda + ECR)

This page covers **one deployment only — Lambda** — start to finish, with no alternatives to
distract. (Other docs compare App Runner / ECS / EC2 because the same app *can* run on those too;
ignore them if you've chosen Lambda. The menu is in [`../infra-choices/`](../infra-choices/).)

## Does Lambda use ECR? — Yes.

Lambda runs your app from a **container image**, and a container image has to be **stored in a
registry**. For Lambda that registry is **ECR**. So the flow is:

```
  you:    docker build (Dockerfile.lambda)  →  docker push  →  [ ECR ]  (image stored)
  AWS:    Lambda pulls the image from ECR  →  runs it
```

ECR = **where the code is stored**. Lambda = **what runs it** (it pulls from ECR). You can't skip
ECR for a container-image Lambda — Lambda can only pull images from ECR.

## The architecture (Lambda only)

```
 [ CLIENT ]
     │  HTTPS:  GET /scrape/2026-06-26?page=2&page_size=5000
     ▼
 [ API GATEWAY ]            ← the public HTTPS endpoint
     │  invokes the function
     ▼
 [ LAMBDA FUNCTION ]        ← runs your app
     │   • cold start: pulls the image ◀──── [ ECR ]   (image storage)
     │   • Mangum → FastAPI app (your app/ code)
     │   • reads the data file from S3 ───┐  (using the Lambda IAM role)
     ▼                                     ▼
 (response back up)                  [ S3 BUCKET ]
   Lambda → API Gateway → CLIENT     processed/scrape/dt=2026-06-26/data.parquet
```

## The components (Lambda only)

| Component | Role |
|---|---|
| **API Gateway** | public HTTPS endpoint; receives the request, invokes Lambda |
| **Lambda function** | runs your app; pulls its image from ECR on cold start |
| **ECR** | stores the container image (built from `Dockerfile.lambda`) |
| **S3** | holds the data files (`processed/scrape/dt=…/data.parquet`) |
| **IAM execution role** | lets the Lambda code read/write S3 — no keys in code |
| `app/lambda_handler.py` (Mangum) | the only Lambda-specific line; hands the request to the app |

## How the code gets to Lambda

```bash
# set once
export AWS_REGION=us-east-1
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export IMAGE="$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/learning-fastapi-s3:lambda"

# 1. build the Lambda image (x86_64 — matches the baked DuckDB extensions)
docker build --platform linux/amd64 -f Dockerfile.lambda -t "$IMAGE" .

# 2. push it to ECR  (this is the "stored in ECR" step)
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"
docker push "$IMAGE"

# 3. create the Lambda function that POINTS AT the ECR image
aws lambda create-function \
  --function-name learning-fastapi-s3 \
  --package-type Image \
  --code ImageUri="$IMAGE" \
  --role arn:aws:iam::$ACCOUNT_ID:role/<lambda-exec-role> \
  --architectures x86_64 --memory-size 2048 --timeout 30 \
  --environment "Variables={S3_BUCKET=<bucket>,AWS_REGION=$AWS_REGION,CORS_ORIGINS=*}"

# 4. put an HTTP API Gateway in front, proxying all routes to the function
aws apigatewayv2 create-api --name learning-fastapi-s3 --protocol-type HTTP \
  --target arn:aws:lambda:$AWS_REGION:$ACCOUNT_ID:function:learning-fastapi-s3
```

Prerequisites (the bucket, the IAM role + S3 policy, the `API_KEY` secret) are the same as any AWS
deploy — see [05-deploy-aws.md](05-deploy-aws.md). Leave `S3_ENDPOINT_URL` and the static AWS keys
**unset** so the code uses the execution role.

**Redeploy** = push a new image, then point the function at it:
```bash
docker push "$IMAGE"
aws lambda update-function-code --function-name learning-fastapi-s3 --image-uri "$IMAGE"
```

## A request, end to end

1. Client → **API Gateway** (HTTPS).
2. API Gateway **invokes the Lambda function**.
3. *(cold start only)* Lambda **pulls the image from ECR** and inits (loads the app + the pre-baked
   DuckDB extensions). Warm instances skip this.
4. **Mangum** hands the request to your FastAPI app.
5. App validates (API key, date, paging), routes to `get_day`.
6. **DuckDB reads the Parquet directly from S3** (HTTP range reads — only the rows asked for), using
   the **IAM role** for credentials.
7. The page of JSON streams back: Lambda → API Gateway → client (`200 OK`).

The detailed per-step version (with status codes, cold-start timing, and multi-day performance) is
in [`../learning/12-request-lifecycle.md`](../learning/12-request-lifecycle.md).

## Cold starts (short version)

The **first** request on a **new** Lambda instance is a "cold start" (~1–3 s): provision the
instance + pull the image from ECR + init the app. After that the instance stays **warm** (requests
in tens of ms) until it's reclaimed after idle. ECR is touched **only at cold start**, never during
a warm request. Full explanation: the lifecycle doc above.

## Why this design

- **Scale to zero** — you pay only per request; ~$0 when idle.
- **Stateless** — DuckDB reads Parquet straight from S3, nothing cached locally, so a fresh Lambda
  instance is as good as a warm one.
- The trade-offs (cold starts, small pages, bulk-export limits) are in
  [`../infra-choices/04-lambda.md`](../infra-choices/04-lambda.md).
