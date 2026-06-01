# OpenAI Image Creation API on AWS

This POC has three containers:

1. `backend` - FastAPI API running on ECS
2. `worker` - Python SQS worker running on ECS
3. `frontend` - React UI served by Nginx on ECS

AWS services used:

- ECS/Fargate for containers
- ECR for images
- SQS FIFO for asynchronous image jobs
- RDS PostgreSQL for users and image job metadata
- S3 for generated images
- Secrets Manager for `OPENAI_API_KEY` and database credentials
- IAM Task Roles for SQS/S3 permissions
- CloudWatch Logs for container logs

## API flow

```text
Browser -> Frontend -> Backend API -> RDS + SQS FIFO
                                  Worker <- SQS FIFO
                                  Worker -> OpenAI Image API
                                  Worker -> S3
                                  Worker -> RDS update
Browser -> Backend API -> presigned S3 URL
```

## Setup

Copy env file:

```bash
cp .env.example .env
```

Update these values:

```bash
OPENAI_API_KEY=sk-your-key
AWS_REGION=ap-south-1
SQS_QUEUE_URL=https://sqs.ap-south-1.amazonaws.com/123456789012/image-generation.fifo
S3_BUCKET_NAME=your-bucket-name
```

Run locally:

```bash
docker compose up --build
```

Open:

```text
Frontend: http://localhost:3000
Backend health: http://localhost:8000/api/health
```

## Required AWS resources

Create S3 bucket:

```bash
aws s3api create-bucket \
  --bucket your-image-generation-bucket \
  --region ap-south-1 \
  --create-bucket-configuration LocationConstraint=ap-south-1
```

Create SQS FIFO queue:

```bash
aws sqs create-queue \
  --queue-name image-generation.fifo \
  --attributes FifoQueue=true,ContentBasedDeduplication=false,VisibilityTimeout=180
```

The visibility timeout should be longer than expected image generation time.

## Build images

```bash
docker build -f Dockerfile.api -t image-api:1.0 .
docker build -f Dockerfile.worker -t image-worker:1.0 .
docker build -t image-frontend:1.0 ./frontend
```

## ECS recommendation

Create three ECS services:

- `image-api-service` behind ALB path `/api/*`
- `image-frontend-service` behind ALB path `/*`
- `image-worker-service` without public ingress

Use IAM Task Role permissions:

- API task: `sqs:SendMessage`
- Worker task: `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:GetQueueAttributes`, `s3:PutObject`
- API task: `s3:GetObject` if generating presigned URLs

Use Secrets Manager for:

- `OPENAI_API_KEY`
- `DATABASE_URL` or database username/password
