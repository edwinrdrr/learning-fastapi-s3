# 08 — Images, ECR, and where your code runs

A common point of confusion: *"if the code runs on Lambda, why do we need ECR?"* This page
answers that by separating three things that are easy to blur together — **your code**, the
**image** that packages it, and the **registry (ECR)** that stores the image.

## 1. Your code vs the host that runs it

Your application code is the `app/` package — `main.py`, `routers/`, `daily.py`, `storage.py`.
**That code is identical no matter where you deploy.** What changes is the *host* it runs in and
the tiny *adapter* that feeds requests to it.

```
   request lifecycle steps ④–⑨ (FastAPI app, routing, dependencies, DuckDB→S3 read)
   = YOUR code, runs INSIDE whatever host you deploy to
```

| Layer | App Runner / ECS / EC2 | Lambda |
|---|---|---|
| Front door (TLS) | App Runner URL / ALB / your proxy | API Gateway |
| Adapter (③) | **uvicorn** (a server process) | **Mangum** (`app/lambda_handler.py`) |
| Your app (④–⑨) | runs inside the container | runs inside the Lambda function |

So "we store the code on Lambda" isn't quite it — your code runs *inside* the Lambda function,
but it gets there as a **container image**, and an image has to be **stored somewhere** Lambda
can fetch it. That somewhere is ECR.

## 2. ECR = a private image registry (the shelf)

**ECR (Elastic Container Registry)** is AWS's private Docker registry — the AWS equivalent of
Docker Hub, scoped to your account. Its only job is to **store and serve container images**. It
runs nothing itself; it's a shelf.

The workflow is **build once → push once → pull many**:

```bash
docker build -t <ecr-url>/learning-fastapi-s3:latest .   # package code into an image
docker push <ecr-url>/learning-fastapi-s3:latest          # store the image in ECR
# ...then any compute target PULLS that image to run it
```

"Pull" = the target authenticates to ECR (using its IAM role) and downloads the image by
address, e.g. `123456789.dkr.ecr.us-east-1.amazonaws.com/learning-fastapi-s3:latest`.

## 3. This project needs *two* images

The container targets and Lambda don't run the image the same way, so they need slightly
different builds — **but both images live in the same ECR repo, as different tags**:

| Built from | Tag | Used by | Runs |
|---|---|---|---|
| `Dockerfile` | `:latest` | App Runner, ECS, EC2 | a long-running **uvicorn** server on port 8000 |
| `Dockerfile.lambda` | `:lambda` | Lambda | **Mangum** handler + pre-baked DuckDB extensions |

Lambda needs its own image because it requires the Lambda **Runtime Interface** (provided by the
`public.ecr.aws/lambda/python` base image) — a normal uvicorn image can't be invoked by Lambda.

## 4. The whole picture

```
   build                          push
Dockerfile ──────▶ image :latest ─────┐
Dockerfile.lambda ▶ image :lambda ────┤
                                      ▼
                          ┌────────────────────────────┐
                          │  ECR repo                   │
                          │  learning-fastapi-s3        │   ← the shelf:
                          │    :latest   (uvicorn)      │     stores the image(s),
                          │    :lambda   (Mangum)       │     runs nothing
                          └────────────────────────────┘
            pull :latest    │          │          │   pull :lambda
          ┌─────────────────┘          │          └─────────────────┐
          ▼                            ▼                            ▼
     App Runner                   ECS Fargate                    Lambda
     (runs uvicorn)               (runs uvicorn)                 (runs Mangum)
          ▲
     EC2 can also pull :latest (or just build the image on the box itself)
```

- **ECR = the warehouse** where the boxed-up app (the image) sits.
- **App Runner / ECS / EC2 / Lambda = workers** that pull the box from the warehouse, unpack it,
  and run it.
- A Lambda function is **tiny config** — *"run the image at this ECR address, handler
  `app.lambda_handler.handler`, 2 GB, this IAM role."* The actual code lives in ECR.

## 5. Mental model & FAQ

> **ECR stores the built image(s). App Runner / ECS / EC2 / Lambda are runners that pull an
> image from ECR and run it. Lambda just pulls a different tag than the rest.**

- **"Why ECR if the code runs on Lambda?"** — Because the code is packaged as a container image,
  and an image must be stored in a registry the runner can pull from. Lambda's container mode can
  pull **only from ECR** (not Docker Hub). Lambda runs it; ECR stores it.
- **"Could we skip ECR?"** — Only by using Lambda's **ZIP** package format instead of a
  container image. We didn't, because DuckDB's native binary + baked extensions are exactly what
  the container image handles cleanly. See [`../infra-choices/04-lambda.md`](../infra-choices/04-lambda.md).
- **"Is it the same for App Runner/ECS?"** — Yes: they also pull their image from ECR. They just
  use the `:latest` (uvicorn) tag instead of `:lambda`.

See also: [01-build.md](01-build.md) (building the images), [05-deploy-aws.md](05-deploy-aws.md)
(creating the ECR repo + pushing), and [`../learning/12-request-lifecycle.md`](../learning/12-request-lifecycle.md)
(what runs inside the host, step by step).
