# Cost and Safety

Read this before Phase 2 (GitHub Actions) and again before Phase 5 (AWS). It explains what can cost money, what needs approval, and how to stay safe.

## 1. The main rule

**Write a budget before any paid dependency, service, API, trial or large credit spend.** This is the spend rule. If someone else pays (an employer, a client, a sponsor), get their written approval first. "Free tier" and "free trial" still count: a trial can turn into a bill, and free tier limits are easy to pass.

If you are not sure whether something costs money, treat it as paid and check first.

## 2. What costs money, phase by phase

| Phase | Runs on | Cost | Watch out for |
|---|---|---|---|
| 1 | Docker Compose on your machine | Free | Only your own electricity and disk |
| 2 | kind on your machine, GitHub | Free locally | GitHub Actions minutes and package storage on private repositories are limited, then billed. Check your plan's limits in GitHub's billing settings. Docker Desktop may need a paid subscription for some companies (see [dev environment](06-dev-environment.md)). |
| 3 | kind on your machine | Free | Nothing extra |
| 4 | kind on your machine or a local Ubuntu VM | Free | If you add an LLM API for threat summaries, it is paid per use. Ask first. |
| 5 | Real AWS | **Paid** | See section 3. Needs a written budget before you create anything. |

We do not write prices in these docs, because prices change and differ by region. Use the official **AWS Pricing Calculator** to estimate costs, and record the estimate in `PLAN.md`.

## 3. AWS things that cost money even when idle

Some AWS resources are billed **per hour while they exist**, even if no request ever reaches them. These are the usual causes of surprise bills:

| Resource | Why it costs while idle |
|---|---|
| **NAT gateway** | Billed per hour, plus per amount of data that passes through it |
| **Application Load Balancer** | Billed per hour, plus usage |
| **RDS (PostgreSQL)** | The database instance runs all the time, plus its storage and backups |
| **ElastiCache** | The cache nodes run all the time |
| **ECS Fargate tasks** | Billed for CPU and memory while each task runs |
| **Amazon OpenSearch Service** | The domain's instances run all the time |
| **Amazon MSK (managed Kafka)** | The brokers run all the time |
| **Amazon EKS** | The cluster control plane is billed per hour, plus the worker nodes |
| **Public IPv4 addresses** | AWS charges for public IPv4 addresses |
| **CloudWatch Logs** | Storage grows every day if you never set a retention period |

The Phase 5 docs choose a reduced setup to keep this small. For example, OpenSearch, MSK and EKS stay out of the AWS phase unless you budget for them.

## 4. Approval checkpoint (before Phase 5)

Do all of these before you create any AWS resource:

1. Finish and test the Terraform code locally (LocalStack, `terraform validate`, `terraform plan`).
2. Make a list of every resource that `terraform plan` will create.
3. Estimate the cost with the AWS Pricing Calculator. Note how many hours you expect it to run.
4. Write the list, the estimate and your plan to tear it down in the decision log in `PLAN.md`.
5. Set your spend limit and write it in the decision log in [`PLAN.md`](../../PLAN.md): date, the limit, and when everything will be destroyed.

## 5. Guard rails on the AWS account

- **AWS Budgets:** create a budget with an email alert at a low amount, set below your spend limit, before anything else.
- **Tags:** tag every resource with `project=orderflow` and `owner=<your name>` through Terraform's `default_tags`. Then you can find everything that belongs to OrderFlow.
- **1 region:** build everything in 1 region, so nothing hides in another one.
- **Log retention:** set a retention period on every CloudWatch log group.
- **Least privilege:** use an IAM identity with only the permissions Phase 5 needs. Never use the root account for daily work. Turn on 2 factor login.

## 6. The destroy routine

Run this at the end of **every** AWS session, not only at the end of the phase:

1. `terraform destroy` in each environment folder you applied, and read the list before you type `yes`.
2. Empty and remove any S3 buckets Terraform could not delete because they had objects (only buckets OrderFlow created).
3. In the AWS console, check these pages in your region for anything left: EC2 (load balancers, NAT gateways, Elastic IPs), ECS, RDS, ElastiCache, VPC, CloudWatch log groups.
4. Check the Billing page the next day to confirm the spend stopped.
5. Write in `PLAN.md` what ran, for how long, and that it was destroyed.

Keep the Terraform state bucket only if you plan to apply again soon. It costs very little, but it is still a resource; remove it at the end of the phase.

## 7. No real-world effects while testing

| Risk | How OrderFlow avoids it |
|---|---|
| Sending real emails | notification-worker sends only to **Mailpit**, a fake inbox on your machine. Never put a real SMTP server or email API in the config. |
| Taking real money | payment-service uses a **fake payment provider** that you control. No real payment API, no card numbers. |
| Using real customer data | Use made-up names, emails and addresses only. Never copy real customer data into OrderFlow. |
| Load tests hitting someone else | k6 and Chaos Mesh only target your own local cluster or your own AWS resources. Never point them at a system you do not own. |

## 8. Secrets

- **No secrets in the repository.** Not passwords, API keys, AWS keys or tokens, not even "just for testing".
- Use environment variables. Commit a `.env.example` with fake values. Add `.env` to `.gitignore`.
- In Kubernetes, use Secrets (and External Secrets if you connect a secrets manager). In AWS, use Secrets Manager.
- Turn on GitHub secret scanning and push protection for the repository.
- Do not put secrets in logs, Terraform outputs, or prompts sent to an LLM.

## 9. The eBPF agent is powerful

`runtime-sentinel` (Phase 4) needs high privileges to load programs into the kernel. It can see every process, file open and network connection on the machine.

- Run it **only on your own machine, your own VM or your own kind cluster.**
- Never run it on a shared or company server, or someone else's cluster.
- Do not store more than you need. The agent records file paths and IP addresses, not file contents or passwords.
- Keep the `security.events` data local and delete it when you are done (the `security-events-*` indices are deleted after 7 days).

## 10. If something goes wrong

Act on it **the same day**: revoke or rotate first, then write down what happened and what you changed.

| Problem | What to do right away |
|---|---|
| A secret was committed or pushed | Revoke or rotate the secret first (a new key, a new password). Removing it from Git is not enough, because it stays in history and may already be copied. Then report it. |
| An AWS key leaked | Deactivate the key in IAM immediately, check CloudTrail for unknown activity, report it. |
| AWS spend is higher than approved | Run the destroy routine, then report with the Billing page numbers. |
| A lost laptop or a strange login | Report it the same day and change your passwords. |
