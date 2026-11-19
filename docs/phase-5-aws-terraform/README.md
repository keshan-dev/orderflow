# Phase 5: AWS with Terraform

In this phase you run OrderFlow on real AWS. Every piece of AWS is created with code (Terraform), not by clicking in the AWS console. At the end, 1 command builds the whole system and 1 command removes it.

You also rebuild 1 small part (the async module) with AWS CDK in TypeScript, so you can compare the 2 tools from real experience.

> **STOP: written budget needed.** This is the only phase that spends real money. Before your first `terraform apply` against real AWS, write down a budget and a spend limit (the spend rule). See milestone M0 in the [implementation plan](implementation-plan.md) and [cost and safety](../common/08-cost-and-safety.md).

## What you build

| Part | What it is | Code folder |
|---|---|---|
| State bootstrap | An S3 bucket that stores Terraform state | `infra/terraform/bootstrap/` |
| Network | A private network (VPC) in 2 Availability Zones with public, app and data subnets | `infra/terraform/modules/network/` |
| Container platform | ECR (image storage) and an ECS cluster on Fargate | `infra/terraform/modules/ecs-cluster/` |
| Services | 1 ECS service per OrderFlow service, behind an Application Load Balancer | `infra/terraform/modules/ecs-service/` |
| Data | RDS PostgreSQL, ElastiCache (Redis OSS or Valkey), S3 for invoices, Secrets Manager | `infra/terraform/modules/data/` |
| Edge | CloudFront in front of the load balancer, protected by AWS WAF | `infra/terraform/modules/edge/` |
| Async | SQS queues and Lambda functions that replace RabbitMQ and notification-worker | `infra/terraform/modules/async/` |
| Dev environment | Wires all modules together for the `dev` environment | `infra/terraform/envs/dev/` |
| CDK version | The async module again, written in AWS CDK TypeScript | `infra/cdk/` |
| CI | Plan on every pull request, apply only after manual approval | `.github/workflows/` |

## Why this phase matters

- Phases 1 to 4 ran on your machine. Real products run in the cloud, with real networks, real security rules and real bills.
- Infrastructure written as code can be reviewed, repeated and removed. Infrastructure made by clicking cannot.
- Most cloud security problems come from bad network and permission setup. This phase makes you build those layers yourself.

## What you will learn

- Terraform: providers, resources, modules, variables, outputs, state, locking, plan, apply, drift, import.
- How a production AWS network is built: VPC, subnets, route tables, NAT, VPC endpoints, security groups, NACLs.
- How containers run on AWS: ECR, ECS, Fargate, task definitions, services, the Application Load Balancer.
- Managed data services: RDS, ElastiCache, S3, Secrets Manager.
- Serverless async processing: SQS, Lambda, dead letter queues, partial batch failure.
- Edge security: CloudFront, WAF, ACM certificates.
- Safe CI for infrastructure: GitHub Actions with OIDC (no long-lived AWS keys), plan on pull request, manual approval for apply.
- How Terraform and CDK differ, from having used both.

Read [concepts.md](concepts.md) for simple explanations of all of these.

## What changes compared to local

| Local (Phases 1 to 4) | AWS (Phase 5) |
|---|---|
| nginx or Gateway API | Application Load Balancer, with CloudFront and WAF in front |
| Docker Compose or kind | ECS on Fargate |
| PostgreSQL container | RDS PostgreSQL |
| Redis container | ElastiCache |
| MinIO | S3 |
| RabbitMQ + notification-worker | SQS + Lambda |
| Kafka (3 brokers in kind) | 1 Kafka broker task on ECS, **for demo only** (see the decisions in [architecture.md](architecture.md)) |
| OpenSearch | **Off by default** in dev to control cost |
| `.env` files | Secrets Manager |

The full mapping is in [architecture.md](architecture.md).

## Before you start

- Phases 1 and 2 are done. You need working Docker images and a CI pipeline.
- You have read [architecture.md](architecture.md) and [concepts.md](concepts.md).
- You have an AWS account set up the safe way (MFA, budget alert, no root user for daily work). This is milestone M0.
- You have a written budget and spend limit for Phase 5.

## Done checklist

- [ ] Budget and spend limit recorded in the decision log in [`PLAN.md`](../../PLAN.md).
- [ ] AWS Budgets alert is active and tested.
- [ ] Terraform state lives in S3 with `use_lockfile` turned on.
- [ ] `terraform fmt -check` and `terraform validate` pass, and an IaC scanner (Trivy config or Checkov) runs in CI.
- [ ] Pull requests show a `terraform plan`. Apply needs a manual approval.
- [ ] GitHub Actions uses OIDC. No AWS access keys are stored anywhere.
- [ ] The VPC has public, private app and isolated data subnets in 2 AZs.
- [ ] Only the ALB is reachable from the internet, and it only accepts traffic from CloudFront.
- [ ] All OrderFlow services run on ECS Fargate and pass ALB health checks.
- [ ] A test order goes from `PENDING` to `CONFIRMED` on AWS.
- [ ] Invoice jobs go through SQS and Lambda, and a failing job ends up in the DLQ.
- [ ] WAF blocks a test attack request.
- [ ] CloudWatch alarms exist for 5xx rate, latency, RDS CPU and DLQ depth.
- [ ] The async module also exists in CDK, and you can explain the differences.
- [ ] `terraform destroy` removes everything, and you checked the console to confirm nothing is left.
- [ ] Measured evidence is collected (see the end of the [implementation plan](implementation-plan.md)).

## Files in this folder

| File | What it gives you |
|---|---|
| [architecture.md](architecture.md) | The AWS design: diagram, request path, async path, security layers, decisions |
| [concepts.md](concepts.md) | Simple explanations of every new AWS and Terraform idea |
| [references.md](references.md) | The official docs to read, and when |
| [implementation-plan.md](implementation-plan.md) | Milestones M0 to M9, step by step |
