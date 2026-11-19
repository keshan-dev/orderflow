# Phase 5 References

Official docs only. Do not read everything at the start. The "When" column tells you which milestone in the [implementation plan](implementation-plan.md) each doc is for.

## Terraform

| Doc | What it includes | Sections to read | When |
|---|---|---|---|
| **HashiCorp Developer: Terraform tutorials** | Guided, hands-on tutorials | "Get Started: AWS", then the modules and state tutorials | Before M1 |
| **Terraform language docs** | The full reference for writing Terraform | Resources, Variables, Outputs, Modules, State, Backends (the `s3` backend page, including `use_lockfile`), `import` blocks | M1, M2, then as needed |
| **Terraform Registry: AWS provider docs** | 1 page per AWS resource, with all arguments and examples | Look up each resource as you write it (`aws_vpc`, `aws_ecs_service`, `aws_db_instance`, ...) | Every milestone |
| **terraform-aws-modules** (on the Terraform Registry, `vpc` and `ecs` modules) | Widely used community modules | Read their code to learn good patterns. Write your own modules first, so you actually learn. | M2, M4 |

## AWS architecture and safety

| Doc | What it includes | Sections to read | When |
|---|---|---|---|
| **AWS Well-Architected Framework** | How AWS recommends designing systems | Security pillar, Reliability pillar, Cost Optimization pillar | Before M0, then again before the showcase |
| **AWS Pricing Calculator** | Estimates the cost of a set of resources | Build an estimate for the dev environment and record it in `PLAN.md` | M0 |
| **AWS Budgets docs** | Spend alerts | Creating a cost budget with email alerts | M0 |
| **IAM User Guide** | Users, roles, policies, MFA | Security best practices, roles, MFA | M0 |

## Network

| Doc | What it includes | Sections to read | When |
|---|---|---|---|
| **Amazon VPC User Guide** | Everything about AWS networking | Subnets, route tables, Internet Gateways, NAT gateways, security groups, network ACLs, VPC endpoints (AWS PrivateLink), gateway endpoints for S3 | M2 |

## Containers and load balancing

| Doc | What it includes | Sections to read | When |
|---|---|---|---|
| **Amazon ECR User Guide** | Private image registry | Repositories, pushing images, lifecycle policies | M3 |
| **Amazon ECS Developer Guide** | Running containers on AWS | Fargate, task definitions, task IAM role and execution role, services, Service Connect, deployment circuit breaker, service autoscaling, passing secrets to containers | M4, M6 |
| **Elastic Load Balancing: Application Load Balancers guide** | The ALB | Listeners, listener rules, target groups, health checks | M4 |

## Data

| Doc | What it includes | Sections to read | When |
|---|---|---|---|
| **Amazon RDS User Guide** | Managed databases | RDS for PostgreSQL, parameter groups, Multi-AZ, backups, encryption, logical replication | M5 |
| **Amazon ElastiCache User Guide** | Managed cache | Choosing Valkey or Redis OSS, subnet groups, encryption in transit | M5 |
| **Amazon S3 User Guide** | Object storage | Block Public Access, default encryption, bucket policies, event notifications | M5, M7 |
| **AWS Secrets Manager User Guide** | Storing secrets | Creating secrets, IAM access, using secrets with ECS | M5 |

## Async and serverless

| Doc | What it includes | Sections to read | When |
|---|---|---|---|
| **Amazon SQS Developer Guide** | Message queues | Visibility timeout, dead-letter queues, redrive policy, message naming rules | M7 |
| **AWS Lambda Developer Guide** | Serverless functions | Using Lambda with Amazon SQS, event source mappings, reporting batch item failures, Lambda with S3 | M7 |
| **LocalStack docs** | Running AWS services locally | Getting started, using Terraform with LocalStack, SQS, Lambda, S3 | M7 (before real AWS) |

## Edge, security and monitoring

| Doc | What it includes | Sections to read | When |
|---|---|---|---|
| **Amazon CloudFront Developer Guide** | The CDN | Distributions, origins, cache behaviors, restricting access to ALB origins, custom headers, VPC origins | M8 |
| **AWS WAF Developer Guide** | Web firewall | Web ACLs, AWS managed rule groups, rate-based rules, testing rules | M8 |
| **AWS Certificate Manager User Guide** | TLS certificates | DNS validation, certificate regions for CloudFront | M8 |
| **Amazon CloudWatch User Guide** | Metrics, logs and alarms | Creating alarms, Container Insights, log group retention | M8 |

## CI

| Doc | What it includes | Sections to read | When |
|---|---|---|---|
| **GitHub Docs: Configuring OpenID Connect in Amazon Web Services** | Letting GitHub Actions use AWS without stored keys | The whole page, especially how to limit the trust policy to 1 repo and branch | M3 |
| **aws-actions/configure-aws-credentials** (GitHub README) | The GitHub Action that gets AWS credentials through OIDC | Usage with `role-to-assume` | M3 |
| **GitHub Docs: Using environments for deployment** | Manual approval before a job runs | Required reviewers | M1 |
| **Trivy docs** (misconfiguration scanning) or **Checkov docs** | Scanning Terraform for unsafe settings | Scanning Terraform, running in CI | M1 |

## CDK

| Doc | What it includes | Sections to read | When |
|---|---|---|---|
| **AWS CDK Developer Guide (v2)** | Writing infrastructure in TypeScript | Getting started, constructs, stacks, `cdk bootstrap`, `cdk synth`, `cdk diff`, `cdk deploy`, `cdk destroy` | M9 |
| **AWS CDK API Reference** | Every construct and its properties | `aws-sqs`, `aws-lambda`, `aws-lambda-event-sources`, `aws-s3` | M9 |

## Reading order

1. **Before M0:** Well-Architected (Security and Cost pillars), Pricing Calculator, Budgets, IAM best practices.
2. **Before M1:** the Terraform "Get Started: AWS" tutorials and the S3 backend page.
3. **M2 to M8:** read each AWS guide when you reach its milestone, and keep the Terraform Registry page for each resource open while you write it.
4. **M9:** the CDK Developer Guide.
