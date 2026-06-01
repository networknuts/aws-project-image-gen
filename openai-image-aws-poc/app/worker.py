import base64
import json
import logging
import signal
import sys
import time
from uuid import UUID

import boto3
from openai import OpenAI
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.models import ImageJob

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("image-worker")

sqs_client = boto3.client("sqs", region_name=settings.AWS_REGION)
s3_client = boto3.client("s3", region_name=settings.AWS_REGION)
openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)

running = True


def shutdown_handler(signum, frame):
    global running
    logger.info("Received signal %s. Shutting down after current message.", signum)
    running = False


signal.signal(signal.SIGTERM, shutdown_handler)
signal.signal(signal.SIGINT, shutdown_handler)


def generate_image_bytes(*, prompt: str, size: str, quality: str, model: str) -> bytes:
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set")

    result = openai_client.images.generate(
        model=model,
        prompt=prompt,
        size=size,
        quality=quality,
        n=1,
        output_format=settings.OPENAI_IMAGE_OUTPUT_FORMAT,
    )

    image_base64 = result.data[0].b64_json
    if not image_base64:
        raise RuntimeError("OpenAI returned an empty image payload")

    return base64.b64decode(image_base64)


def upload_image_to_s3(*, job: ImageJob, image_bytes: bytes) -> str:
    extension = settings.OPENAI_IMAGE_OUTPUT_FORMAT
    content_type = "image/png" if extension == "png" else f"image/{extension}"
    s3_key = f"generated-images/{job.user_id}/{job.id}.{extension}"

    s3_client.put_object(
        Bucket=settings.S3_BUCKET_NAME,
        Key=s3_key,
        Body=image_bytes,
        ContentType=content_type,
        Metadata={
            "job_id": str(job.id),
            "user_id": str(job.user_id),
            "model": job.model,
        },
    )
    return s3_key


def delete_message(receipt_handle: str) -> None:
    sqs_client.delete_message(
        QueueUrl=settings.SQS_QUEUE_URL,
        ReceiptHandle=receipt_handle,
    )


def mark_failed(db: Session, job_id: UUID, error: str) -> None:
    job = db.query(ImageJob).filter(ImageJob.id == job_id).first()
    if job:
        job.status = "FAILED"
        job.error = error[:2000]
        db.commit()


def process_message(message: dict) -> None:
    receipt_handle = message["ReceiptHandle"]
    body = json.loads(message["Body"])
    job_id = UUID(body["job_id"])
    receive_count = int(message.get("Attributes", {}).get("ApproximateReceiveCount", "1"))

    db = SessionLocal()
    try:
        job = db.query(ImageJob).filter(ImageJob.id == job_id).first()
        if not job:
            logger.warning("Job %s not found. Deleting orphan SQS message.", job_id)
            delete_message(receipt_handle)
            return

        if job.status == "COMPLETED":
            logger.info("Job %s already completed. Deleting duplicate SQS message.", job_id)
            delete_message(receipt_handle)
            return

        logger.info("Processing job %s, attempt %s", job_id, receive_count)
        job.status = "PROCESSING"
        job.error = None
        db.commit()
        db.refresh(job)

        image_bytes = generate_image_bytes(
            prompt=job.prompt,
            size=job.size,
            quality=job.quality,
            model=job.model,
        )
        s3_key = upload_image_to_s3(job=job, image_bytes=image_bytes)

        job.status = "COMPLETED"
        job.s3_key = s3_key
        job.error = None
        db.commit()

        delete_message(receipt_handle)
        logger.info("Completed job %s and uploaded to s3://%s/%s", job_id, settings.S3_BUCKET_NAME, s3_key)

    except Exception as exc:
        db.rollback()
        logger.exception("Job %s failed on attempt %s", job_id, receive_count)

        if receive_count >= settings.WORKER_MAX_ATTEMPTS:
            mark_failed(db, job_id, str(exc))
            delete_message(receipt_handle)
            logger.error("Job %s marked FAILED after %s attempts", job_id, receive_count)
        else:
            job = db.query(ImageJob).filter(ImageJob.id == job_id).first()
            if job:
                job.status = "QUEUED"
                job.error = f"Attempt {receive_count} failed: {str(exc)[:1000]}"
                db.commit()
            # Do not delete the message. SQS visibility timeout will make it visible again.
    finally:
        db.close()


def poll_once() -> None:
    response = sqs_client.receive_message(
        QueueUrl=settings.SQS_QUEUE_URL,
        MaxNumberOfMessages=1,
        WaitTimeSeconds=settings.WORKER_POLL_SECONDS,
        AttributeNames=["ApproximateReceiveCount"],
    )

    for message in response.get("Messages", []):
        process_message(message)


def main() -> int:
    Base.metadata.create_all(bind=engine)
    logger.info("Worker started. Queue=%s Bucket=%s Model=%s", settings.SQS_QUEUE_URL, settings.S3_BUCKET_NAME, settings.OPENAI_IMAGE_MODEL)

    while running:
        try:
            poll_once()
        except Exception:
            logger.exception("Worker polling error")
            time.sleep(5)

    logger.info("Worker stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
