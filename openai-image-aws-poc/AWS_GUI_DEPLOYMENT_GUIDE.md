# AWS Console Deployment Guide

This guide shows how to deploy the OpenAI Image Generator POC using the AWS Management Console in a very explicit, step-by-step way.

It is written for students who need every step spelled out, including:

- what AWS service to open
- what resource to create
- what values to enter
- what names to use
- what output to save for the next step

This guide covers:

- `VPC`
- `Security Groups`
- `S3`
- `SQS FIFO` with a `DLQ`
- `RDS PostgreSQL`
- `Secrets Manager`
- `ECR`
- `ECS Fargate`
- `ALB`
- `Route 53`
- `ACM`
- `CloudWatch`
- `Auto Scaling`

## 1. Target Architecture

By the end of this deployment, the project should look like this:

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

## 2. Values to Use Throughout This Guide

To make the guide easy to follow, use these example names.

You can change them, but if you do, keep them consistent everywhere.

### 2.1 Region

Use:

- `ap-south-1`

### 2.2 Project naming

Use this prefix for all resources:

- `openai-image-prod`

Example resource names:

- VPC: `openai-image-prod-vpc`
- ALB: `openai-image-prod-alb`
- ECS cluster: `openai-image-prod-cluster`
- S3 bucket: `openai-image-prod-images`
- RDS instance: `openai-image-prod-postgres`
- Main queue: `openai-image-prod-image-generation.fifo`
- DLQ: `openai-image-prod-image-generation-dlq.fifo`

### 2.3 Domain names

Assume:

- root domain: `example.com`
- app domain: `images.example.com`

### 2.4 VPC CIDR plan

Use these ranges:

- VPC: `10.0.0.0/16`
- Public subnet 1: `10.0.1.0/24`
- Public subnet 2: `10.0.2.0/24`
- Private subnet 1: `10.0.11.0/24`
- Private subnet 2: `10.0.12.0/24`

### 2.5 Availability zones

Use any two AZs in `ap-south-1`. Example:

- `ap-south-1a`
- `ap-south-1b`

### 2.6 Database values

Example values:

- DB engine: `PostgreSQL`
- database name: `imageapp`
- username: `imageapp`
- password: choose your own strong password

### 2.7 Save these values as you go

Keep a notepad open and save:

- VPC ID
- public subnet IDs
- private subnet IDs
- security group IDs
- S3 bucket name
- SQS queue URL
- SQS DLQ URL
- RDS endpoint
- secret names
- ECR repository URIs
- ALB DNS name
- ACM certificate ARN

You will reuse them in later steps.

## 3. Recommended Deployment Order

Follow this exact order:

1. Create the VPC
2. Create public and private subnets
3. Create the internet gateway
4. Create the NAT gateway
5. Create route tables
6. Create security groups
7. Create the S3 bucket
8. Create the SQS DLQ
9. Create the main SQS FIFO queue
10. Create the RDS PostgreSQL database
11. Create the secrets in Secrets Manager
12. Create the ECR repositories
13. Build and push the Docker images
14. Create IAM roles for ECS
15. Create the ECS cluster
16. Create the ALB
17. Create the target groups
18. Create the ACM certificate
19. Create the Route 53 validation record
20. Create ECS task definitions
21. Create ECS services
22. Add HTTPS to the ALB
23. Create the Route 53 alias record
24. Configure CloudWatch logs and alarms
25. Configure ECS auto scaling
26. Test the full deployment

## 4. Create the VPC

Open the AWS Console and set the region to:

- `ap-south-1`

Then:

1. Search for `VPC`
2. Open the `VPC` service
3. In the left menu, click `Your VPCs`
4. Click `Create VPC`
5. Choose `VPC only`

Enter:

- Name tag: `openai-image-prod-vpc`
- IPv4 CIDR: `10.0.0.0/16`
- IPv6 CIDR: `No IPv6 CIDR block`
- Tenancy: `Default`

Click `Create VPC`

After creation:

1. Click the VPC name
2. Copy and save the `VPC ID`

## 5. Create the Public Subnets

In the `VPC` console:

1. Open `Subnets`
2. Click `Create subnet`
3. Select VPC: `openai-image-prod-vpc`

Create the first public subnet:

- Subnet name: `openai-image-prod-public-1`
- Availability Zone: `ap-south-1a`
- IPv4 subnet CIDR block: `10.0.1.0/24`

Click `Add new subnet`

Create the second public subnet:

- Subnet name: `openai-image-prod-public-2`
- Availability Zone: `ap-south-1b`
- IPv4 subnet CIDR block: `10.0.2.0/24`

Click `Create subnet`

Save both subnet IDs.

## 6. Create the Private Subnets

Still in `Subnets`:

1. Click `Create subnet`
2. Select the same VPC

Create the first private subnet:

- Subnet name: `openai-image-prod-private-1`
- Availability Zone: `ap-south-1a`
- IPv4 subnet CIDR block: `10.0.11.0/24`

Click `Add new subnet`

Create the second private subnet:

- Subnet name: `openai-image-prod-private-2`
- Availability Zone: `ap-south-1b`
- IPv4 subnet CIDR block: `10.0.12.0/24`

Click `Create subnet`

Save both private subnet IDs.

## 7. Configure Public Subnets to Auto-Assign Public IPs

You want public subnets to automatically assign public IPs.

For `openai-image-prod-public-1`:

1. Click the subnet
2. Click `Actions`
3. Click `Edit subnet settings`
4. Enable `Auto-assign public IPv4 address`
5. Click `Save`

Repeat the same for:

- `openai-image-prod-public-2`

## 8. Create the Internet Gateway

In the `VPC` console:

1. Open `Internet gateways`
2. Click `Create internet gateway`

Enter:

- Name tag: `openai-image-prod-igw`

Click `Create internet gateway`

Then:

1. Select the internet gateway
2. Click `Actions`
3. Click `Attach to VPC`
4. Choose `openai-image-prod-vpc`
5. Click `Attach internet gateway`

## 9. Create the NAT Gateway

The backend and worker will run in private subnets, but they still need outbound internet access for:

- OpenAI API calls
- pulling dependencies at runtime if needed
- AWS service access through the network path

To create the NAT gateway:

1. In the `VPC` console, open `NAT gateways`
2. Click `Create NAT gateway`

Enter:

- Name: `openai-image-prod-nat`
- Subnet: `openai-image-prod-public-1`
- Connectivity type: `Public`

Then:

1. Under Elastic IP allocation ID, click `Allocate Elastic IP`
2. Confirm the Elastic IP appears
3. Click `Create NAT gateway`

Wait until the NAT gateway status becomes:

- `Available`

This may take a few minutes.

## 10. Create the Public Route Table

In the `VPC` console:

1. Open `Route tables`
2. Click `Create route table`

Enter:

- Name: `openai-image-prod-public-rt`
- VPC: `openai-image-prod-vpc`

Click `Create route table`

Then add the public route:

1. Open the route table
2. Open the `Routes` tab
3. Click `Edit routes`
4. Click `Add route`

Enter:

- Destination: `0.0.0.0/0`
- Target: select `Internet Gateway`
- Choose `openai-image-prod-igw`

Click `Save changes`

Now associate the public subnets:

1. Open the `Subnet associations` tab
2. Click `Edit subnet associations`
3. Select:
   - `openai-image-prod-public-1`
   - `openai-image-prod-public-2`
4. Click `Save associations`

## 11. Create the Private Route Table

In `Route tables`:

1. Click `Create route table`

Enter:

- Name: `openai-image-prod-private-rt`
- VPC: `openai-image-prod-vpc`

Click `Create route table`

Add the private outbound route:

1. Open the new route table
2. Open the `Routes` tab
3. Click `Edit routes`
4. Click `Add route`

Enter:

- Destination: `0.0.0.0/0`
- Target: select `NAT gateway`
- Choose `openai-image-prod-nat`

Click `Save changes`

Now associate the private subnets:

1. Open `Subnet associations`
2. Click `Edit subnet associations`
3. Select:
   - `openai-image-prod-private-1`
   - `openai-image-prod-private-2`
4. Click `Save associations`

## 12. Create the Security Groups

Still in the `VPC` service:

1. Open `Security Groups`
2. Click `Create security group`

You will create five groups.

### 12.1 ALB security group

Create:

- Security group name: `openai-image-prod-alb-sg`
- Description: `ALB security group`
- VPC: `openai-image-prod-vpc`

Inbound rules:

- Type: `HTTP`
- Port: `80`
- Source: `Anywhere-IPv4`

- Type: `HTTPS`
- Port: `443`
- Source: `Anywhere-IPv4`

Outbound rules:

- leave default `All traffic`

Click `Create security group`

### 12.2 Frontend ECS security group

Create:

- Security group name: `openai-image-prod-frontend-sg`
- Description: `Frontend ECS tasks`
- VPC: `openai-image-prod-vpc`

Inbound rule:

- Type: `HTTP`
- Port: `80`
- Source: `Custom`
- Select `openai-image-prod-alb-sg`

Outbound:

- keep default `All traffic`

### 12.3 Backend ECS security group

Create:

- Security group name: `openai-image-prod-backend-sg`
- Description: `Backend ECS tasks`
- VPC: `openai-image-prod-vpc`

Inbound rule:

- Type: `Custom TCP`
- Port: `8000`
- Source: `Custom`
- Select `openai-image-prod-alb-sg`

Outbound:

- keep default `All traffic`

### 12.4 Worker ECS security group

Create:

- Security group name: `openai-image-prod-worker-sg`
- Description: `Worker ECS tasks`
- VPC: `openai-image-prod-vpc`

Inbound:

- no inbound rules needed

Outbound:

- keep default `All traffic`

### 12.5 Database security group

Create:

- Security group name: `openai-image-prod-db-sg`
- Description: `PostgreSQL database`
- VPC: `openai-image-prod-vpc`

Inbound rules:

- Type: `PostgreSQL`
- Port: `5432`
- Source: `Custom`
- Select `openai-image-prod-backend-sg`

- Type: `PostgreSQL`
- Port: `5432`
- Source: `Custom`
- Select `openai-image-prod-worker-sg`

Outbound:

- keep default `All traffic`

Save all security group IDs.

## 13. Create the S3 Bucket

Search for `S3` and open the S3 console.

1. Click `Create bucket`

Enter:

- Bucket name: `openai-image-prod-images`
- AWS Region: `Asia Pacific (Mumbai) ap-south-1`

Object Ownership:

- choose `ACLs disabled`

Block Public Access:

- keep `Block all public access` enabled

Bucket Versioning:

- choose `Enable`

Default encryption:

- choose `Server-side encryption with Amazon S3 managed keys (SSE-S3)`

Click `Create bucket`

Save the bucket name exactly.

## 14. Create the SQS Dead-Letter Queue

Search for `SQS` and open the service.

1. Click `Create queue`

Enter:

- Type: `FIFO`
- Name: `openai-image-prod-image-generation-dlq.fifo`

Configuration:

- Content-based deduplication: leave disabled
- Visibility timeout: keep default
- Delivery delay: keep default
- Message retention period: default is fine

Click `Create queue`

After creation:

1. Open the queue
2. Copy and save:
   - Queue URL
   - Queue ARN

## 15. Create the Main SQS FIFO Queue

Still in `SQS`:

1. Click `Create queue`

Enter:

- Type: `FIFO`
- Name: `openai-image-prod-image-generation.fifo`

Configuration:

- Content-based deduplication: disabled
- Visibility timeout: `180` seconds
- Message retention period: leave default

Dead-letter queue:

1. Enable dead-letter queue
2. Choose `Use existing queue`
3. Select `openai-image-prod-image-generation-dlq.fifo`
4. Set `Maximum receives` to `3`

Click `Create queue`

After creation, save:

- Queue URL
- Queue ARN

You will need the queue URL for the backend and worker task definitions.

## 16. Create the RDS PostgreSQL Database

Search for `RDS` and open the service.

1. Click `Create database`
2. Choose `Standard create`

Engine options:

- Engine type: `PostgreSQL`
- Version: latest stable version shown by AWS is fine

Templates:

- choose `Free tier` if you want the smallest classroom setup
- choose `Dev/Test` if free tier options are not available

Settings:

- DB instance identifier: `openai-image-prod-postgres`
- Master username: `imageapp`
- Master password: choose a strong password
- Confirm password: re-enter it

Instance configuration:

- DB instance class: `db.t3.micro`

Storage:

- Allocated storage: `20 GiB`
- Storage type: default is fine

Connectivity:

- Compute resource: `Don’t connect to an EC2 compute resource`
- VPC: `openai-image-prod-vpc`
- DB subnet group: create a new one if needed using the two private subnets
- Public access: `No`
- VPC security group: `Choose existing`
- Existing VPC security groups: select `openai-image-prod-db-sg`
- Availability Zone: `No preference`

Database authentication:

- Password authentication

Additional configuration:

- Initial database name: `imageapp`

Leave other settings as default for a classroom deployment, then click:

- `Create database`

Wait until the database status becomes:

- `Available`

Then open the DB instance and copy:

- Endpoint
- Port

Example endpoint use later:

```text
postgresql+psycopg2://imageapp:YOUR_PASSWORD@YOUR_RDS_ENDPOINT:5432/imageapp
```

## 17. Create the Secrets in Secrets Manager

Search for `Secrets Manager` and open it.

You need two secrets.

### 17.1 Secret for the OpenAI API key

1. Click `Store a new secret`
2. Choose `Other type of secret`
3. Add a key/value pair:
   - Key: `OPENAI_API_KEY`
   - Value: your actual OpenAI API key
4. Click `Next`

Secret name:

- `openai-image-prod/openai-api-key`

Description:

- `OpenAI API key for image generation app`

Click `Next`

Rotation:

- leave rotation disabled

Click `Next`, then `Store`

### 17.2 Secret for the database URL

1. Click `Store a new secret`
2. Choose `Other type of secret`
3. Add a key/value pair:
   - Key: `DATABASE_URL`
   - Value: `postgresql+psycopg2://imageapp:YOUR_PASSWORD@YOUR_RDS_ENDPOINT:5432/imageapp`
4. Click `Next`

Secret name:

- `openai-image-prod/database-url`

Description:

- `Database connection string for image generation app`

Click `Next`

Rotation:

- keep disabled for now

Click `Next`, then `Store`

Save both secret names and ARNs.

## 18. Create the ECR Repositories

Search for `ECR` and open `Elastic Container Registry`.

Create three repositories.

### 18.1 Frontend repository

1. Click `Create repository`
2. Visibility settings: `Private`
3. Repository name: `openai-image-poc-frontend`
4. Leave the defaults
5. Click `Create repository`

### 18.2 Backend repository

Create:

- Repository name: `openai-image-poc-api`

### 18.3 Worker repository

Create:

- Repository name: `openai-image-poc-worker`

After creating each repository:

1. Open it
2. Copy the repository URI
3. Save it

You will need the URI in the ECS task definitions.

## 19. Build and Push Docker Images

This step is done on your local machine, but it still connects to the AWS resources you created in the GUI.

From the project root:

```bash
docker build -f Dockerfile.api -t image-api:1.0 .
docker build -f Dockerfile.worker -t image-worker:1.0 .
docker build -t image-frontend:1.0 ./frontend
```

Now push each image to ECR.

For each repository:

1. Open the repository in `ECR`
2. Click `View push commands`
3. Copy and run the commands shown by AWS

Push:

- backend image to `openai-image-poc-api`
- worker image to `openai-image-poc-worker`
- frontend image to `openai-image-poc-frontend`

When complete, confirm that each repository shows at least one image tag.

## 20. Create IAM Roles for ECS

Search for `IAM` and open the service.

You need two roles:

- ECS task execution role
- ECS application role

### 20.1 Create the ECS task execution role

1. Open `Roles`
2. Click `Create role`
3. Trusted entity type: `AWS service`
4. Use case: search for and choose `Elastic Container Service Task`
5. Click `Next`

Attach permissions:

- `AmazonECSTaskExecutionRolePolicy`

Also add permission for Secrets Manager:

- `SecretsManagerReadWrite`

For a stricter real-world setup you would use a custom read-only policy, but for classroom simplicity this is acceptable.

Role name:

- `openai-image-prod-ecs-execution-role`

Click `Create role`

### 20.2 Create the ECS application role

1. Click `Create role`
2. Trusted entity type: `AWS service`
3. Use case: `Elastic Container Service Task`
4. Click `Next`

Permissions:

- for a classroom demo, create a custom inline policy after creating the role

Role name:

- `openai-image-prod-ecs-app-role`

Click `Create role`

Now open the new role and add an inline policy.

Policy permissions should include:

- `sqs:SendMessage`
- `sqs:ReceiveMessage`
- `sqs:DeleteMessage`
- `sqs:GetQueueAttributes`
- `sqs:ChangeMessageVisibility`
- `s3:PutObject`
- `s3:GetObject`

For a beginner-friendly classroom demo, you can use broader resource scope if needed.

## 21. Create the ECS Cluster

Search for `ECS` and open the service.

1. In the left menu, click `Clusters`
2. Click `Create cluster`

Enter:

- Cluster name: `openai-image-prod-cluster`

Infrastructure:

- use `AWS Fargate (serverless)`

Click `Create`

Save the cluster name.

## 22. Create the Application Load Balancer

Search for `EC2` and then open `Load Balancers`.

1. Click `Create load balancer`
2. Choose `Application Load Balancer`
3. Click `Create`

Basic configuration:

- Load balancer name: `openai-image-prod-alb`
- Scheme: `Internet-facing`
- IP address type: `IPv4`

Network mapping:

- VPC: `openai-image-prod-vpc`
- Availability Zones:
  - select `ap-south-1a` with `openai-image-prod-public-1`
  - select `ap-south-1b` with `openai-image-prod-public-2`

Security groups:

- select `openai-image-prod-alb-sg`

Listeners and routing:

- Listener protocol: `HTTP`
- Port: `80`

For the default target group, you can create one later if the screen requires it.

Click `Create load balancer`

After creation, save:

- ALB ARN
- ALB DNS name

## 23. Create the Target Groups

Still in `EC2`, open `Target Groups`.

You need two target groups.

### 23.1 Frontend target group

1. Click `Create target group`

Enter:

- Choose target type: `IP addresses`
- Target group name: `openai-image-prod-frontend-tg`
- Protocol: `HTTP`
- Port: `80`
- VPC: `openai-image-prod-vpc`

Health checks:

- Protocol: `HTTP`
- Path: `/`
- Advanced health check settings can stay at defaults

Click `Next`

Do not register targets manually now, because ECS will do that later.

Click `Create target group`

### 23.2 Backend target group

Create another target group with:

- Choose target type: `IP addresses`
- Target group name: `openai-image-prod-backend-tg`
- Protocol: `HTTP`
- Port: `8000`
- VPC: `openai-image-prod-vpc`

Health checks:

- Protocol: `HTTP`
- Path: `/api/health`

Click `Create target group`

## 24. Request the ACM Certificate

Search for `Certificate Manager` or `ACM`.

1. Click `Request`
2. Choose `Request a public certificate`
3. Click `Next`

Domain names:

- `images.example.com`

Validation method:

- `DNS validation`

Algorithm:

- keep default

Click `Request`

After the certificate is created:

1. Open it
2. Copy the `CNAME name` and `CNAME value` shown for DNS validation
3. Save the certificate ARN

Do not continue to the HTTPS listener until this certificate becomes:

- `Issued`

## 25. Create or Confirm the Route 53 Hosted Zone

Search for `Route 53`.

1. Open `Hosted zones`

If your domain already exists:

- open the hosted zone for `example.com`

If it does not exist:

1. Click `Create hosted zone`
2. Domain name: `example.com`
3. Type: `Public hosted zone`
4. Click `Create hosted zone`

## 26. Create the ACM Validation Record

Inside the `example.com` hosted zone:

1. Click `Create record`

Enter the record exactly as ACM provided:

- Record name: the ACM `CNAME name`
- Record type: `CNAME`
- Value: the ACM `CNAME value`

Click `Create records`

Wait a few minutes and refresh the ACM certificate page until the status becomes:

- `Issued`

## 27. Create CloudWatch Log Groups First

Search for `CloudWatch`, then open `Log groups`.

Create three log groups:

1. `/ecs/openai-image-prod/frontend`
2. `/ecs/openai-image-prod/backend`
3. `/ecs/openai-image-prod/worker`

For each:

1. Click `Create log group`
2. Enter the name
3. Click `Create`

These names will be used in ECS task definitions.

## 28. Create the ECS Task Definitions

Return to the `ECS` service.

Open:

- `Task definitions`

You will create three task definitions using `Fargate`.

### 28.1 Frontend task definition

1. Click `Create new task definition`
2. Launch type: `AWS Fargate`

Task definition configuration:

- Task definition family: `openai-image-prod-frontend`
- Task role: `openai-image-prod-ecs-app-role`
- Task execution role: `openai-image-prod-ecs-execution-role`
- Operating system: `Linux`
- CPU: `0.25 vCPU`
- Memory: `0.5 GB`

Add container:

- Container name: `frontend`
- Image URI: frontend ECR repository URI with tag
- Essential container: enabled

Port mappings:

- Container port: `80`
- Protocol: `TCP`

Log collection:

- Use log collection: enabled
- Log driver: `awslogs`
- Log group: `/ecs/openai-image-prod/frontend`
- Region: `ap-south-1`
- Stream prefix: `ecs`

Click `Create`

### 28.2 Backend task definition

Create another task definition:

- Family: `openai-image-prod-backend`
- Task role: `openai-image-prod-ecs-app-role`
- Task execution role: `openai-image-prod-ecs-execution-role`
- CPU: `0.5 vCPU`
- Memory: `1 GB`

Container:

- Container name: `backend`
- Image URI: backend ECR image URI
- Essential: enabled

Port mappings:

- Container port: `8000`

Environment variables:

- `AWS_REGION` = `ap-south-1`
- `SQS_QUEUE_URL` = your main queue URL
- `S3_BUCKET_NAME` = `openai-image-prod-images`
- `OPENAI_IMAGE_MODEL` = `gpt-image-2`
- `OPENAI_IMAGE_OUTPUT_FORMAT` = `png`
- `CORS_ORIGINS` = `*`

Secrets:

- `OPENAI_API_KEY` from `openai-image-prod/openai-api-key`
- `DATABASE_URL` from `openai-image-prod/database-url`

Logs:

- Log group: `/ecs/openai-image-prod/backend`
- Region: `ap-south-1`
- Stream prefix: `ecs`

Click `Create`

### 28.3 Worker task definition

Create another task definition:

- Family: `openai-image-prod-worker`
- Task role: `openai-image-prod-ecs-app-role`
- Task execution role: `openai-image-prod-ecs-execution-role`
- CPU: `0.5 vCPU`
- Memory: `1 GB`

Container:

- Container name: `worker`
- Image URI: worker ECR image URI

No public port mapping is required.

Environment variables:

- `AWS_REGION` = `ap-south-1`
- `SQS_QUEUE_URL` = your main queue URL
- `S3_BUCKET_NAME` = `openai-image-prod-images`
- `OPENAI_IMAGE_MODEL` = `gpt-image-2`
- `OPENAI_IMAGE_OUTPUT_FORMAT` = `png`
- `WORKER_POLL_SECONDS` = `20`
- `WORKER_MAX_ATTEMPTS` = `3`

Secrets:

- `OPENAI_API_KEY` from `openai-image-prod/openai-api-key`
- `DATABASE_URL` from `openai-image-prod/database-url`

Logs:

- Log group: `/ecs/openai-image-prod/worker`
- Region: `ap-south-1`
- Stream prefix: `ecs`

Click `Create`

## 29. Create the ECS Services

Open the ECS cluster:

- `openai-image-prod-cluster`

You will create three services.

### 29.1 Frontend service

1. Click `Create`

Environment:

- Launch type: `Fargate`

Deployment configuration:

- Application type: `Service`
- Family: `openai-image-prod-frontend`
- Revision: latest
- Service name: `openai-image-prod-frontend-service`
- Desired tasks: `2`

Networking:

- VPC: `openai-image-prod-vpc`
- Subnets:
  - `openai-image-prod-private-1`
  - `openai-image-prod-private-2`
- Security group:
  - `openai-image-prod-frontend-sg`
- Public IP: `Off`

Load balancing:

- Use load balancing: `Yes`
- Load balancer type: `Application Load Balancer`
- Use existing load balancer
- Select `openai-image-prod-alb`
- Container: `frontend:80`
- Listener: `HTTP:80`
- Target group: `openai-image-prod-frontend-tg`

Click `Create`

### 29.2 Backend service

Create another service:

- Family: `openai-image-prod-backend`
- Service name: `openai-image-prod-backend-service`
- Desired tasks: `2`

Networking:

- same VPC
- same private subnets
- security group: `openai-image-prod-backend-sg`
- Public IP: `Off`

Load balancing:

- Use existing load balancer: `openai-image-prod-alb`
- Container: `backend:8000`
- Listener: `HTTP:80`
- Target group: `openai-image-prod-backend-tg`

Click `Create`

### 29.3 Worker service

Create the worker service:

- Family: `openai-image-prod-worker`
- Service name: `openai-image-prod-worker-service`
- Desired tasks: `1`

Networking:

- private subnets
- security group: `openai-image-prod-worker-sg`
- Public IP: `Off`

Load balancing:

- do not attach a load balancer

Click `Create`

## 30. Configure the ALB Listener Rules

Go back to `EC2` -> `Load Balancers`.

1. Open `openai-image-prod-alb`
2. Open the `Listeners` tab
3. Open the `HTTP:80` listener
4. Click `View/edit rules`

You want:

- `/api/*` -> backend target group
- default -> frontend target group

If the default rule currently forwards somewhere else:

1. Edit it
2. Set default action to forward to `openai-image-prod-frontend-tg`

Then create a new rule:

1. Click `Insert rule`
2. Add condition:
   - `Path`
   - value: `/api/*`
3. Add action:
   - `Forward to`
   - `openai-image-prod-backend-tg`
4. Save rules

## 31. Add HTTPS to the ALB

Once the ACM certificate is `Issued`:

1. Open the ALB
2. Open `Listeners`
3. Click `Add listener`

Enter:

- Protocol: `HTTPS`
- Port: `443`

Default action:

- Forward to `openai-image-prod-frontend-tg`

Security policy:

- leave the default recommended policy

Certificate:

- select the ACM certificate for `images.example.com`

Click `Add`

Now edit the HTTP listener:

1. Open the `HTTP:80` listener
2. Edit its default action if you want redirection
3. Set action to redirect to:
   - Protocol: `HTTPS`
   - Port: `443`
   - Status code: `HTTP_301`

Then recreate the `/api/*` rule on the `HTTPS:443` listener too, if needed, so API traffic still routes to the backend target group.

## 32. Create the Route 53 Alias Record

Go to `Route 53` -> `Hosted zones` -> `example.com`

1. Click `Create record`

Enter:

- Record name: `images`
- Record type: `A`
- Alias: `On`
- Route traffic to: `Alias to Application and Classic Load Balancer`
- Choose region: `ap-south-1`
- Choose load balancer: `openai-image-prod-alb`

Click `Create records`

After DNS propagates, your frontend should be reachable at:

- `https://images.example.com`

## 33. Verify ECS Targets Become Healthy

Go to `EC2` -> `Target Groups`

Check:

- `openai-image-prod-frontend-tg`
- `openai-image-prod-backend-tg`

Open each target group and then the `Targets` tab.

Wait until targets show:

- `healthy`

If the backend target group is unhealthy:

1. open CloudWatch logs for the backend
2. confirm the app started correctly
3. confirm `SQS_QUEUE_URL`, `DATABASE_URL`, and `S3_BUCKET_NAME` were entered correctly
4. confirm the backend security group allows port `8000` from the ALB security group

## 34. Configure CloudWatch Alarms

Search for `CloudWatch`.

### 34.1 Queue depth alarm

1. Open `Alarms`
2. Click `Create alarm`
3. Select metric
4. Choose namespace `SQS`
5. Choose metric `ApproximateNumberOfMessagesVisible`
6. Choose the main queue
7. Click `Select metric`

Set:

- Statistic: `Average`
- Period: `1 minute`
- Threshold type: `Static`
- Whenever metric is: `Greater than`
- Threshold value: `5`

Alarm name:

- `openai-image-prod-queue-depth-high`

Create the alarm

### 34.2 DLQ alarm

Create another alarm:

- Metric: `ApproximateNumberOfMessagesVisible`
- Queue: DLQ
- Threshold: `Greater than 0`
- Alarm name: `openai-image-prod-dlq-messages`

### 34.3 Backend unhealthy hosts alarm

Create another alarm from the `ApplicationELB` metrics:

- Metric: `UnHealthyHostCount`
- Target group: backend target group
- Threshold: `Greater than 0`
- Alarm name: `openai-image-prod-backend-unhealthy-hosts`

## 35. Configure ECS Auto Scaling

### 35.1 Frontend service auto scaling

Open ECS -> cluster -> frontend service.

1. Open the service
2. Click `Update`
3. Go to the scaling section
4. Enable service auto scaling

Set:

- Minimum tasks: `2`
- Desired tasks: `2`
- Maximum tasks: `4`

Scaling policy:

- Policy type: `Target tracking`
- Metric: `ECS service average CPU utilization`
- Target value: `60`

Save changes

### 35.2 Backend service auto scaling

Repeat for the backend service:

- Minimum tasks: `2`
- Desired tasks: `2`
- Maximum tasks: `4`
- Target CPU utilization: `60`

### 35.3 Worker service auto scaling

For the worker, explain that queue-based scaling is more meaningful than web traffic scaling.

In a simple classroom setup:

1. enable service auto scaling
2. set minimum tasks to `1`
3. set maximum tasks to `5`

Then explain that production queue-based scaling would be connected to CloudWatch alarms on SQS queue depth.

## 36. Test the Full Deployment

Once everything is deployed:

1. Open `https://images.example.com`
2. Confirm the frontend loads
3. Open `https://images.example.com/api/health`
4. Confirm the backend health endpoint responds
5. Submit a new image generation request
6. Go to `SQS` and confirm messages appear
7. Go to `CloudWatch Logs` and inspect the worker log group
8. Confirm the worker processes the message
9. Go to `S3` and confirm an image object appears
10. Return to the UI and confirm the final image displays

## 37. Failure Testing for Students

To teach failure handling, do this only in a test environment:

1. change the OpenAI key secret to an invalid value
2. submit a new image request
3. observe retries in worker logs
4. observe the message move to the DLQ after repeated failure
5. restore the valid OpenAI key after the demo

This helps students understand:

- why queues matter
- why DLQs matter
- how logs and alarms help debugging

## 38. Common Troubleshooting Checks

If something does not work, check these first.

### 38.1 Frontend does not load

Check:

- ALB is internet-facing
- public subnets are attached to the ALB
- Route 53 alias points to the ALB
- frontend targets are healthy

### 38.2 Backend health check fails

Check:

- backend service is running
- backend task logs show successful startup
- target group health path is `/api/health`
- backend security group allows port `8000` from the ALB security group
- database and SQS settings are correct

### 38.3 Worker is not processing messages

Check:

- worker service has running tasks
- worker task role has SQS permissions
- `SQS_QUEUE_URL` is correct
- worker logs in CloudWatch show polling activity

### 38.4 Images are not appearing in S3

Check:

- worker role has `s3:PutObject`
- bucket name is correct
- OpenAI API key is valid

## 39. Suggested Classroom Walkthrough

Use this order during a live demo:

1. Show the VPC, subnets, and route tables
2. Show the security groups
3. Show the S3 bucket
4. Show the SQS queue and DLQ
5. Show the RDS instance
6. Show the Secrets Manager secrets
7. Show the ECR repositories and images
8. Show the ECS cluster, task definitions, and services
9. Show the ALB and target groups
10. Show the ACM certificate and Route 53 record
11. Trigger an image generation request
12. Show the queue depth, worker logs, and final image in S3
13. Show the DLQ and alarms
14. Explain scaling

## 40. Summary

This guide walks through the full AWS Console deployment with explicit values and exact resource creation steps for:

1. `VPC`
2. `Security Groups`
3. `S3`
4. `SQS FIFO + DLQ`
5. `RDS PostgreSQL`
6. `Secrets Manager`
7. `ECR`
8. `ECS Fargate`
9. `ALB`
10. `ACM`
11. `Route 53`
12. `CloudWatch`
13. `Auto Scaling`

If you follow the steps in order, you should end up with a complete student-facing AWS deployment for this project.
