# AWS Deployment Guide for the OpenAI Image Generator POC

This guide shows how to deploy this project to AWS in a way that feels close to a real production system while still being simple enough for students to follow.

It covers these services:

- `ALB` for frontend and API routing
- `Route 53` for DNS
- `ACM` for HTTPS certificates
- `CloudWatch` for logs, metrics, and alarms
- `Secrets Manager` for application secrets
- `SQS DLQ` for failed background jobs
- `Auto Scaling` for ECS services

It also assumes the existing architecture in this repo:

- `frontend` React app served by Nginx
- `backend` FastAPI API
- `worker` Python worker consuming SQS messages
- `RDS PostgreSQL` for metadata
- `S3` for generated images
- `SQS FIFO` for async image jobs
- `ECR` for container images
- `ECS Fargate` for running containers

## 1. Final Architecture

The student-facing architecture should look like this:

```text
User
  |
Route 53
  |
ACM certificate
  |
Application Load Balancer
  |-----------------------------|
  |                             |
Frontend ECS Service        Backend ECS Service
                                  |
                                  |--> RDS PostgreSQL
                                  |--> SQS FIFO Queue
                                             |
                                             v
                                    Worker ECS Service
                                      |--> OpenAI Images API
                                      |--> S3 Bucket
                                      |--> CloudWatch Logs

Main Queue ---> Dead Letter Queue
```

## 2. Deployment Order

Use this order so students see the system build up logically:

1. Create networking and security groups
2. Create S3 bucket
3. Create SQS FIFO queue and DLQ
4. Create RDS database
5. Create Secrets Manager secrets
6. Create ECR repositories
7. Build and push Docker images
8. Create ECS cluster and task definitions
9. Create ALB and target groups
10. Create ECS services
11. Attach ACM certificate and HTTPS listener
12. Configure Route 53 DNS
13. Add CloudWatch dashboards and alarms
14. Configure ECS auto scaling

## 3. Prepare AWS Foundations

### 3.1 Create a VPC layout

For a complete learning setup, use:

- `2 public subnets` for the ALB
- `2 private subnets` for ECS tasks and RDS
- `Internet Gateway` for public traffic
- `NAT Gateway` if private ECS tasks need outbound internet access

Why this matters:

- The `ALB` should be public
- The `backend`, `worker`, and `database` should ideally stay private
- Students get to see a standard AWS network design

### 3.2 Create security groups

Recommended security groups:

- `alb-sg`
  - allow inbound `80` and `443` from the internet
  - allow outbound to ECS task security groups
- `frontend-sg`
  - allow inbound from `alb-sg` on container port `80`
- `backend-sg`
  - allow inbound from `alb-sg` on container port `8000`
- `db-sg`
  - allow inbound from `backend-sg` and `worker-sg` on `5432`
- `worker-sg`
  - no public inbound required

## 4. Create Core Data Services

### 4.1 Create the S3 bucket

Use the bucket for generated images.

Suggested settings:

- block public access
- enable server-side encryption
- enable versioning if you want to teach safe object retention

Example:

```bash
aws s3api create-bucket \
  --bucket your-image-generation-bucket \
  --region ap-south-1 \
  --create-bucket-configuration LocationConstraint=ap-south-1
```

### 4.2 Create the SQS FIFO queue and DLQ

Create two queues:

- main queue: `image-generation.fifo`
- dead-letter queue: `image-generation-dlq.fifo`

Example DLQ creation:

```bash
aws sqs create-queue \
  --queue-name image-generation-dlq.fifo \
  --attributes FifoQueue=true,ContentBasedDeduplication=false
```

Get the DLQ ARN, then create the main queue with a redrive policy:

```bash
aws sqs create-queue \
  --queue-name image-generation.fifo \
  --attributes FifoQueue=true,ContentBasedDeduplication=false,VisibilityTimeout=180,RedrivePolicy='{"deadLetterTargetArn":"DLQ_ARN_HERE","maxReceiveCount":"3"}'
```

Why this matters:

- jobs that repeatedly fail are preserved for inspection
- students learn how resilient async systems are built

### 4.3 Create the RDS PostgreSQL database

Use PostgreSQL for user and job metadata.

Recommended student setup:

- `PostgreSQL`
- `db.t3.micro` or similar small instance
- private subnets
- security group allowing only ECS task access

Store the connection string in `Secrets Manager` rather than hardcoding it in ECS task definitions.

## 5. Store Secrets in Secrets Manager

Create secrets for:

- `OPENAI_API_KEY`
- `DATABASE_URL`

Optional:

- separate DB username/password secret
- environment-specific secrets for dev, staging, and prod

Example:

```bash
aws secretsmanager create-secret \
  --name openai-image-app/openai-api-key \
  --secret-string "sk-your-key"
```

```bash
aws secretsmanager create-secret \
  --name openai-image-app/database-url \
  --secret-string "postgresql+psycopg2://user:password@host:5432/dbname"
```

In ECS task definitions, inject these secrets as environment variables instead of placing them in plain text.

Why this matters:

- students see secure secret handling
- ECS tasks fetch secrets dynamically at runtime

## 6. Create ECR Repositories

Create one repository per image:

- `image-frontend`
- `image-api`
- `image-worker`

Example:

```bash
aws ecr create-repository --repository-name image-frontend
aws ecr create-repository --repository-name image-api
aws ecr create-repository --repository-name image-worker
```

Then authenticate Docker to ECR:

```bash
aws ecr get-login-password --region ap-south-1 | docker login --username AWS --password-stdin ACCOUNT_ID.dkr.ecr.ap-south-1.amazonaws.com
```

## 7. Build and Push Images

Build from this repo:

```bash
docker build -f Dockerfile.api -t image-api:1.0 .
docker build -f Dockerfile.worker -t image-worker:1.0 .
docker build -t image-frontend:1.0 ./frontend
```

Tag the images:

```bash
docker tag image-api:1.0 ACCOUNT_ID.dkr.ecr.ap-south-1.amazonaws.com/image-api:1.0
docker tag image-worker:1.0 ACCOUNT_ID.dkr.ecr.ap-south-1.amazonaws.com/image-worker:1.0
docker tag image-frontend:1.0 ACCOUNT_ID.dkr.ecr.ap-south-1.amazonaws.com/image-frontend:1.0
```

Push the images:

```bash
docker push ACCOUNT_ID.dkr.ecr.ap-south-1.amazonaws.com/image-api:1.0
docker push ACCOUNT_ID.dkr.ecr.ap-south-1.amazonaws.com/image-worker:1.0
docker push ACCOUNT_ID.dkr.ecr.ap-south-1.amazonaws.com/image-frontend:1.0
```

## 8. Create IAM Roles

You need at least two ECS roles:

- `task execution role`
  - pull images from ECR
  - write logs to CloudWatch
  - read secrets from Secrets Manager
- `task role`
  - API task: send SQS messages, optionally read S3 for presigned URL logic
  - worker task: receive/delete SQS messages, upload to S3, read queue attributes

Recommended permissions:

- API task role
  - `sqs:SendMessage`
  - `sqs:GetQueueAttributes`
  - `s3:GetObject` if needed
- Worker task role
  - `sqs:ReceiveMessage`
  - `sqs:DeleteMessage`
  - `sqs:GetQueueAttributes`
  - `sqs:ChangeMessageVisibility`
  - `s3:PutObject`
- Both if using secrets injection
  - `secretsmanager:GetSecretValue`

This is a great place to teach least-privilege access.

## 9. Create the ECS Cluster and Task Definitions

Create one ECS cluster for the application.

Then create three task definitions:

- `frontend-task`
- `backend-task`
- `worker-task`

### 9.1 Frontend task definition

Container details:

- image: `image-frontend`
- container port: `80`
- log driver: `awslogs`

### 9.2 Backend task definition

Container details:

- image: `image-api`
- container port: `8000`
- secrets:
  - `OPENAI_API_KEY`
  - `DATABASE_URL`
- environment:
  - `AWS_REGION`
  - `SQS_QUEUE_URL`
  - `S3_BUCKET_NAME`
  - `OPENAI_IMAGE_MODEL`
  - `OPENAI_IMAGE_OUTPUT_FORMAT`
  - `CORS_ORIGINS`

Health check target in the app:

- `GET /api/health`

### 9.3 Worker task definition

Container details:

- image: `image-worker`
- no public port required
- secrets:
  - `OPENAI_API_KEY`
  - `DATABASE_URL`
- environment:
  - `AWS_REGION`
  - `SQS_QUEUE_URL`
  - `S3_BUCKET_NAME`
  - `WORKER_POLL_SECONDS`
  - `WORKER_MAX_ATTEMPTS`

## 10. Add the Application Load Balancer

Create an `Application Load Balancer` in the public subnets.

Create two target groups:

- `frontend-tg`
  - protocol: `HTTP`
  - port: `80`
  - health check path: `/`
- `backend-tg`
  - protocol: `HTTP`
  - port: `8000`
  - health check path: `/api/health`

Configure ALB listener rules:

- `/api/*` -> `backend-tg`
- `/*` -> `frontend-tg`

Why this matters:

- one public entrypoint
- clean routing between frontend and backend
- production-style ECS deployment model

## 11. Request an ACM Certificate

Use `AWS Certificate Manager` to request a public certificate for your domain.

Example domains:

- `images.example.com`
- `api.images.example.com`

Recommended approach:

- request certificate in the same region as the ALB
- use DNS validation

Example:

```bash
aws acm request-certificate \
  --domain-name images.example.com \
  --validation-method DNS
```

After requesting the certificate:

1. ACM gives you DNS validation records
2. add them in Route 53
3. wait for certificate status to become `ISSUED`

## 12. Configure Route 53

Create a hosted zone for your domain if it does not already exist.

Then create alias records:

- `images.example.com` -> ALB

Optional:

- `api.images.example.com` -> ALB with host-based rules instead of path-based rules

Recommended student setup:

- keep one domain and use path routing
- `https://images.example.com/`
- `https://images.example.com/api/health`

This is easier to demo and explain.

## 13. Create ECS Services

Create three ECS services:

- `frontend-service`
- `backend-service`
- `worker-service`

Recommended desired counts:

- frontend: `2`
- backend: `2`
- worker: `1`

Attach load balancers:

- frontend service -> `frontend-tg`
- backend service -> `backend-tg`
- worker service -> no load balancer

Recommended subnet placement:

- frontend tasks: private subnets is ideal, public subnets is acceptable for a simpler lab
- backend tasks: private subnets
- worker tasks: private subnets

## 14. Enable HTTPS on the ALB

Once ACM issues the certificate:

1. create an HTTPS listener on port `443`
2. attach the ACM certificate
3. forward traffic using the same routing rules
4. optionally redirect port `80` to `443`

Students should see:

- how HTTPS is terminated at the ALB
- how ECS containers can keep serving plain HTTP internally

## 15. Add CloudWatch Logging, Metrics, and Alarms

### 15.1 Container logs

Enable `awslogs` for all ECS containers:

- frontend logs
- backend logs
- worker logs

Suggested log groups:

- `/ecs/openai-image/frontend`
- `/ecs/openai-image/backend`
- `/ecs/openai-image/worker`

### 15.2 Metrics to watch

Important CloudWatch metrics:

- ALB `RequestCount`
- ALB `HTTPCode_Target_5XX_Count`
- ECS service `CPUUtilization`
- ECS service `MemoryUtilization`
- SQS `ApproximateNumberOfMessagesVisible`
- SQS `ApproximateAgeOfOldestMessage`
- RDS CPU and connections

### 15.3 Useful alarms

Create alarms for:

- backend target group unhealthy hosts > `0`
- worker queue depth above threshold
- messages arriving in the DLQ
- ECS CPU > `70%`
- ECS memory > `80%`
- ALB 5XX responses above threshold

This is one of the most valuable additions for students because it teaches operational awareness.

## 16. Configure Auto Scaling

### 16.1 Backend and frontend scaling

Use ECS Service Auto Scaling based on:

- CPU utilization
- memory utilization
- optionally ALB request count

Suggested target tracking:

- scale out when CPU averages above `60%`
- minimum `2` tasks
- maximum `4` tasks

### 16.2 Worker scaling

Scale the worker service based on SQS queue depth.

Recommended idea:

- minimum `1` task
- maximum `5` tasks
- scale out when visible messages increase
- scale in when queue drains

This is especially nice for this app because students can see the system react to bursts of image jobs.

## 17. Validate the Deployment

Once everything is deployed, test in this order:

1. Open the frontend domain in the browser
2. Check that the frontend loads through the ALB
3. Call `https://your-domain/api/health`
4. Submit an image generation request
5. Confirm the backend writes a job to PostgreSQL
6. Confirm the message appears in SQS
7. Confirm the worker consumes the message
8. Confirm the image uploads to S3
9. Confirm the UI shows the completed image
10. Confirm logs appear in CloudWatch

Then test failure handling:

1. force the worker to fail with a bad API key in a non-production test environment
2. watch retry behavior
3. confirm failed messages move to the DLQ after max receives
4. inspect CloudWatch logs and alarms

## 18. Suggested Demo Flow for Students

A strong classroom demo sequence is:

1. Show the architecture diagram
2. Show ECR repositories containing the three images
3. Show ECS cluster and services
4. Show the ALB target groups and listener rules
5. Show the Route 53 domain and ACM certificate
6. Show Secrets Manager holding API key and DB connection info
7. Trigger a new image job from the frontend
8. Show the message on SQS
9. Show the worker logs in CloudWatch
10. Show the image in S3 and the final UI result
11. Show the DLQ and explain retry safety
12. Show auto scaling policies and discuss production behavior

## 19. Recommended Talking Points

Use these ideas while teaching:

- `ECR` stores versioned container images
- `ECS Fargate` runs containers without managing servers
- `ALB` gives one public entrypoint and routes by path
- `Route 53` maps the domain name to the load balancer
- `ACM` provides managed HTTPS certificates
- `Secrets Manager` avoids hardcoding secrets in containers
- `SQS` decouples the API from long-running image generation
- `DLQ` protects failed jobs for later inspection
- `CloudWatch` centralizes logs, metrics, and alarms
- `Auto Scaling` lets the app adapt to traffic and queue load

## 20. Nice Optional Enhancements

If you want the project to feel even more complete later, consider:

- `CloudFront` in front of the frontend or S3 image delivery
- `AWS WAF` in front of the ALB
- `RDS Multi-AZ` for high availability discussion
- `CI/CD` with GitHub Actions, CodeBuild, or CodePipeline
- `AWS X-Ray` or OpenTelemetry tracing

## 21. Summary

For the most complete student version of this project, the strongest next AWS improvements are:

1. `ALB`
2. `Route 53`
3. `ACM`
4. `Secrets Manager`
5. `CloudWatch`
6. `SQS DLQ`
7. `Auto Scaling`

That combination turns this repo from a simple async image app into a very solid example of a modern containerized AWS system.
