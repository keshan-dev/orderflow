# Phase 5 Architecture: OrderFlow on AWS

This doc shows how OrderFlow runs on AWS. Names of services, topics and tables come from the [main architecture](../common/02-architecture.md). Only the places where AWS changes things are described here.

## 1. The AWS layout

1 AWS account, 1 region (chosen in M0), 1 environment (`dev`). The VPC spans 2 Availability Zones (AZ A and AZ B).

```
                               Internet
                                  |
                       +----------v-----------+
                       |      CloudFront      |  HTTPS, caching off for /api/*
                       |   + AWS WAF (web ACL)|  managed rules + rate limit
                       +----------+-----------+
                                  | only CloudFront can reach the ALB
+---------------------------------|----------------------------------------+
| VPC                             |                                        |
|                                 |                                        |
|  PUBLIC SUBNETS   +-------------v--------------+       +-------------+   |
|  (AZ A, AZ B)     | Application Load Balancer  |       | NAT gateway |   |
|                   +-------------+--------------+       | (1, in AZ A)|   |
|                                 | path routing          +------^------+  |
|  ------------------------------ | ---------------------------- | -----   |
|  PRIVATE APP SUBNETS            v                              |         |
|  (AZ A, AZ B)     +-------------+-------------+    outbound only|        |
|                   | ECS cluster on Fargate    |  ---------------+        |
|                   |  order-service            |                          |
|                   |  inventory-service        |   VPC endpoints:         |
|                   |  payment-service          |   S3 (gateway), ECR,     |
|                   |  search-indexer (off)     |   Secrets Manager, SQS,  |
|                   |  kafka (1 broker, demo)   |   CloudWatch Logs        |
|                   |  kafka-connect (Debezium) |                          |
|                   +-----+---------------+-----+                          |
|  ---------------------- | ------------- | ------------------------------ |
|  ISOLATED DATA SUBNETS  v               v      (no route to internet)    |
|  (AZ A, AZ B)     +-----------+   +-------------+                        |
|                   |    RDS    |   | ElastiCache |                        |
|                   | PostgreSQL|   | Redis/Valkey|                        |
|                   +-----------+   +-------------+                        |
+--------------------------------------------------------------------------+

  Outside the VPC (regional AWS services, reached through VPC endpoints):
    S3 bucket for invoices      SQS queues + DLQs      Lambda functions
    ECR repositories            Secrets Manager        CloudWatch Logs, alarms
```

## 2. Subnet tiers

| Tier | What lives there | Route to internet | Why |
|---|---|---|---|
| Public | ALB, NAT gateway | Yes, through the Internet Gateway | Only things that must be reached from outside live here |
| Private app | ECS tasks | Outbound only, through the NAT gateway | Tasks can pull updates and call AWS, but nobody can connect to them from the internet |
| Isolated data | RDS, ElastiCache | None | Databases never talk to the internet, in either direction |

Each tier has 1 subnet in AZ A and 1 in AZ B, so 6 subnets in total.

## 3. The request path

What happens when a customer calls `POST /api/orders`:

1. The request reaches **CloudFront** over HTTPS.
2. **AWS WAF** checks it. Known attack patterns (for example SQL injection) and clients that send too many requests are blocked here.
3. CloudFront forwards it to the **ALB**. It adds a secret header, and the ALB only accepts traffic from the CloudFront IP ranges (the AWS managed prefix list for CloudFront). Anyone who finds the ALB address and calls it directly is rejected.
4. The **ALB listener rule** looks at the path. `/api/orders*` goes to the order-service target group, `/api/products*` to inventory-service.
5. The ALB sends the request to a healthy **order-service task** on Fargate. Tasks that fail the health check (`/readyz`) get no traffic.
6. order-service reads the database password from **Secrets Manager** (injected when the task starts), writes the order and the outbox row to **RDS**, and checks the idempotency key in **ElastiCache**.
7. **kafka-connect** (Debezium) reads the outbox through logical replication and publishes to the demo **Kafka** broker. The saga continues exactly as in Phase 1.

Services find each other inside the VPC through **ECS Service Connect** (short DNS names like `inventory-service`), not through the ALB.

## 4. The async path

RabbitMQ and notification-worker are replaced by SQS and Lambda. Note that SQS queue names cannot contain dots, so the names change.

| Local queue | AWS queue | AWS DLQ | Lambda |
|---|---|---|---|
| `notifications.email` | `orderflow-dev-notifications-email` | `orderflow-dev-notifications-email-dlq` | `orderflow-dev-email-sender` |
| `invoices.generate` | `orderflow-dev-invoices-generate` | `orderflow-dev-invoices-generate-dlq` | `orderflow-dev-invoice-generator` |

```
order-service --(send job)--> SQS queue --(event source mapping)--> Lambda
                                  |                                   |
                         fails N times                          invoice-generator
                                  v                             writes the PDF
                              SQS DLQ  --> CloudWatch alarm      to S3
```

- order-service uses a small "job publisher" interface. It sends to RabbitMQ when `JOB_BACKEND=rabbitmq` and to SQS when `JOB_BACKEND=sqs`. The rest of the code does not change.
- Lambda reports **partial batch failures**. If 1 message in a batch of 10 fails, only that 1 is retried.
- After the configured number of failed tries (`maxReceiveCount`), SQS moves the message to the DLQ.
- **email-sender does not send real emails.** It writes the email content to its logs. Sending real email needs SES and a budget decision.
- Invoice bucket: S3 bucket names are global, so the bucket is named `orderflow-dev-invoices-<account-id>`. The key layout stays `invoices/{yyyy}/{mm}/{order_id}.pdf`.
- Optional extension: an S3 event notification on the `invoices/` prefix that sends "invoice created" messages to another SQS queue. This shows the S3 to SQS to Lambda pattern from end to end.

## 5. Security layers (defense in depth)

No single layer has to be perfect, because an attacker must get past all of them.

| Layer | Control | What it stops |
|---|---|---|
| Edge | CloudFront + WAF managed rule groups (common rules, SQL injection, known bad inputs) | Common web attacks before they reach your code |
| Edge | WAF rate-based rule | 1 client flooding the API |
| Transport | HTTPS with ACM certificates | Reading or changing traffic on the way |
| Load balancer | ALB security group allows only the CloudFront managed prefix list, plus a secret header check | Bypassing CloudFront and WAF by calling the ALB directly |
| Network | 3 subnet tiers, data subnets with no internet route | Databases being reachable from the internet |
| Network | Security groups by role: ALB to app, app to data | A compromised component reaching things it should not |
| Network | NACLs on the data subnets | A wrong security group rule opening the databases |
| Identity | 1 IAM task role per service, least privilege | 1 hacked service using another service's permissions |
| Secrets | Secrets Manager, never in code, images or Terraform variables files | Leaked passwords in Git or Docker images |
| Data | Encryption at rest for RDS, ElastiCache, S3, SQS; S3 Block Public Access | Data exposed through a disk copy or a public bucket |
| CI | GitHub OIDC role limited to this repository and branch | Stolen long-lived AWS keys |
| Audit | CloudWatch logs and alarms | Problems going unnoticed |

Security group rules:

| Security group | Inbound allowed from | Port |
|---|---|---|
| `alb-sg` | CloudFront managed prefix list | 443 (or 80 if no custom domain, see section 7) |
| `app-sg` | `alb-sg`, and `app-sg` itself (service to service, Kafka) | service ports 8001 to 8003, 9092, 8083 |
| `db-sg` | `app-sg` only | 5432 |
| `cache-sg` | `app-sg` only | 6379 |
| `endpoints-sg` | `app-sg` only | 443 |

## 6. Terraform layout

```
infra/terraform/
  bootstrap/            creates the state bucket (uses local state, run once)
  modules/
    network/            VPC, 6 subnets, IGW, NAT, route tables, NACLs, VPC endpoints
    ecs-cluster/        ECS cluster, ECR repositories, Container Insights, log groups
    ecs-service/        1 reusable module: task definition, service, target group,
                        listener rule, IAM roles, autoscaling (used once per service)
    data/               RDS, ElastiCache, S3 invoice bucket, Secrets Manager secrets
    edge/               CloudFront distribution, WAF web ACL, ACM certificate
    async/              SQS queues, DLQs, Lambda functions, event source mappings
  envs/
    dev/                main.tf (calls the modules), backend.tf, variables.tf,
                        terraform.tfvars (no secrets), outputs.tf
```

- **State:** S3 backend with `use_lockfile = true` (needs Terraform 1.10 or newer). DynamoDB locking is deprecated, so it is not used. Each environment has its own state file key.
- **Tags:** every resource gets `Project = orderflow`, `Env = dev`, `Owner = <your role>`, through the provider's `default_tags`. This makes cost tracking and cleanup easy.
- **Dev only settings**, so `terraform destroy` works cleanly: `skip_final_snapshot = true` on RDS, `force_destroy = true` on the S3 bucket, `force_delete = true` on ECR, deletion protection off. These must never be copied to a production environment.

## 7. Domain and certificates

- **CloudFront certificates must be in `us-east-1`**, no matter which region the rest of the system uses. The ALB certificate must be in the ALB's own region.
- **If there is no domain:** use the CloudFront default domain (`xxxx.cloudfront.net`), which already has HTTPS. CloudFront then talks to the ALB over HTTP on port 80, and the ALB only accepts the CloudFront prefix list plus the secret header. Write this down as a known gap: traffic between CloudFront and the ALB is not encrypted in this setup.
- **If you own a domain**: request ACM certificates in both regions, validate them with DNS, and use HTTPS all the way to the ALB.

## 8. Observability on AWS

| What | How |
|---|---|
| Logs | Each ECS task and Lambda writes to its own CloudWatch log group, with a set retention period |
| Container metrics | ECS Container Insights |
| Alarms | ALB 5xx rate, ALB target response time, RDS CPU, SQS DLQ depth greater than 0, ECS running task count |
| Traces (optional) | Send OpenTelemetry data to the Phase 2 stack, or to AWS X-Ray through the AWS Distro for OpenTelemetry collector |

## 9. Local tool to AWS service

| Local tool | AWS service | Notes |
|---|---|---|
| nginx / Gateway API | Application Load Balancer | Path routing and health checks |
| (none) | CloudFront + WAF | New edge layer |
| Docker Compose / kind | ECS on Fargate | No servers to manage |
| Local image build | ECR | Images pushed by CI |
| PostgreSQL container | RDS PostgreSQL | Logical replication turned on for Debezium |
| Redis container | ElastiCache (Redis OSS or Valkey) | Both engines are offered by AWS |
| MinIO | S3 | Same S3 API, so the code barely changes |
| RabbitMQ | SQS | Different API, hidden behind the job publisher interface |
| notification-worker | Lambda | Runs only when there are messages |
| Kafka (kind) | 1 Kafka broker task on ECS (demo) | Production answer: Amazon MSK |
| Kafka Connect + Debezium | kafka-connect task on ECS | Same connector configs as Phase 1 |
| OpenSearch | Off in dev | Optional Amazon OpenSearch Service domain with approval |
| `.env` file | Secrets Manager | Injected into tasks at start |
| Prometheus + Grafana + Loki | CloudWatch | Or forward to the Phase 2 stack |
| GitHub Actions secrets | GitHub OIDC + IAM role | No stored keys |

## 10. Key decisions

| Decision | Why | What we gave up |
|---|---|---|
| Terraform for everything, CDK for 1 module only | Terraform is in the target stack. CDK is used enough to compare, not to maintain 2 copies. | The CDK copy is not deployed long term |
| 1 NAT gateway in dev | Each NAT gateway is billed per hour, so 1 instead of 2 cuts cost | If AZ A fails, tasks in AZ B lose outbound internet. Production uses 1 NAT per AZ. |
| VPC endpoints for S3, ECR, Secrets Manager, SQS, CloudWatch Logs | Traffic to AWS services stays inside AWS and does not go through the NAT | Interface endpoints are billed per hour per AZ too. Check the Pricing Calculator and keep only the ones you need. |
| Isolated data subnets | Databases have no internet route at all | Database maintenance must go through a task inside the VPC |
| RDS single-AZ in dev | Lower cost | No automatic failover. Production uses Multi-AZ. |
| SQS + Lambda instead of RabbitMQ | Managed, pay per use, no broker to run, and you learn serverless | Different API from RabbitMQ; needs the job publisher interface |
| 1 Kafka broker task on ECS | Shows the full saga working on AWS at low cost | **Known gap:** no replication, data lost if the task restarts, not production-ready. The production answer is Amazon MSK. |
| OpenSearch off in dev | An OpenSearch domain bills per hour even when idle | Search does not work on AWS unless you budget for a small domain |
| CloudFront in front of a public ALB | Simple and common, and WAF sits at the edge | ALB has a public address. Locked down with the prefix list and secret header. CloudFront VPC origins can make the ALB fully private; worth reading about as a next step. |
| ECS deployment circuit breaker with rollback | A broken release rolls back by itself | A slow first start can be mistaken for a failure; tune health check grace periods |
| GitHub OIDC instead of access keys | No secret to leak or rotate | The IAM trust policy must be scoped carefully to this repo and branch |
| Destroy after every session | Nothing bills while you are not working | Each session starts with an apply that takes time |
