# 02 — ECS Fargate + ALB

> The standard "real" production container setup. More moving parts than App Runner, but it's
> what you'd run (and be asked about) in a job: a cluster, a task definition, a service behind
> an Application Load Balancer.

## Mental model

- **ECR** = image registry.
- **Task definition** = the blueprint (image, CPU/memory, env, the task role).
- **ECS Service** = keeps N copies of the task running and healthy.
- **Fargate** = serverless compute for the tasks (no EC2 hosts to manage).
- **ALB** = the public entry point + TLS + health checks + routing.

Note: with no ingest job, there is **no EventBridge / scheduled-task** piece here anymore —
just the web service. (That used to be the main reason to prefer ECS; it no longer applies.)

## Architecture

```
   Internet
      │  HTTPS (ACM cert)
      ▼
 ┌─────────┐    ┌──────────────────────── ECS Service (Fargate) ───────────────────┐
 │   ALB   │───▶│  target group  ─▶  task: FastAPI container :8000                  │
 │ +listener│   │                     task role ───────────────────────────────────┼──▶ S3 (r/w)
 └─────────┘    └──────────────────────────────────────────────────────────────────┘
      ▲                  ▲ pulls image
      │ health /health   │
 (security groups,       └── ECR
  subnets, VPC)
```

## Request flow

1. Client → ALB (HTTPS, cert from ACM).
2. ALB health-checks each task at `/health` and routes only to healthy targets.
3. Request → a Fargate task running the container on port 8000.
4. boto3 in the container uses the **ECS task role** (temporary creds from the task metadata
   endpoint) to reach S3.

## App-specific fit notes

- **Task size:** **1 vCPU / 2 GB** for the same DuckDB memory reason as App Runner.
- **Desired count:** keep the web service at **1 task** until the `scrape_config.py` lock is
  replaced — otherwise concurrent blacklist/whitelist appends across tasks can race.
- **IAM is read + write** (`/readings` + `/scrape-config` write): task role gets
  `s3:GetObject/PutObject/DeleteObject/ListBucket` + `ssm:GetParameter` for the API key.
- **Networking is on you:** VPC, subnets, security groups (ALB→task on 8000), and an ALB
  listener/cert. This is the bulk of the extra effort vs App Runner.
- **Logs:** wire the task to the `awslogs` driver → CloudWatch.

## Steps (high level)

1. **S3 bucket** + **ECR push** (same as App Runner).
2. **IAM:** a **task execution role** (pull image, write logs) and a **task role** (S3 r/w +
   `ssm:GetParameter`).
3. **VPC plumbing:** subnets, a security group for the ALB (443 in) and one for tasks (8000
   from the ALB SG only).
4. **ALB:** target group (port 8000, health `/health`), an HTTPS listener with an ACM cert.
5. **Task definition:** image, 1 vCPU/2 GB, env vars, secrets from SSM, awslogs.
6. **ECS Service:** Fargate launch type, desired count 1, attached to the target group.

## Cost (approx, us-east-1)

| Item | ~Monthly |
|---|---|
| Fargate 1 vCPU / 2 GB, 1 task 24/7 | **~$18–22** (vCPU ~$0.04048/hr + mem ~$0.004445/GB-hr) |
| ALB (hourly + LCU) | **~$16–20** |
| ECR / S3 / SSM / logs | cents–$1 |
| **Total** | **~$35–45** |

> The **ALB is the cost surprise** — it roughly doubles the bill vs App Runner and runs 24/7
> regardless of traffic. Since the native-cron advantage is gone, App Runner or EC2 is now the
> better pick unless you specifically want to learn the ECS/ALB stack.

## Pros / cons

**Pros:** the production-standard pattern; fine-grained control (networking, scaling, rolling
deploys); the most transferable job skill.
**Cons:** the most pieces to wire (VPC, SGs, ALB, target group, task def, service); highest
idle cost mostly due to the ALB; easy to misconfigure security groups.

## When to choose

You specifically want to **learn the ECS/Fargate/ALB production stack**, and the ~$35–45/mo
(ALB-driven) is acceptable.
