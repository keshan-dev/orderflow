# Phase 5 Concepts

Simple explanations of every new idea in this phase. Each one says what it is and what goes wrong without it. For short definitions of other terms, see the [glossary](../common/04-glossary.md).

## 1. Infrastructure as Code and Terraform

| Concept | Simple meaning | What breaks without it |
|---|---|---|
| **Infrastructure as Code (IaC)** | You describe servers, networks and databases in text files. A tool reads the files and creates the real things. | People click in the console. Nobody knows exactly what exists or why, and you cannot rebuild it the same way. |
| **Provider** | A plugin that lets Terraform talk to 1 platform, for example the `aws` provider | Terraform would not know how to create anything in AWS |
| **Resource** | 1 real thing Terraform manages, for example 1 subnet or 1 S3 bucket | (the basic building block) |
| **Data source** | Reads something that already exists, without managing it, for example the CloudFront prefix list | You would hard-code ids that change between accounts and regions |
| **Module** | A folder of Terraform code you can reuse with different inputs, like a function | You copy and paste the same 40 lines for every service, and they slowly drift apart |
| **Variable** | An input to a module or environment, for example `env = "dev"` | Values are hard-coded and you cannot reuse code across environments |
| **Output** | A value a module gives back, for example the VPC id, so other modules can use it | Modules cannot pass information to each other |
| **State** | A file where Terraform remembers which real resources belong to which code | Terraform cannot tell what already exists, so it tries to create everything again |
| **Remote state** | State kept in S3 instead of your laptop | Your laptop breaks and the state is lost, or 2 people have different copies |
| **State locking** | Only 1 person or CI job can change the state at a time. With the S3 backend, `use_lockfile = true` writes a lock file next to the state. | 2 applies run together and corrupt the state |
| **Plan** | A preview of what Terraform will create, change or delete | You change production without knowing what will happen |
| **Apply** | Actually makes the changes from the plan | (the step that changes the real world) |
| **Drift** | The real resources no longer match the code, usually because someone changed something in the console | Your code lies about what is running. The next apply may undo someone's fix, or fail. |
| **Import** | Telling Terraform to take over a resource that was created outside Terraform | You must delete and recreate things to manage them with code |
| **Destroy** | Deletes everything in the state | Forgotten resources keep billing |

## 2. Regions and the network

| Concept | Simple meaning | What breaks without it |
|---|---|---|
| **Region** | A geographic area where AWS has data centers, for example `ap-south-1` | (every resource lives in 1 region) |
| **Availability Zone (AZ)** | 1 or more separate data centers inside a region, with their own power and network | If everything is in 1 AZ and that AZ fails, your whole system is down |
| **VPC** | Your own private network inside AWS | Your resources would have no private network boundary |
| **Subnet** | A slice of the VPC that lives in 1 AZ. Public, private or isolated depending on its routes. | You cannot separate public things from private things |
| **Route table** | Rules that say where traffic from a subnet can go | Traffic has no path, or every subnet can reach the internet |
| **Internet Gateway (IGW)** | The door between the VPC and the internet, used by public subnets | Nothing in the VPC can be reached from, or reach, the internet |
| **NAT gateway** | Lets private subnets call out to the internet, but blocks the internet from calling in | Private tasks cannot download anything or call external APIs, or you must make them public |
| **VPC endpoint** | A private door from your VPC to an AWS service like S3 or SQS. **Gateway** endpoints (S3) are free; **interface** endpoints (ECR, SQS, Secrets Manager, CloudWatch Logs) bill per hour. | All traffic to AWS services goes through the NAT gateway, which costs more and leaves the private network |
| **Security group** | A firewall around 1 resource. **Stateful**: if a request is allowed in, the reply is allowed out automatically. Rules can point at other security groups. | Any resource in the VPC can reach any other resource |
| **NACL (network ACL)** | A firewall around a whole subnet. **Stateless**: you must allow both directions. Has allow and deny rules. | No second safety net if a security group is too open |

**Security groups vs NACLs, in 1 line:** security groups protect each resource and are the main tool; NACLs protect a whole subnet and are a backup layer.

## 3. Identity and access

| Concept | Simple meaning | What breaks without it |
|---|---|---|
| **IAM policy** | A JSON document that lists what actions are allowed on which resources | (the rule itself) |
| **IAM role** | An identity that a service or person can take on for a short time. It has policies attached. | You use long-lived keys everywhere |
| **Least privilege** | Give each role only the permissions it really needs | 1 hacked service can read every bucket and delete every database |
| **Task role vs execution role** | ECS uses 2 roles. The **execution role** pulls the image and reads secrets at start. The **task role** is what your code uses while running. | Your code gets permissions it does not need, or the task cannot start |
| **OIDC federation** | GitHub proves to AWS "this is a job from repo X, branch Y". AWS gives it short-lived credentials for 1 role. | You store AWS access keys in GitHub secrets. If they leak, they work until someone notices. |
| **MFA** | A second login factor, like an authenticator app code | A stolen password is enough to take over the account |

## 4. Running containers

| Concept | Simple meaning | What breaks without it |
|---|---|---|
| **ECR** | AWS's private Docker image registry | ECS has nowhere private to pull your images from |
| **ECS cluster** | A logical group where your services run | (the container for everything else) |
| **Task definition** | The recipe for a container: image, CPU, memory, ports, environment variables, secrets, roles, log settings | ECS does not know how to run your container |
| **Task** | 1 running copy of a task definition | (the running container) |
| **ECS service** | Keeps the wanted number of tasks running, replaces failed ones and registers them with the load balancer | Crashed containers stay dead |
| **Fargate** | Runs your tasks without you managing any servers | You must create, patch and scale EC2 machines yourself |
| **Service Connect** | Gives services short names like `inventory-service` to call each other inside the VPC | Services need hard-coded IP addresses that change on every deploy |
| **Deployment circuit breaker** | If new tasks keep failing to start, ECS stops the deployment and rolls back | A broken release keeps trying forever and the service can go down |
| **Service autoscaling** | Changes the number of tasks based on CPU or request count | You pay for peak capacity all day, or fall over at peak time |

## 5. Load balancing and the edge

| Concept | Simple meaning | What breaks without it |
|---|---|---|
| **Application Load Balancer (ALB)** | Spreads HTTP requests over healthy tasks | 1 task takes all traffic, and a dead task still gets requests |
| **Listener** | The port and protocol the ALB listens on, for example HTTPS 443 | (the entry point) |
| **Listener rule** | "If path starts with `/api/orders`, send to order-service" | 1 load balancer per service |
| **Target group** | The set of tasks behind 1 rule, with a health check | The ALB does not know which tasks are healthy |
| **CloudFront** | AWS's CDN: a global network of edge servers in front of your app | Every request travels all the way to your region, and you have no edge place for WAF |
| **AWS WAF** | A web firewall that checks each request against rules | SQL injection and other common attacks reach your code |
| **Managed rule group** | A set of WAF rules written and kept up to date by AWS | You must write and maintain attack patterns yourself |
| **Rate-based rule** | Blocks an IP that sends more than a set number of requests in a time window | 1 client can flood the API |
| **CloudFront managed prefix list** | An AWS-maintained list of CloudFront IP ranges you can use in a security group | You cannot easily stop people from calling the ALB directly and skipping WAF |
| **ACM** | AWS Certificate Manager: free TLS certificates that renew themselves. For CloudFront, the certificate must be in `us-east-1`. | Manual certificates that expire and take the site down |

## 6. Data services

| Concept | Simple meaning | What breaks without it |
|---|---|---|
| **RDS** | Managed PostgreSQL: AWS does backups, patching and storage | You run, back up and patch the database yourself |
| **Multi-AZ** | RDS keeps a standby copy in another AZ and switches to it if the main one fails | An AZ failure takes your database down until you restore it |
| **Parameter group** | Database settings for RDS. Debezium needs `rds.logical_replication` turned on here. | Debezium cannot read the outbox tables |
| **ElastiCache** | Managed Redis-compatible cache. AWS offers both Redis OSS and Valkey engines. | You run and patch Redis yourself |
| **S3 encryption** | Objects are encrypted at rest. S3 does this by default; you can choose your own KMS key. | A copied disk or a leaked backup is readable |
| **S3 Block Public Access** | An account or bucket setting that stops any object from becoming public | 1 wrong policy makes invoices readable by anyone |
| **Bucket policy** | Rules on the bucket itself, for example "only this role can write" | Any role with S3 permissions can read your invoices |
| **Secrets Manager** | Stores passwords and keys, encrypted, with access logged. ECS injects them into tasks at start. | Passwords end up in code, images or Terraform files |

## 7. Async and serverless

| Concept | Simple meaning | What breaks without it |
|---|---|---|
| **SQS** | A managed message queue | You run a broker (RabbitMQ) yourself |
| **Visibility timeout** | When a consumer takes a message, SQS hides it for a while. If the consumer does not delete it in time, the message comes back for another try. | A crashed consumer loses the message, or 2 consumers work on it at once |
| **maxReceiveCount** | How many times a message can be received before it is moved to the DLQ | A broken message is retried forever |
| **DLQ (dead letter queue)** | A side queue for messages that failed too many times, so a person can inspect them | Poison messages block the queue or are lost |
| **Lambda** | Runs your function only when there is work. No server, billed per use. | You run a worker all day even when the queue is empty |
| **Event source mapping** | The link that makes Lambda read from an SQS queue automatically | You write and run your own polling loop |
| **Partial batch failure** | Lambda tells SQS which messages in a batch failed (`ReportBatchItemFailures`), so only those are retried | 1 bad message makes the whole batch retry, so good messages are processed twice |
| **S3 event notification** | S3 sends a message when an object is created or deleted | Other parts cannot react to new files without checking the bucket over and over |

## 8. Watching it on AWS

| Concept | Simple meaning | What breaks without it |
|---|---|---|
| **CloudWatch Logs** | Central place for logs from tasks and Lambdas | Logs disappear with the container |
| **Log retention** | How long logs are kept | Logs are kept forever and the bill grows |
| **Container Insights** | CPU, memory and task metrics for ECS | You cannot see which service is short on resources |
| **CloudWatch alarm** | Watches 1 metric and changes state when it crosses a limit | Problems are found by users, not by you |
| **AWS Budgets** | Sends an alert when spend goes over, or is forecast to go over, an amount you set | A forgotten resource bills for weeks before anyone notices |

## 9. AWS CDK

| Concept | Simple meaning | What breaks without it |
|---|---|---|
| **CDK** | Write AWS infrastructure in a real programming language (TypeScript here) | (alternative to Terraform) |
| **Construct** | A reusable building block in CDK, from 1 resource up to a whole pattern | You repeat the same setup for every resource |
| **Stack** | A group of constructs deployed together | (the deploy unit) |
| **Synth** | `cdk synth` turns your TypeScript into a CloudFormation template | (CDK does not call AWS directly; CloudFormation does the work) |
| **Bootstrap** | `cdk bootstrap` creates a few resources CDK needs in the account before the first deploy | Deploys fail |

**Terraform vs CDK, in short:**

| Point | Terraform | CDK |
|---|---|---|
| Language | HCL, a simple config language | TypeScript, Python and others |
| State | Your own state file (S3 here) | Kept by CloudFormation inside AWS |
| Clouds | Many providers, not just AWS | AWS only (through CloudFormation) |
| Drift | `terraform plan` shows it | CloudFormation drift detection |
| Logic | Limited loops and conditions | Full programming language |
| Preview | `terraform plan` | `cdk diff` |
