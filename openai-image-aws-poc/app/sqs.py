import json
from uuid import UUID

import boto3

from app.config import settings

sqs_client = boto3.client("sqs", region_name=settings.AWS_REGION)


def send_image_job_to_queue(
    *,
    job_id: UUID,
    email: str,
    prompt: str,
    size: str,
    quality: str,
    model: str,
) -> None:
    body = {
        "job_id": str(job_id),
        "email": email,
        "prompt": prompt,
        "size": size,
        "quality": quality,
        "model": model,
    }

    sqs_client.send_message(
        QueueUrl=settings.SQS_QUEUE_URL,
        MessageBody=json.dumps(body),
        MessageGroupId=email.lower(),
        MessageDeduplicationId=str(job_id),
    )
