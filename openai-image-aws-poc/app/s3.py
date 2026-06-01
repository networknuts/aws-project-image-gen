import boto3

from app.config import settings

s3_client = boto3.client("s3", region_name=settings.AWS_REGION)


def create_presigned_image_url(s3_key: str) -> str:
    return s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.S3_BUCKET_NAME, "Key": s3_key},
        ExpiresIn=settings.S3_PRESIGNED_URL_EXPIRE_SECONDS,
    )
