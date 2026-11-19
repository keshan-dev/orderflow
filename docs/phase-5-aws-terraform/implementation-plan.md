# Phase 5 Implementation Plan

10 milestones, M0 to M9. Finish each one, test it, and only then start the next. Names and layout come from [architecture.md](architecture.md).

> **Cost rule for every session:** start with `terraform apply`, end with `terraform destroy`. Never leave the dev environment running overnight unless you planned and budgeted for it. See [The destroy routine](#the-destroy-routine) at the end.

---

## M0: AWS account safety and spend limit

**Goal:** a safe AWS account, a cost estimate, and written approval before anything that costs money is created.

**Tasks**
- [ ] Use a dedicated AWS account for this project, not one that runs anything else.
- [ ] Turn on MFA for the root user. Then stop using the root user for daily work.
- [ ] Create your own login through IAM Identity Center (preferred) or an IAM user, with MFA turned on.
- [ ] Install and configure the AWS CLI with that login. Check with `aws sts get-caller-identity`.
- [ ] Choose 1 region close to you that offers every service Phase 5 uses.
- [ ] Build a cost estimate for the dev environment in the **AWS Pricing Calculator**: NAT gateway, ALB, Fargate tasks, RDS, ElastiCache, interface VPC endpoints, public IPv4 addresses, CloudFront, WAF, CloudWatch. Use the calculator's numbers, not guesses.
- [ ] Create an **AWS Budgets** cost budget with email alerts at an amount below your spend limit.
- [ ] **Write the estimate, the spend limit and the teardown plan** in the decision log in [`PLAN.md`](../../PLAN.md): date, limit, and when it will be destroyed.

**How to test**
```bash
aws sts get-caller-identity          # shows your role, not root
aws budgets describe-budgets --account-id <account-id>
```

**Done when:** MFA is on, you never use root, the budget alert exists, and the budget and spend limit are in `PLAN.md`.

---

## M1: Terraform state bootstrap and CI checks

**Goal:** a safe place for Terraform state, and CI that checks every Terraform change.

**Tasks**
- [ ] Create `infra/terraform/bootstrap/`. It creates the state bucket with versioning, encryption and Block Public Access. It uses local state, because the bucket does not exist yet.
- [ ] Create `infra/terraform/envs/dev/backend.tf`:
  ```hcl
  terraform {
    backend "s3" {
      bucket       = "orderflow-tfstate-<account-id>"
      key          = "envs/dev/terraform.tfstate"
      region       = "<region>"
      encrypt      = true
      use_lockfile = true   # needs Terraform 1.10 or newer
    }
  }
  ```
- [ ] Set `default_tags` in the AWS provider: `Project = orderflow`, `Env = dev`, `Owner = <your role>`.
- [ ] Add `.terraform/`, `*.tfstate`, `*.tfstate.*` and any `*.auto.tfvars` with secrets to `.gitignore`.
- [ ] GitHub Actions workflow on pull requests: `terraform fmt -check`, `terraform init -backend=false`, `terraform validate`, and an IaC scan with Trivy config or Checkov.
- [ ] Create a GitHub environment called `aws-dev` with yourself as required reviewer. Apply jobs will use it in later milestones.

**How to test**
```bash
cd infra/terraform/bootstrap && terraform init && terraform apply
cd ../envs/dev && terraform init      # should say the S3 backend is configured
terraform plan                        # empty plan, no errors
```
Run 2 `terraform plan` commands at the same time from 2 terminals. 1 of them should report that the state is locked.

**Done when:** state is in S3, locking works, and a pull request with badly formatted Terraform fails CI.

---

## M2: Network

**Goal:** the 3-tier VPC from [architecture.md](architecture.md) section 2.

**Tasks**
- [ ] `modules/network`: VPC, 2 public, 2 private app and 2 isolated data subnets across 2 AZs.
- [ ] Internet Gateway, 1 NAT gateway in AZ A (dev only), route tables for each tier. Data subnets get no default route.
- [ ] NACLs on the data subnets: allow 5432 and 6379 in from the app subnet ranges, allow return traffic, deny the rest.
- [ ] VPC endpoints: S3 (gateway), ECR API, ECR Docker, Secrets Manager, SQS, CloudWatch Logs (interface). Attach `endpoints-sg`.
- [ ] Outputs: VPC id, subnet ids per tier, security group ids.
- [ ] Turn on VPC Flow Logs to CloudWatch, with short retention (optional, but useful for debugging).

**How to test**
```bash
terraform plan    # read every line before you apply
terraform apply
aws ec2 describe-subnets --filters Name=tag:Project,Values=orderflow \
  --query "Subnets[].{Name:Tags[?Key=='Name']|[0].Value,AZ:AvailabilityZone,CIDR:CidrBlock}"
aws ec2 describe-route-tables --filters Name=tag:Project,Values=orderflow
```
Check that the data subnet route table has only the local route.

**Done when:** 6 subnets exist in 2 AZs, routes match the table in the architecture doc, and `terraform plan` right after apply shows no changes.

---

## M3: ECR and image push from CI with OIDC

**Goal:** CI builds images and pushes them to ECR without any stored AWS keys.

**Tasks**
- [ ] `modules/ecs-cluster`: 1 ECR repository per service (`orderflow/order-service`, ...), with image scanning on push and a lifecycle policy that keeps only the last few images.
- [ ] IAM OIDC provider for `token.actions.githubusercontent.com`.
- [ ] IAM role `orderflow-github-ci` that trusts only your repository and the `main` branch. Permissions: push to these ECR repositories only.
- [ ] A separate role for Terraform plan and apply, also trusting only your repository, used only in the `aws-dev` environment.
- [ ] GitHub Actions job: `aws-actions/configure-aws-credentials` with `role-to-assume`, then build, tag with the Git commit SHA, push.

**How to test**
```bash
aws ecr describe-images --repository-name orderflow/order-service
```
Search the repository and GitHub secrets for `AKIA` (the start of AWS access key ids). There must be none.

**Done when:** a merge to `main` pushes all images to ECR, tagged with the commit SHA, and no AWS keys exist in GitHub.

---

## M4: ECS cluster, ALB and the first service

**Goal:** 1 service (inventory-service, because it only needs the database and cache later) running on Fargate behind the ALB. Use a temporary in-memory or health-only mode if the data tier is not ready yet.

**Tasks**
- [ ] ECS cluster with Container Insights turned on.
- [ ] ALB in the public subnets with `alb-sg`. For now allow your own IP only; CloudFront comes in M8.
- [ ] `modules/ecs-service`: task definition (CPU, memory, port, environment, secrets, log group with retention), execution role, task role, service in the private app subnets with `app-sg`, target group with `/readyz` health check, listener rule for its path.
- [ ] Deployment circuit breaker with rollback turned on.
- [ ] Service autoscaling on CPU, min 1, max a small number.
- [ ] ECS Service Connect namespace, so services can call each other by name later.

**How to test**
```bash
curl http://<alb-dns-name>/api/products
aws ecs describe-services --cluster orderflow-dev --services inventory-service \
  --query "services[0].{running:runningCount,desired:desiredCount,events:events[0:3]}"
```
Deploy an image that exits at start (for example a wrong command). Watch the circuit breaker roll back to the last good version.

**Done when:** the endpoint answers through the ALB, the target is healthy, and a broken deploy rolls back by itself.

---

## M5: Data tier

**Goal:** RDS, ElastiCache, the invoice bucket and secrets, reachable only from the app tier.

**Tasks**
- [ ] `modules/data`: RDS PostgreSQL in the isolated data subnets, single-AZ, encryption on, `db-sg` allows 5432 only from `app-sg`.
- [ ] Parameter group with `rds.logical_replication = 1` (Debezium needs it). This needs a reboot to take effect.
- [ ] Master password managed by RDS in Secrets Manager (`manage_master_user_password`), or generated and stored in Secrets Manager. Never in a `.tfvars` file.
- [ ] ElastiCache (Valkey or Redis OSS, write down which and why), encryption in transit and at rest, `cache-sg` allows 6379 only from `app-sg`.
- [ ] S3 bucket `orderflow-dev-invoices-<account-id>` with Block Public Access, default encryption, and a bucket policy that allows writes only from the invoice Lambda role (added in M7).
- [ ] A one-off ECS task (`aws ecs run-task`) that creates `orders_db`, `inventory_db`, `payments_db`, the Debezium user with the `rds_replication` role, and runs the Alembic migrations.
- [ ] dev only: `skip_final_snapshot = true`, `deletion_protection = false`, `force_destroy = true`.

**How to test**
- Run the one-off migration task and read its CloudWatch logs.
- From your laptop, try to connect to the RDS endpoint on 5432. It must fail (no route).
- inventory-service on ECS reads products from RDS and caches them in ElastiCache. Call `/api/products` twice and check the cache hit in the logs.

**Done when:** services use RDS and ElastiCache, the databases are not reachable from outside, and no password appears in Terraform files, Git or task definition plain-text environment variables.

---

## M6: All services and the Kafka demo broker

**Goal:** the full saga works on AWS.

**Tasks**
- [ ] Use `modules/ecs-service` for order-service, payment-service and search-indexer (search-indexer with `desired_count = 0`, since OpenSearch is off).
- [ ] `kafka` task: 1 broker in KRaft mode, reachable by its Service Connect name. Advertised listeners must use that name.
- [ ] `kafka-connect` task with the Debezium connector configs from Phase 1, pointed at RDS.
- [ ] A one-off task that creates the topics from the [main architecture](../common/02-architecture.md), and registers the Debezium connectors.
- [ ] Listener rules for `/api/orders*` and `/api/products*`.
- [ ] Write the **known gap** in `PLAN.md`: 1 broker, no replication, data lost on task restart. Production answer: Amazon MSK.

**How to test**
```bash
curl -X POST http://<alb-dns-name>/api/orders \
  -H "Content-Type: application/json" -H "Idempotency-Key: test-001" \
  -d '{"items":[{"product_id":"<id>","quantity":1}]}'
curl http://<alb-dns-name>/api/orders/<order-id>    # repeat until CONFIRMED
```
Set the fake payment provider to fail and place another order. It must end `CANCELLED` and the stock must come back.

**Done when:** 1 order reaches `CONFIRMED` and 1 failing order reaches `CANCELLED` with stock released, both on AWS.

---

## M7: Async with SQS and Lambda (LocalStack first)

**Goal:** RabbitMQ jobs replaced by SQS + Lambda, tested for free on LocalStack before real AWS.

**Tasks**
- [ ] `modules/async`: the 2 queues and 2 DLQs from [architecture.md](architecture.md) section 4, redrive policy with `maxReceiveCount`, encryption on.
- [ ] Visibility timeout longer than the Lambda timeout (the SQS docs explain why).
- [ ] `invoice-generator` Lambda (Python): builds the PDF, writes to S3, returns failed message ids with `ReportBatchItemFailures`.
- [ ] `email-sender` Lambda (Python): writes the email content to its logs only. No real email.
- [ ] Event source mappings with partial batch responses turned on.
- [ ] order-service: add the SQS implementation of the job publisher, chosen by `JOB_BACKEND=sqs`. Its task role may only send to these 2 queues.
- [ ] Run the module against **LocalStack** first, using a provider block that points to the LocalStack endpoint.
- [ ] Then apply on AWS.
- [ ] Optional: S3 event notification on the `invoices/` prefix to a third queue.

**How to test**
```bash
# LocalStack (awslocal is the LocalStack wrapper for the AWS CLI)
awslocal sqs send-message --queue-url <invoices-queue-url> --message-body '{"order_id":"<id>"}'
awslocal s3 ls s3://orderflow-dev-invoices-<account-id>/invoices/ --recursive

# AWS: send a message that always fails (for example an unknown order id)
aws sqs get-queue-attributes --queue-url <invoices-dlq-url> \
  --attribute-names ApproximateNumberOfMessages
```

**Done when:** a confirmed order produces a PDF in S3 and an email in the Lambda logs, and a bad message ends up in the DLQ after the set number of tries, without blocking the good ones.

---

## M8: CloudFront, WAF and alarms

**Goal:** the edge security layer and alarms that tell you when something is wrong.

**Tasks**
- [ ] `modules/edge`: CloudFront distribution with the ALB as origin, caching turned off for `/api/*`, a custom secret header added to origin requests.
- [ ] Certificates: if there is a domain, ACM in `us-east-1` for CloudFront and in your region for the ALB. If not, use the CloudFront default domain and HTTP from CloudFront to the ALB, and record the gap (see architecture section 7).
- [ ] ALB: change `alb-sg` to allow only the CloudFront managed prefix list. Add a listener rule that returns 403 when the secret header is missing. Store the header value in Secrets Manager, not in code.
- [ ] WAF web ACL (scope `CLOUDFRONT`, created in `us-east-1`): AWS managed rule groups for common rules, SQL injection and known bad inputs, plus 1 rate-based rule.
- [ ] CloudWatch alarms: ALB 5xx rate, ALB target response time, RDS CPU, DLQ depth greater than 0, running task count below desired. Send them to an SNS topic with your email.

**How to test**
```bash
# Normal request through CloudFront: expect 200
curl -i https://<distribution>.cloudfront.net/api/products

# SQL injection pattern in a query parameter: expect 403 from WAF
curl -i "https://<distribution>.cloudfront.net/api/products?id=1%27%20OR%20%271%27%3D%271"

# Direct call to the ALB: expect a timeout or 403
curl -i --max-time 10 http://<alb-dns-name>/api/products
```
To test an alarm, send a bad message to the invoices queue and wait for the DLQ alarm email. Keep any rate-limit test small, with a short loop from your own machine only.

**Done when:** normal traffic works through CloudFront, the attack pattern is blocked, the ALB cannot be reached directly, and at least 1 alarm has fired and reached your email.

---

## M9: CDK rebuild and the full destroy and recreate test

**Goal:** compare Terraform and CDK, and prove the whole environment can be built and removed from code.

**Tasks**
- [ ] `infra/cdk/`: a CDK TypeScript app with 1 stack that builds the async module (2 queues, 2 DLQs, 2 Lambdas, event sources, S3 bucket). Use different names (for example a `-cdk` suffix) so it does not clash with the Terraform version.
- [ ] `cdk bootstrap`, `cdk synth`, read the generated CloudFormation template, `cdk diff`, `cdk deploy`, run the same tests as M7, then `cdk destroy`.
- [ ] Write a short comparison in the phase notes: lines of code, how state is kept, how drift is shown, what was easier or harder.
- [ ] Full test: `terraform destroy`, check nothing is left, then `terraform apply` from scratch. Time both.

**How to test**
```bash
cd infra/cdk && npx cdk synth && npx cdk diff && npx cdk deploy
npx cdk destroy

cd infra/terraform/envs/dev
time terraform destroy
time terraform apply
```

**Done when:** the CDK stack works and is removed, and the full environment can be destroyed and rebuilt from code with no manual console steps.

---

## The destroy routine

Run this at the end of **every** session:

1. `cd infra/terraform/envs/dev && terraform destroy`. Read the plan, type `yes`.
2. If you used CDK that day: `npx cdk destroy`.
3. Check that nothing tagged with the project is left:
   ```bash
   aws resourcegroupstaggingapi get-resources --tag-filters Key=Project,Values=orderflow
   ```
   Recently deleted resources can still appear for a short time. Check again if needed.
4. Check the console for the usual leftovers: NAT gateways, Elastic IPs, load balancers, RDS instances and snapshots, ElastiCache clusters, VPC endpoints, CloudFront distributions (they take a while to disable and delete).
5. The state bucket from `bootstrap/` stays. Delete it only at the very end of the phase.
6. The next day, check AWS Cost Explorer and the budget page.

If `terraform destroy` fails, do not delete things by hand first. Read the error, fix the cause (often a non-empty bucket or a dependency), and run destroy again, so the state stays correct.

---

## The showcase

A 3 to 5 minute demo for an interviewer or reviewer:

1. Show the Terraform code layout and 1 pull request with a plan comment and the manual approval step.
2. `terraform apply` builds the whole environment from nothing.
3. Place an order through CloudFront. Show it reach `CONFIRMED`, and the invoice PDF appear in S3.
4. Send the SQL injection test request. Show the 403 and the blocked request in the WAF metrics.
5. Try the ALB directly. Show that it is refused.
6. `terraform destroy` removes everything. Show the empty tagged-resource list.

## Evidence to collect

Only write down things you actually measured or saw:

- [ ] Time for a full `terraform apply` from nothing, and for a full `terraform destroy`.
- [ ] Number of AWS resources Terraform manages (`terraform state list | wc -l`).
- [ ] Screenshot of the WAF blocking the test request.
- [ ] Screenshot of the circuit breaker rolling back a broken deploy.
- [ ] Screenshot of the DLQ alarm email.
- [ ] Actual cost for the phase from Cost Explorer, compared with the Pricing Calculator estimate.
- [ ] The Terraform vs CDK comparison notes.
- [ ] Known gaps, written honestly: 1 Kafka broker instead of MSK, single-AZ RDS, 1 NAT gateway, OpenSearch off, and HTTP between CloudFront and the ALB if no domain was used.
