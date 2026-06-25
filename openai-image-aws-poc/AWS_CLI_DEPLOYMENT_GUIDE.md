# AWS CLI Deployment Guide

This guide shows one way to deploy the OpenAI Image Generator POC entirely from the AWS CLI.

It is designed for students who want to see the full deployment process from the terminal using:

- `ECR`
- `ECS Fargate`
- `ALB`
- `Route 53`
- `ACM`
- `CloudWatch`
- `Secrets Manager`
- `SQS FIFO` with a `DLQ`
- `Application Auto Scaling`

This guide assumes:

- you are using a Linux or macOS shell
- `aws` CLI is installed and configured
- `docker` is installed
- you already own a domain in `Route 53` or can create a hosted zone for one

## 1. Export Variables

Set these first and change the placeholder values.

```bash
export AWS_REGION=ap-south-1
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

export PROJECT_NAME=openai-image-poc
export ENV_NAME=prod
export APP_PREFIX=${PROJECT_NAME}-${ENV_NAME}

export VPC_CIDR=10.0.0.0/16
export PUBLIC_SUBNET_1_CIDR=10.0.1.0/24
export PUBLIC_SUBNET_2_CIDR=10.0.2.0/24
export PRIVATE_SUBNET_1_CIDR=10.0.11.0/24
export PRIVATE_SUBNET_2_CIDR=10.0.12.0/24

export DB_NAME=imageapp
export DB_USER=imageapp
export DB_PASSWORD='ChangeThisPassword123!'

export OPENAI_API_KEY='sk-your-key-here'
export S3_BUCKET_NAME=${APP_PREFIX}-images

export ROOT_DOMAIN=example.com
export APP_DOMAIN=images.${ROOT_DOMAIN}

export FRONTEND_REPO=${PROJECT_NAME}-frontend
export BACKEND_REPO=${PROJECT_NAME}-api
export WORKER_REPO=${PROJECT_NAME}-worker

export FRONTEND_IMAGE=${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${FRONTEND_REPO}:1.0
export BACKEND_IMAGE=${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${BACKEND_REPO}:1.0
export WORKER_IMAGE=${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${WORKER_REPO}:1.0
```

Set availability zones:

```bash
export AZ1=$(aws ec2 describe-availability-zones --region ${AWS_REGION} --query 'AvailabilityZones[0].ZoneName' --output text)
export AZ2=$(aws ec2 describe-availability-zones --region ${AWS_REGION} --query 'AvailabilityZones[1].ZoneName' --output text)
```

## 2. Create Networking

### 2.1 Create the VPC

```bash
export VPC_ID=$(aws ec2 create-vpc \
  --region ${AWS_REGION} \
  --cidr-block ${VPC_CIDR} \
  --query 'Vpc.VpcId' \
  --output text)
```

```bash
aws ec2 modify-vpc-attribute --vpc-id ${VPC_ID} --enable-dns-support '{"Value":true}'
aws ec2 modify-vpc-attribute --vpc-id ${VPC_ID} --enable-dns-hostnames '{"Value":true}'
aws ec2 create-tags --resources ${VPC_ID} --tags Key=Name,Value=${APP_PREFIX}-vpc
```

### 2.2 Create subnets

```bash
export PUBLIC_SUBNET_1_ID=$(aws ec2 create-subnet \
  --vpc-id ${VPC_ID} \
  --cidr-block ${PUBLIC_SUBNET_1_CIDR} \
  --availability-zone ${AZ1} \
  --query 'Subnet.SubnetId' \
  --output text)

export PUBLIC_SUBNET_2_ID=$(aws ec2 create-subnet \
  --vpc-id ${VPC_ID} \
  --cidr-block ${PUBLIC_SUBNET_2_CIDR} \
  --availability-zone ${AZ2} \
  --query 'Subnet.SubnetId' \
  --output text)

export PRIVATE_SUBNET_1_ID=$(aws ec2 create-subnet \
  --vpc-id ${VPC_ID} \
  --cidr-block ${PRIVATE_SUBNET_1_CIDR} \
  --availability-zone ${AZ1} \
  --query 'Subnet.SubnetId' \
  --output text)

export PRIVATE_SUBNET_2_ID=$(aws ec2 create-subnet \
  --vpc-id ${VPC_ID} \
  --cidr-block ${PRIVATE_SUBNET_2_CIDR} \
  --availability-zone ${AZ2} \
  --query 'Subnet.SubnetId' \
  --output text)
```

Enable public IP mapping on public subnets:

```bash
aws ec2 modify-subnet-attribute --subnet-id ${PUBLIC_SUBNET_1_ID} --map-public-ip-on-launch
aws ec2 modify-subnet-attribute --subnet-id ${PUBLIC_SUBNET_2_ID} --map-public-ip-on-launch
```

### 2.3 Create internet gateway and route table

```bash
export IGW_ID=$(aws ec2 create-internet-gateway --query 'InternetGateway.InternetGatewayId' --output text)
aws ec2 attach-internet-gateway --internet-gateway-id ${IGW_ID} --vpc-id ${VPC_ID}
aws ec2 create-tags --resources ${IGW_ID} --tags Key=Name,Value=${APP_PREFIX}-igw
```

```bash
export PUBLIC_RT_ID=$(aws ec2 create-route-table --vpc-id ${VPC_ID} --query 'RouteTable.RouteTableId' --output text)
aws ec2 create-route --route-table-id ${PUBLIC_RT_ID} --destination-cidr-block 0.0.0.0/0 --gateway-id ${IGW_ID}
aws ec2 associate-route-table --subnet-id ${PUBLIC_SUBNET_1_ID} --route-table-id ${PUBLIC_RT_ID}
aws ec2 associate-route-table --subnet-id ${PUBLIC_SUBNET_2_ID} --route-table-id ${PUBLIC_RT_ID}
```

### 2.4 Create NAT gateway for private outbound access

Allocate an Elastic IP and create a NAT gateway in the first public subnet:

```bash
export EIP_ALLOC_ID=$(aws ec2 allocate-address --domain vpc --query 'AllocationId' --output text)
export NAT_GW_ID=$(aws ec2 create-nat-gateway \
  --subnet-id ${PUBLIC_SUBNET_1_ID} \
  --allocation-id ${EIP_ALLOC_ID} \
  --query 'NatGateway.NatGatewayId' \
  --output text)
```

Wait for the NAT gateway:

```bash
aws ec2 wait nat-gateway-available --nat-gateway-ids ${NAT_GW_ID}
```

Create a private route table:

```bash
export PRIVATE_RT_ID=$(aws ec2 create-route-table --vpc-id ${VPC_ID} --query 'RouteTable.RouteTableId' --output text)
aws ec2 create-route --route-table-id ${PRIVATE_RT_ID} --destination-cidr-block 0.0.0.0/0 --nat-gateway-id ${NAT_GW_ID}
aws ec2 associate-route-table --subnet-id ${PRIVATE_SUBNET_1_ID} --route-table-id ${PRIVATE_RT_ID}
aws ec2 associate-route-table --subnet-id ${PRIVATE_SUBNET_2_ID} --route-table-id ${PRIVATE_RT_ID}
```

## 3. Create Security Groups

```bash
export ALB_SG_ID=$(aws ec2 create-security-group \
  --group-name ${APP_PREFIX}-alb-sg \
  --description "ALB security group" \
  --vpc-id ${VPC_ID} \
  --query 'GroupId' \
  --output text)

export FRONTEND_SG_ID=$(aws ec2 create-security-group \
  --group-name ${APP_PREFIX}-frontend-sg \
  --description "Frontend ECS security group" \
  --vpc-id ${VPC_ID} \
  --query 'GroupId' \
  --output text)

export BACKEND_SG_ID=$(aws ec2 create-security-group \
  --group-name ${APP_PREFIX}-backend-sg \
  --description "Backend ECS security group" \
  --vpc-id ${VPC_ID} \
  --query 'GroupId' \
  --output text)

export WORKER_SG_ID=$(aws ec2 create-security-group \
  --group-name ${APP_PREFIX}-worker-sg \
  --description "Worker ECS security group" \
  --vpc-id ${VPC_ID} \
  --query 'GroupId' \
  --output text)

export DB_SG_ID=$(aws ec2 create-security-group \
  --group-name ${APP_PREFIX}-db-sg \
  --description "RDS security group" \
  --vpc-id ${VPC_ID} \
  --query 'GroupId' \
  --output text)
```

Allow ALB traffic:

```bash
aws ec2 authorize-security-group-ingress --group-id ${ALB_SG_ID} --protocol tcp --port 80 --cidr 0.0.0.0/0
aws ec2 authorize-security-group-ingress --group-id ${ALB_SG_ID} --protocol tcp --port 443 --cidr 0.0.0.0/0
```

Allow ALB to reach frontend and backend:

```bash
aws ec2 authorize-security-group-ingress --group-id ${FRONTEND_SG_ID} --protocol tcp --port 80 --source-group ${ALB_SG_ID}
aws ec2 authorize-security-group-ingress --group-id ${BACKEND_SG_ID} --protocol tcp --port 8000 --source-group ${ALB_SG_ID}
```

Allow ECS tasks to reach the database:

```bash
aws ec2 authorize-security-group-ingress --group-id ${DB_SG_ID} --protocol tcp --port 5432 --source-group ${BACKEND_SG_ID}
aws ec2 authorize-security-group-ingress --group-id ${DB_SG_ID} --protocol tcp --port 5432 --source-group ${WORKER_SG_ID}
```

## 4. Create S3 Bucket

```bash
aws s3api create-bucket \
  --bucket ${S3_BUCKET_NAME} \
  --region ${AWS_REGION} \
  --create-bucket-configuration LocationConstraint=${AWS_REGION}
```

Block public access:

```bash
aws s3api put-public-access-block \
  --bucket ${S3_BUCKET_NAME} \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
```

Enable default encryption:

```bash
aws s3api put-bucket-encryption \
  --bucket ${S3_BUCKET_NAME} \
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
```

## 5. Create SQS FIFO Queue and DLQ

Create the DLQ first:

```bash
export DLQ_URL=$(aws sqs create-queue \
  --queue-name ${APP_PREFIX}-image-generation-dlq.fifo \
  --attributes FifoQueue=true,ContentBasedDeduplication=false \
  --query 'QueueUrl' \
  --output text)
```

```bash
export DLQ_ARN=$(aws sqs get-queue-attributes \
  --queue-url ${DLQ_URL} \
  --attribute-names QueueArn \
  --query 'Attributes.QueueArn' \
  --output text)
```

Create the main queue:

```bash
export MAIN_QUEUE_URL=$(aws sqs create-queue \
  --queue-name ${APP_PREFIX}-image-generation.fifo \
  --attributes FifoQueue=true,ContentBasedDeduplication=false,VisibilityTimeout=180,RedrivePolicy="{\"deadLetterTargetArn\":\"${DLQ_ARN}\",\"maxReceiveCount\":\"3\"}" \
  --query 'QueueUrl' \
  --output text)
```

## 6. Create Secrets in Secrets Manager

Create the OpenAI secret:

```bash
export OPENAI_SECRET_ARN=$(aws secretsmanager create-secret \
  --name ${APP_PREFIX}/openai-api-key \
  --secret-string "${OPENAI_API_KEY}" \
  --query 'ARN' \
  --output text)
```

Create the DB subnet group:

```bash
aws rds create-db-subnet-group \
  --db-subnet-group-name ${APP_PREFIX}-db-subnet-group \
  --db-subnet-group-description "Subnet group for ${APP_PREFIX}" \
  --subnet-ids ${PRIVATE_SUBNET_1_ID} ${PRIVATE_SUBNET_2_ID}
```

## 7. Create the RDS PostgreSQL Database

```bash
aws rds create-db-instance \
  --db-instance-identifier ${APP_PREFIX}-postgres \
  --engine postgres \
  --db-instance-class db.t3.micro \
  --allocated-storage 20 \
  --master-username ${DB_USER} \
  --master-user-password ${DB_PASSWORD} \
  --db-name ${DB_NAME} \
  --vpc-security-group-ids ${DB_SG_ID} \
  --db-subnet-group-name ${APP_PREFIX}-db-subnet-group \
  --backup-retention-period 1 \
  --no-publicly-accessible \
  --region ${AWS_REGION}
```

Wait for the DB:

```bash
aws rds wait db-instance-available --db-instance-identifier ${APP_PREFIX}-postgres
```

Get the endpoint:

```bash
export DB_ENDPOINT=$(aws rds describe-db-instances \
  --db-instance-identifier ${APP_PREFIX}-postgres \
  --query 'DBInstances[0].Endpoint.Address' \
  --output text)
```

Create the database URL secret:

```bash
export DATABASE_URL="postgresql+psycopg2://${DB_USER}:${DB_PASSWORD}@${DB_ENDPOINT}:5432/${DB_NAME}"

export DATABASE_SECRET_ARN=$(aws secretsmanager create-secret \
  --name ${APP_PREFIX}/database-url \
  --secret-string "${DATABASE_URL}" \
  --query 'ARN' \
  --output text)
```

## 8. Create ECR Repositories

```bash
aws ecr create-repository --repository-name ${FRONTEND_REPO}
aws ecr create-repository --repository-name ${BACKEND_REPO}
aws ecr create-repository --repository-name ${WORKER_REPO}
```

Login Docker to ECR:

```bash
aws ecr get-login-password --region ${AWS_REGION} | docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com
```

## 9. Build and Push Images

Run these from the repository root:

```bash
docker build -f Dockerfile.api -t ${BACKEND_REPO}:1.0 .
docker build -f Dockerfile.worker -t ${WORKER_REPO}:1.0 .
docker build -t ${FRONTEND_REPO}:1.0 ./frontend
```

Tag images:

```bash
docker tag ${BACKEND_REPO}:1.0 ${BACKEND_IMAGE}
docker tag ${WORKER_REPO}:1.0 ${WORKER_IMAGE}
docker tag ${FRONTEND_REPO}:1.0 ${FRONTEND_IMAGE}
```

Push images:

```bash
docker push ${BACKEND_IMAGE}
docker push ${WORKER_IMAGE}
docker push ${FRONTEND_IMAGE}
```

## 10. Create CloudWatch Log Groups

```bash
aws logs create-log-group --log-group-name /ecs/${APP_PREFIX}/frontend
aws logs create-log-group --log-group-name /ecs/${APP_PREFIX}/backend
aws logs create-log-group --log-group-name /ecs/${APP_PREFIX}/worker
```

## 11. Create IAM Roles

### 11.1 Task execution role

Create a trust policy file named `ecs-task-execution-trust.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "ecs-tasks.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

Create the role:

```bash
aws iam create-role \
  --role-name ${APP_PREFIX}-ecs-execution-role \
  --assume-role-policy-document file://ecs-task-execution-trust.json
```

Attach managed policies:

```bash
aws iam attach-role-policy \
  --role-name ${APP_PREFIX}-ecs-execution-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
```

```bash
aws iam attach-role-policy \
  --role-name ${APP_PREFIX}-ecs-execution-role \
  --policy-arn arn:aws:iam::aws:policy/SecretsManagerReadWrite
```

### 11.2 Application task role

Create a trust policy file named `ecs-task-role-trust.json` with the same contents as above, then:

```bash
aws iam create-role \
  --role-name ${APP_PREFIX}-ecs-app-role \
  --assume-role-policy-document file://ecs-task-role-trust.json
```

Create an inline policy file named `ecs-app-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "sqs:SendMessage",
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes",
        "sqs:ChangeMessageVisibility"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject"
      ],
      "Resource": "arn:aws:s3:::*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue"
      ],
      "Resource": "*"
    }
  ]
}
```

Attach the policy:

```bash
aws iam put-role-policy \
  --role-name ${APP_PREFIX}-ecs-app-role \
  --policy-name ${APP_PREFIX}-ecs-app-policy \
  --policy-document file://ecs-app-policy.json
```

## 12. Create ECS Cluster

```bash
aws ecs create-cluster --cluster-name ${APP_PREFIX}-cluster
export ECS_CLUSTER_NAME=${APP_PREFIX}-cluster
```

## 13. Register ECS Task Definitions

Create `backend-task-definition.json`:

```json
{
  "family": "openai-image-backend",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "executionRoleArn": "arn:aws:iam::AWS_ACCOUNT_ID:role/EXECUTION_ROLE_NAME",
  "taskRoleArn": "arn:aws:iam::AWS_ACCOUNT_ID:role/APP_ROLE_NAME",
  "containerDefinitions": [
    {
      "name": "backend",
      "image": "BACKEND_IMAGE_URI",
      "essential": true,
      "portMappings": [
        {
          "containerPort": 8000,
          "protocol": "tcp"
        }
      ],
      "environment": [
        { "name": "AWS_REGION", "value": "ap-south-1" },
        { "name": "SQS_QUEUE_URL", "value": "MAIN_QUEUE_URL" },
        { "name": "S3_BUCKET_NAME", "value": "S3_BUCKET_NAME" },
        { "name": "OPENAI_IMAGE_MODEL", "value": "gpt-image-2" },
        { "name": "OPENAI_IMAGE_OUTPUT_FORMAT", "value": "png" },
        { "name": "CORS_ORIGINS", "value": "*" }
      ],
      "secrets": [
        { "name": "OPENAI_API_KEY", "valueFrom": "OPENAI_SECRET_ARN" },
        { "name": "DATABASE_URL", "valueFrom": "DATABASE_SECRET_ARN" }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/APP_PREFIX/backend",
          "awslogs-region": "ap-south-1",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ]
}
```

Create `worker-task-definition.json`:

```json
{
  "family": "openai-image-worker",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "executionRoleArn": "arn:aws:iam::AWS_ACCOUNT_ID:role/EXECUTION_ROLE_NAME",
  "taskRoleArn": "arn:aws:iam::AWS_ACCOUNT_ID:role/APP_ROLE_NAME",
  "containerDefinitions": [
    {
      "name": "worker",
      "image": "WORKER_IMAGE_URI",
      "essential": true,
      "environment": [
        { "name": "AWS_REGION", "value": "ap-south-1" },
        { "name": "SQS_QUEUE_URL", "value": "MAIN_QUEUE_URL" },
        { "name": "S3_BUCKET_NAME", "value": "S3_BUCKET_NAME" },
        { "name": "WORKER_POLL_SECONDS", "value": "20" },
        { "name": "WORKER_MAX_ATTEMPTS", "value": "3" }
      ],
      "secrets": [
        { "name": "OPENAI_API_KEY", "valueFrom": "OPENAI_SECRET_ARN" },
        { "name": "DATABASE_URL", "valueFrom": "DATABASE_SECRET_ARN" }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/APP_PREFIX/worker",
          "awslogs-region": "ap-south-1",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ]
}
```

Create `frontend-task-definition.json`:

```json
{
  "family": "openai-image-frontend",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "256",
  "memory": "512",
  "executionRoleArn": "arn:aws:iam::AWS_ACCOUNT_ID:role/EXECUTION_ROLE_NAME",
  "taskRoleArn": "arn:aws:iam::AWS_ACCOUNT_ID:role/APP_ROLE_NAME",
  "containerDefinitions": [
    {
      "name": "frontend",
      "image": "FRONTEND_IMAGE_URI",
      "essential": true,
      "portMappings": [
        {
          "containerPort": 80,
          "protocol": "tcp"
        }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/APP_PREFIX/frontend",
          "awslogs-region": "ap-south-1",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ]
}
```

Replace placeholders in those files before registering them.

Register task definitions:

```bash
aws ecs register-task-definition --cli-input-json file://backend-task-definition.json
aws ecs register-task-definition --cli-input-json file://worker-task-definition.json
aws ecs register-task-definition --cli-input-json file://frontend-task-definition.json
```

## 14. Create the ALB and Target Groups

Create the ALB:

```bash
export ALB_ARN=$(aws elbv2 create-load-balancer \
  --name ${APP_PREFIX}-alb \
  --subnets ${PUBLIC_SUBNET_1_ID} ${PUBLIC_SUBNET_2_ID} \
  --security-groups ${ALB_SG_ID} \
  --type application \
  --query 'LoadBalancers[0].LoadBalancerArn' \
  --output text)
```

Get the ALB DNS name:

```bash
export ALB_DNS_NAME=$(aws elbv2 describe-load-balancers \
  --load-balancer-arns ${ALB_ARN} \
  --query 'LoadBalancers[0].DNSName' \
  --output text)
```

Create target groups:

```bash
export FRONTEND_TG_ARN=$(aws elbv2 create-target-group \
  --name ${PROJECT_NAME:0:20}-fe-tg \
  --protocol HTTP \
  --port 80 \
  --vpc-id ${VPC_ID} \
  --target-type ip \
  --health-check-path / \
  --query 'TargetGroups[0].TargetGroupArn' \
  --output text)

export BACKEND_TG_ARN=$(aws elbv2 create-target-group \
  --name ${PROJECT_NAME:0:20}-be-tg \
  --protocol HTTP \
  --port 8000 \
  --vpc-id ${VPC_ID} \
  --target-type ip \
  --health-check-path /api/health \
  --query 'TargetGroups[0].TargetGroupArn' \
  --output text)
```

Create the HTTP listener:

```bash
export HTTP_LISTENER_ARN=$(aws elbv2 create-listener \
  --load-balancer-arn ${ALB_ARN} \
  --protocol HTTP \
  --port 80 \
  --default-actions Type=forward,TargetGroupArn=${FRONTEND_TG_ARN} \
  --query 'Listeners[0].ListenerArn' \
  --output text)
```

Add path routing for the API:

```bash
aws elbv2 create-rule \
  --listener-arn ${HTTP_LISTENER_ARN} \
  --priority 10 \
  --conditions Field=path-pattern,Values='/api/*' \
  --actions Type=forward,TargetGroupArn=${BACKEND_TG_ARN}
```

## 15. Request ACM Certificate

Request the certificate:

```bash
export CERT_ARN=$(aws acm request-certificate \
  --domain-name ${APP_DOMAIN} \
  --validation-method DNS \
  --query 'CertificateArn' \
  --output text)
```

Fetch the validation record:

```bash
aws acm describe-certificate --certificate-arn ${CERT_ARN}
```

Use the returned DNS validation record to create a `CNAME` in Route 53.

## 16. Create or Find the Route 53 Hosted Zone

If the hosted zone already exists:

```bash
export HOSTED_ZONE_ID=$(aws route53 list-hosted-zones-by-name \
  --dns-name ${ROOT_DOMAIN} \
  --query 'HostedZones[0].Id' \
  --output text | sed 's|/hostedzone/||')
```

If it does not exist, create it:

```bash
aws route53 create-hosted-zone \
  --name ${ROOT_DOMAIN} \
  --caller-reference $(date +%s)
```

## 17. Create the Route 53 Alias Record

Create `route53-alias.json`:

```json
{
  "Comment": "Alias record for ALB",
  "Changes": [
    {
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "images.example.com",
        "Type": "A",
        "AliasTarget": {
          "HostedZoneId": "ALB_HOSTED_ZONE_ID",
          "DNSName": "dualstack.ALB_DNS_NAME",
          "EvaluateTargetHealth": false
        }
      }
    }
  ]
}
```

Get the ALB hosted zone ID:

```bash
export ALB_HOSTED_ZONE_ID=$(aws elbv2 describe-load-balancers \
  --load-balancer-arns ${ALB_ARN} \
  --query 'LoadBalancers[0].CanonicalHostedZoneId' \
  --output text)
```

Update the JSON placeholders, then run:

```bash
aws route53 change-resource-record-sets \
  --hosted-zone-id ${HOSTED_ZONE_ID} \
  --change-batch file://route53-alias.json
```

## 18. Add the HTTPS Listener

After the ACM certificate becomes `ISSUED`, create the HTTPS listener:

```bash
aws elbv2 create-listener \
  --load-balancer-arn ${ALB_ARN} \
  --protocol HTTPS \
  --port 443 \
  --certificates CertificateArn=${CERT_ARN} \
  --default-actions Type=forward,TargetGroupArn=${FRONTEND_TG_ARN}
```

You can optionally change port `80` to redirect to `443`.

## 19. Create ECS Services

### 19.1 Backend service

```bash
aws ecs create-service \
  --cluster ${ECS_CLUSTER_NAME} \
  --service-name ${APP_PREFIX}-backend-service \
  --task-definition openai-image-backend \
  --desired-count 2 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[${PRIVATE_SUBNET_1_ID},${PRIVATE_SUBNET_2_ID}],securityGroups=[${BACKEND_SG_ID}],assignPublicIp=DISABLED}" \
  --load-balancers targetGroupArn=${BACKEND_TG_ARN},containerName=backend,containerPort=8000
```

### 19.2 Frontend service

```bash
aws ecs create-service \
  --cluster ${ECS_CLUSTER_NAME} \
  --service-name ${APP_PREFIX}-frontend-service \
  --task-definition openai-image-frontend \
  --desired-count 2 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[${PRIVATE_SUBNET_1_ID},${PRIVATE_SUBNET_2_ID}],securityGroups=[${FRONTEND_SG_ID}],assignPublicIp=DISABLED}" \
  --load-balancers targetGroupArn=${FRONTEND_TG_ARN},containerName=frontend,containerPort=80
```

### 19.3 Worker service

```bash
aws ecs create-service \
  --cluster ${ECS_CLUSTER_NAME} \
  --service-name ${APP_PREFIX}-worker-service \
  --task-definition openai-image-worker \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[${PRIVATE_SUBNET_1_ID},${PRIVATE_SUBNET_2_ID}],securityGroups=[${WORKER_SG_ID}],assignPublicIp=DISABLED}"
```

## 20. Configure CloudWatch Alarms

Create an alarm for visible queue depth:

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name ${APP_PREFIX}-queue-depth-high \
  --metric-name ApproximateNumberOfMessagesVisible \
  --namespace AWS/SQS \
  --statistic Average \
  --period 60 \
  --threshold 5 \
  --comparison-operator GreaterThanThreshold \
  --evaluation-periods 2 \
  --dimensions Name=QueueName,Value=$(basename ${MAIN_QUEUE_URL}) \
  --alarm-description "Queue depth is high"
```

Create an alarm for the DLQ:

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name ${APP_PREFIX}-dlq-messages \
  --metric-name ApproximateNumberOfMessagesVisible \
  --namespace AWS/SQS \
  --statistic Average \
  --period 60 \
  --threshold 0 \
  --comparison-operator GreaterThanThreshold \
  --evaluation-periods 1 \
  --dimensions Name=QueueName,Value=$(basename ${DLQ_URL}) \
  --alarm-description "Messages detected in DLQ"
```

## 21. Configure ECS Auto Scaling

### 21.1 Register scalable targets

```bash
aws application-autoscaling register-scalable-target \
  --service-namespace ecs \
  --resource-id service/${ECS_CLUSTER_NAME}/${APP_PREFIX}-backend-service \
  --scalable-dimension ecs:service:DesiredCount \
  --min-capacity 2 \
  --max-capacity 4
```

```bash
aws application-autoscaling register-scalable-target \
  --service-namespace ecs \
  --resource-id service/${ECS_CLUSTER_NAME}/${APP_PREFIX}-frontend-service \
  --scalable-dimension ecs:service:DesiredCount \
  --min-capacity 2 \
  --max-capacity 4
```

```bash
aws application-autoscaling register-scalable-target \
  --service-namespace ecs \
  --resource-id service/${ECS_CLUSTER_NAME}/${APP_PREFIX}-worker-service \
  --scalable-dimension ecs:service:DesiredCount \
  --min-capacity 1 \
  --max-capacity 5
```

### 21.2 Add CPU target tracking for backend and frontend

```bash
aws application-autoscaling put-scaling-policy \
  --service-namespace ecs \
  --resource-id service/${ECS_CLUSTER_NAME}/${APP_PREFIX}-backend-service \
  --scalable-dimension ecs:service:DesiredCount \
  --policy-name ${APP_PREFIX}-backend-cpu-scaling \
  --policy-type TargetTrackingScaling \
  --target-tracking-scaling-policy-configuration '{"TargetValue":60.0,"PredefinedMetricSpecification":{"PredefinedMetricType":"ECSServiceAverageCPUUtilization"},"ScaleInCooldown":60,"ScaleOutCooldown":60}'
```

```bash
aws application-autoscaling put-scaling-policy \
  --service-namespace ecs \
  --resource-id service/${ECS_CLUSTER_NAME}/${APP_PREFIX}-frontend-service \
  --scalable-dimension ecs:service:DesiredCount \
  --policy-name ${APP_PREFIX}-frontend-cpu-scaling \
  --policy-type TargetTrackingScaling \
  --target-tracking-scaling-policy-configuration '{"TargetValue":60.0,"PredefinedMetricSpecification":{"PredefinedMetricType":"ECSServiceAverageCPUUtilization"},"ScaleInCooldown":60,"ScaleOutCooldown":60}'
```

### 21.3 Add worker scaling policy

For students, the simplest CLI approach is:

- register the worker service as scalable
- add a CloudWatch alarm on queue depth
- connect that alarm to a step scaling policy

Create the step scaling policy:

```bash
aws application-autoscaling put-scaling-policy \
  --service-namespace ecs \
  --resource-id service/${ECS_CLUSTER_NAME}/${APP_PREFIX}-worker-service \
  --scalable-dimension ecs:service:DesiredCount \
  --policy-name ${APP_PREFIX}-worker-step-scale-out \
  --policy-type StepScaling \
  --step-scaling-policy-configuration '{"AdjustmentType":"ChangeInCapacity","Cooldown":60,"MetricAggregationType":"Average","StepAdjustments":[{"MetricIntervalLowerBound":0,"ScalingAdjustment":1}]}'
```

## 22. Validate the Deployment

Check ECS services:

```bash
aws ecs describe-services \
  --cluster ${ECS_CLUSTER_NAME} \
  --services ${APP_PREFIX}-frontend-service ${APP_PREFIX}-backend-service ${APP_PREFIX}-worker-service
```

Check target health:

```bash
aws elbv2 describe-target-health --target-group-arn ${FRONTEND_TG_ARN}
aws elbv2 describe-target-health --target-group-arn ${BACKEND_TG_ARN}
```

Check the backend health endpoint:

```bash
curl http://${ALB_DNS_NAME}/api/health
```

Or once DNS and HTTPS are working:

```bash
curl https://${APP_DOMAIN}/api/health
```

Check CloudWatch logs:

```bash
aws logs describe-log-streams --log-group-name /ecs/${APP_PREFIX}/backend
aws logs describe-log-streams --log-group-name /ecs/${APP_PREFIX}/worker
aws logs describe-log-streams --log-group-name /ecs/${APP_PREFIX}/frontend
```

## 23. Notes and Simplifications

This guide intentionally keeps some things simple for teaching:

- IAM permissions are broader than ideal
- NAT is single-AZ instead of highly available
- RDS uses a small single instance
- task definition JSON files use placeholder replacement rather than automation tooling

In a real production setup, you would likely use:

- `Terraform`, `CloudFormation`, or `CDK`
- tighter IAM policies scoped to exact ARNs
- multi-AZ NAT and RDS
- separate environments for dev, staging, and prod

## 24. Suggested Student Demo

After deployment, walk through this flow:

1. Show the `ECR` repositories
2. Show the `ECS` cluster and services
3. Show the `ALB` rules sending `/api/*` to the backend
4. Open the `Route 53` domain
5. Show the `ACM` certificate
6. Show secrets in `Secrets Manager`
7. Submit an image generation request
8. Inspect the `SQS` main queue and `DLQ`
9. Show the worker and backend logs in `CloudWatch`
10. Explain how `Auto Scaling` would react to more traffic
