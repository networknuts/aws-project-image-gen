# AWS Console Deployment Guide

This guide shows how to deploy the OpenAI Image Generator POC using the AWS Management Console instead of the CLI.

It is intended for students who have learned AWS services in theory and now want to connect them through the GUI in a realistic deployment flow.

This guide covers:

- `ECR`
- `ECS Fargate`
- `ALB`
- `Route 53`
- `ACM`
- `CloudWatch`
- `Secrets Manager`
- `SQS FIFO` with a `DLQ`
- `Auto Scaling`

It assumes this project architecture:

- `frontend` React app served by Nginx
- `backend` FastAPI API
- `worker` Python background worker
- `RDS PostgreSQL` for job metadata
- `S3` for generated images
- `SQS FIFO` for async image processing

## 1. What Students Will Build

By the end of this guide, the deployment will look like this:

```text
User
  |
Route 53
  |
ACM Certificate
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

## 2. Recommended Deployment Order

Use this order in class so each service builds naturally on the previous one:

1. Create the VPC and subnets
2. Create security groups
3. Create the S3 bucket
4. Create the SQS queue and DLQ
5. Create the RDS database
6. Create secrets in Secrets Manager
7. Create ECR repositories
8. Build and push Docker images
9. Create the ECS cluster
10. Create the ALB and target groups
11. Create ECS task definitions
12. Create ECS services
13. Request an ACM certificate
14. Create Route 53 DNS records
15. Configure CloudWatch
16. Configure Auto Scaling

## 3. Create Networking in the VPC Console

Open the `VPC` service in the AWS Console.

### 3.1 Create the VPC

In the VPC dashboard:

1. Open `Your VPCs`
2. Click `Create VPC`
3. Choose `VPC and more resources` if you want AWS to help create subnets and route tables
4. Or choose `VPC only` if you want students to create each networking component manually

Recommended teaching setup:

- 1 VPC
- 2 public subnets
- 2 private subnets
- 1 internet gateway
- 1 NAT gateway

Why this matters:

- the `ALB` should be public
- `ECS` backend and worker tasks should stay private
- `RDS` should stay private

### 3.2 Create or verify subnets

Inside `Subnets`, make sure you have:

- `2 public subnets` in different availability zones
- `2 private subnets` in different availability zones

Check:

- public subnets have routes to the internet gateway
- private subnets have routes to the NAT gateway

## 4. Create Security Groups

Open `Security Groups` in the VPC console and create these groups:

### 4.1 ALB security group

Create `alb-sg` with:

- inbound `HTTP 80` from `0.0.0.0/0`
- inbound `HTTPS 443` from `0.0.0.0/0`

### 4.2 Frontend ECS security group

Create `frontend-sg` with:

- inbound `HTTP 80` from `alb-sg`

### 4.3 Backend ECS security group

Create `backend-sg` with:

- inbound `TCP 8000` from `alb-sg`

### 4.4 Worker ECS security group

Create `worker-sg` with:

- no public inbound rules

### 4.5 RDS security group

Create `db-sg` with:

- inbound `PostgreSQL 5432` from `backend-sg`
- inbound `PostgreSQL 5432` from `worker-sg`

## 5. Create the S3 Bucket

Open the `S3` console.

1. Click `Create bucket`
2. Choose a globally unique name
3. Select the correct AWS Region
4. Keep `Block all public access` enabled
5. Turn on bucket encryption
6. Optionally enable versioning
7. Click `Create bucket`

Use this bucket for generated images.

Recommended bucket settings for students:

- private bucket
- encryption enabled
- no public object access

## 6. Create the SQS FIFO Queue and DLQ

Open the `SQS` console.

### 6.1 Create the dead-letter queue

1. Click `Create queue`
2. Choose `FIFO`
3. Name it something like `image-generation-dlq.fifo`
4. Create the queue

### 6.2 Create the main queue

1. Click `Create queue`
2. Choose `FIFO`
3. Name it something like `image-generation.fifo`
4. Set a visibility timeout long enough for image generation, for example `180 seconds`
5. In the dead-letter queue section, attach the FIFO DLQ
6. Set `max receives` to `3`
7. Create the queue

Why this matters:

- if a worker fails repeatedly, the message is preserved
- students see how AWS handles failure safely

## 7. Create the RDS PostgreSQL Database

Open the `RDS` console.

1. Click `Create database`
2. Choose `Standard create`
3. Engine type: `PostgreSQL`
4. Templates: choose `Free tier` or `Dev/Test` for a classroom demo
5. DB instance identifier: something like `imageapp-postgres`
6. Set the master username and password
7. Under connectivity, choose the application VPC
8. Place it in private subnets using a DB subnet group
9. Attach `db-sg`
10. Set public access to `No`
11. Create the database

Wait for the instance to become available, then copy the endpoint.

You will use that endpoint to build the `DATABASE_URL` secret later.

## 8. Create Secrets in Secrets Manager

Open `Secrets Manager`.

Create these secrets:

### 8.1 OpenAI API key

1. Click `Store a new secret`
2. Choose `Other type of secret`
3. Store the value for `OPENAI_API_KEY`
4. Name it something like `openai-image-app/openai-api-key`
5. Save it

### 8.2 Database URL

Create a second secret for:

- `DATABASE_URL`

Example value:

```text
postgresql+psycopg2://imageapp:password@your-rds-endpoint:5432/imageapp
```

Name it something like:

- `openai-image-app/database-url`

Why this matters:

- no secrets in ECS task definitions
- cleaner production-style setup

## 9. Create ECR Repositories

Open the `ECR` console.

Create three private repositories:

- `image-frontend`
- `image-api`
- `image-worker`

For each one:

1. Click `Create repository`
2. Choose `Private`
3. Enter the repository name
4. Create the repository

After creation, copy the repository URI for each repository.

## 10. Build and Push the Docker Images

This step uses Docker locally, but students can still follow the rest in the GUI.

From the repository root, build:

```bash
docker build -f Dockerfile.api -t image-api:1.0 .
docker build -f Dockerfile.worker -t image-worker:1.0 .
docker build -t image-frontend:1.0 ./frontend
```

Then use the `View push commands` button in each ECR repository page to:

1. authenticate Docker to ECR
2. tag the image
3. push the image

Repeat for:

- backend
- worker
- frontend

## 11. Create the ECS Cluster

Open the `ECS` console.

1. Click `Clusters`
2. Click `Create cluster`
3. Choose an ECS cluster using `AWS Fargate`
4. Name it something like `openai-image-cluster`
5. Create the cluster

This cluster will run:

- the frontend service
- the backend service
- the worker service

## 12. Create IAM Roles for ECS

Open the `IAM` console.

You need at least:

- an `ECS task execution role`
- an `application task role`

### 12.1 ECS task execution role

This role should allow:

- pulling images from `ECR`
- writing logs to `CloudWatch`
- reading secrets from `Secrets Manager`

The easiest classroom approach is:

1. Create a role for `Elastic Container Service Task`
2. Attach the standard ECS task execution policy
3. Add Secrets Manager read permissions

### 12.2 Application task role

This role should allow:

- `SQS SendMessage` for the backend
- `SQS ReceiveMessage`, `DeleteMessage`, `GetQueueAttributes`, `ChangeMessageVisibility` for the worker
- `S3 PutObject` for the worker
- `S3 GetObject` if needed
- `SecretsManager GetSecretValue` if your setup uses it at runtime

This is a good place to explain least privilege to students.

## 13. Create the Application Load Balancer

Open the `EC2` console and then `Load Balancers`.

1. Click `Create Load Balancer`
2. Choose `Application Load Balancer`
3. Name it something like `image-app-alb`
4. Scheme: `Internet-facing`
5. IP address type: `IPv4`
6. Choose the application VPC
7. Select the `2 public subnets`
8. Attach `alb-sg`

For now, create at least one listener on port `80`.

You will add `HTTPS 443` after the ACM certificate is ready.

## 14. Create the Target Groups

Still in the `EC2` console, open `Target Groups`.

Create two target groups:

### 14.1 Frontend target group

- target type: `IP`
- protocol: `HTTP`
- port: `80`
- health check path: `/`

### 14.2 Backend target group

- target type: `IP`
- protocol: `HTTP`
- port: `8000`
- health check path: `/api/health`

These target groups will later be attached to ECS services.

## 15. Create ECS Task Definitions

Open `ECS` and then `Task Definitions`.

Create three task definitions using `Fargate`:

- `frontend-task`
- `backend-task`
- `worker-task`

### 15.1 Frontend task definition

Configure:

- container image: frontend ECR URI
- port mapping: `80`
- log driver: `awslogs`
- CloudWatch log group for frontend logs

### 15.2 Backend task definition

Configure:

- container image: backend ECR URI
- port mapping: `8000`
- environment variables:
  - `AWS_REGION`
  - `SQS_QUEUE_URL`
  - `S3_BUCKET_NAME`
  - `OPENAI_IMAGE_MODEL`
  - `OPENAI_IMAGE_OUTPUT_FORMAT`
  - `CORS_ORIGINS`
- secrets:
  - `OPENAI_API_KEY`
  - `DATABASE_URL`
- log driver: `awslogs`

Health endpoint:

- `/api/health`

### 15.3 Worker task definition

Configure:

- container image: worker ECR URI
- no public port required
- environment variables:
  - `AWS_REGION`
  - `SQS_QUEUE_URL`
  - `S3_BUCKET_NAME`
  - `WORKER_POLL_SECONDS`
  - `WORKER_MAX_ATTEMPTS`
- secrets:
  - `OPENAI_API_KEY`
  - `DATABASE_URL`
- log driver: `awslogs`

## 16. Create the ECS Services

Inside the ECS cluster, create three services.

### 16.1 Frontend service

When creating the service:

- choose the frontend task definition
- launch type: `Fargate`
- desired tasks: `2`
- networking:
  - choose the VPC
  - choose the private subnets if NAT exists
  - attach `frontend-sg`
- load balancing:
  - attach the frontend target group
  - container name and port should match the task definition

### 16.2 Backend service

- choose the backend task definition
- desired tasks: `2`
- choose private subnets
- attach `backend-sg`
- attach the backend target group

### 16.3 Worker service

- choose the worker task definition
- desired tasks: `1`
- choose private subnets
- attach `worker-sg`
- do not attach a load balancer

## 17. Configure ALB Listener Rules

Open the ALB in the `EC2` console and edit the listener rules.

Recommended routing:

- `/api/*` -> backend target group
- default `/*` -> frontend target group

This gives:

- frontend at `/`
- backend endpoints at `/api/...`

This is the cleanest student demo setup.

## 18. Request an ACM Certificate

Open the `Certificate Manager` console.

1. Click `Request`
2. Choose `Request a public certificate`
3. Enter the domain, such as `images.example.com`
4. Choose `DNS validation`
5. Submit the request

ACM will show DNS validation records.

## 19. Create the Route 53 Records

Open the `Route 53` console.

### 19.1 Validate the ACM certificate

In the hosted zone:

1. Create the ACM-provided `CNAME` record
2. Wait until the certificate status changes to `Issued`

### 19.2 Create the application DNS record

Create an alias record:

- record name: `images`
- type: `A`
- alias target: your ALB

Now users can access:

- `https://images.example.com`

## 20. Add HTTPS to the ALB

Return to the `EC2` console and open the ALB listeners.

1. Add a new listener on `443`
2. Choose `HTTPS`
3. Attach the ACM certificate
4. Forward traffic using the same routing logic
5. Optionally redirect `HTTP 80` to `HTTPS 443`

This is a strong teaching moment:

- `ACM` manages the certificate
- `ALB` terminates TLS
- containers can continue serving plain HTTP internally

## 21. Configure CloudWatch

### 21.1 Logs

When creating ECS task definitions, enable `awslogs` for:

- frontend
- backend
- worker

Suggested log group names:

- `/ecs/openai-image/frontend`
- `/ecs/openai-image/backend`
- `/ecs/openai-image/worker`

Open `CloudWatch Logs` to verify:

- backend health checks appear
- worker job processing appears
- frontend container logs appear

### 21.2 Metrics and alarms

Open `CloudWatch` and create alarms for:

- ALB `5XX` errors
- unhealthy backend targets
- SQS queue depth
- DLQ visible messages
- ECS CPU utilization
- ECS memory utilization

Important metrics to show students:

- `ApproximateNumberOfMessagesVisible`
- `ApproximateAgeOfOldestMessage`
- ALB target health
- ECS service CPU and memory

## 22. Configure Auto Scaling

Open the `ECS` service page and then the auto scaling section.

### 22.1 Frontend and backend scaling

Add target tracking scaling policies:

- metric: `CPU utilization`
- target value: around `60%`
- minimum tasks: `2`
- maximum tasks: `4`

### 22.2 Worker scaling

For the worker service, teach students that scaling can be tied to queue load.

A good classroom approach is:

1. register the worker service as scalable
2. create a scaling policy
3. connect it to SQS queue depth through CloudWatch alarms

This helps students understand that async systems scale differently from web servers.

## 23. Validate the Full Deployment

After deployment, test in this order:

1. Open the frontend domain
2. Confirm the frontend loads through the ALB
3. Open `/api/health`
4. Confirm the backend health check works
5. Submit an image generation request
6. Check that the message appears in SQS
7. Check that the worker consumes it
8. Check CloudWatch logs
9. Check that the image appears in S3
10. Check that the frontend shows the generated result

Then test failure handling:

1. force a bad API key in a non-production environment
2. watch retries happen
3. confirm failed jobs move to the DLQ
4. inspect logs and alarms

## 24. Suggested Demo Flow in Class

Use this classroom walkthrough:

1. Show the final architecture diagram
2. Show the `ECR` repositories
3. Show the `ECS` cluster, task definitions, and services
4. Show the `ALB`, listeners, and target groups
5. Show the `Route 53` alias record
6. Show the `ACM` certificate
7. Show the `Secrets Manager` secrets
8. Submit a job from the frontend
9. Watch the queue and worker logs
10. Show the result in `S3` and in the UI
11. Show the `DLQ`
12. Show CloudWatch alarms and scaling settings

## 25. Teaching Notes

This GUI flow is especially useful for students because they can visually connect services:

- `ECR` stores images
- `ECS Fargate` runs containers
- `ALB` routes traffic
- `Route 53` provides the domain
- `ACM` enables HTTPS
- `Secrets Manager` protects secrets
- `SQS` decouples long-running work
- `DLQ` captures failures
- `CloudWatch` gives observability
- `Auto Scaling` adapts to load

## 26. Nice Optional Extensions

If you want to extend the class later, consider adding:

- `CloudFront`
- `AWS WAF`
- `CodePipeline`
- `GitHub Actions`
- `RDS Multi-AZ`
- `AWS X-Ray`

## 27. Summary

This project becomes a strong student-facing AWS deployment when the GUI flow includes:

1. `ECR`
2. `ECS Fargate`
3. `ALB`
4. `Route 53`
5. `ACM`
6. `Secrets Manager`
7. `CloudWatch`
8. `SQS DLQ`
9. `Auto Scaling`

That combination gives students a realistic picture of how a modern containerized AWS application is deployed and operated.
