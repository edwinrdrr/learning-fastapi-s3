# 05 — Deploy to AWS (shared setup)

These steps are the **same regardless of compute target**. Once they're done, pick a target in
[`../infra-choices/`](../infra-choices/) (App Runner ⭐ / ECS / EC2 / Lambda) and follow that
file for the target-specific wiring.

Set these once:

```bash
export AWS_REGION=us-east-1
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export BUCKET=readings-<your-unique-suffix>     # bucket names are globally unique
export REPO=learning-fastapi-s3
export IMAGE="$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$REPO:latest"
```

## 1. S3 bucket (pre-create)

```bash
aws s3api create-bucket --bucket "$BUCKET" --region "$AWS_REGION"
# non-us-east-1 needs: --create-bucket-configuration LocationConstraint=$AWS_REGION
aws s3api put-public-access-block --bucket "$BUCKET" \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
```

Pre-creating means the app never needs `s3:CreateBucket`. Your upstream producer writes
`processed/scrape/dt=…/data.parquet` here (see [03-data-contract.md](03-data-contract.md)).

## 2. Push the image to ECR

```bash
aws ecr create-repository --repository-name "$REPO" --region "$AWS_REGION"
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"
docker build -t "$IMAGE" .
docker push "$IMAGE"
```

## 3. Store the API key as a secret

```bash
aws ssm put-parameter --name /learning-fastapi-s3/API_KEY \
  --type SecureString --value "$(openssl rand -hex 24)"
```

## 4. IAM policy for the service role (read + write)

Attach this to whatever role the compute target uses (App Runner instance role / ECS task role
/ EC2 instance profile / Lambda execution role). It is **read and write** because `/readings`
and `/scrape-config` write objects — see [03-data-contract.md](03-data-contract.md).

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": ["s3:ListBucket"],
      "Resource": "arn:aws:s3:::BUCKET" },
    { "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::BUCKET/*" },
    { "Effect": "Allow", "Action": ["ssm:GetParameter"],
      "Resource": "arn:aws:ssm:REGION:ACCOUNT_ID:parameter/learning-fastapi-s3/API_KEY" }
  ]
}
```

## 5. Runtime configuration (every target)

Set these as the service's environment + secret, and **leave the local-only vars unset** so
boto3 and DuckDB use the role's credentials:

| Set | Leave UNSET |
|---|---|
| `S3_BUCKET=$BUCKET` | `S3_ENDPOINT_URL` |
| `AWS_REGION=$AWS_REGION` | `AWS_ACCESS_KEY_ID` |
| `CORS_ORIGINS=<your origin>` | `AWS_SECRET_ACCESS_KEY` |
| `RATE_LIMIT=120/minute` | |
| `API_KEY` ← from the SSM secret (step 3) | |

Full reference: [02-configuration.md](02-configuration.md).

## 6. Pick a compute target

| Target | Guide | Idle cost/mo |
|---|---|---|
| App Runner ⭐ | [`../infra-choices/01-app-runner.md`](../infra-choices/01-app-runner.md) | ~$10–15 |
| ECS Fargate + ALB | [`../infra-choices/02-ecs-fargate-alb.md`](../infra-choices/02-ecs-fargate-alb.md) | ~$35–45 |
| EC2 + docker compose | [`../infra-choices/03-ec2-docker-compose.md`](../infra-choices/03-ec2-docker-compose.md) | ~$8–17 |
| Lambda | [`../infra-choices/04-lambda.md`](../infra-choices/04-lambda.md) | ~$0 idle |

## 7. Verify

```bash
curl https://<your-url>/health                         # 200 {"status":"ok",...}  => role + bucket OK
curl https://<your-url>/scrape/<day>/meta              # 200 once a day exists, else 404
curl https://<your-url>/readings -H "X-API-Key: <key>" # 200 with the key, 401/403 without
```
A `503` on `/health` means the role can't reach S3 — widen/fix the policy in step 4.
