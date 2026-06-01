from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "OpenAI Image AWS POC"
    ENVIRONMENT: str = "dev"

    DATABASE_URL: str

    AWS_REGION: str = "ap-south-1"
    SQS_QUEUE_URL: str
    S3_BUCKET_NAME: str
    S3_PRESIGNED_URL_EXPIRE_SECONDS: int = 3600

    OPENAI_API_KEY: str | None = None
    OPENAI_IMAGE_MODEL: str = "gpt-image-2"
    OPENAI_IMAGE_OUTPUT_FORMAT: str = "png"

    WORKER_POLL_SECONDS: int = 20
    WORKER_MAX_ATTEMPTS: int = 3

    CORS_ORIGINS: str = "*"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
