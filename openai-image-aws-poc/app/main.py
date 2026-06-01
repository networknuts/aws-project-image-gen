from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, engine, get_db
from app.models import ImageJob, User
from app.s3 import create_presigned_image_url
from app.schemas import GenerateImageRequest, GenerateImageResponse, JobResponse
from app.sqs import send_image_job_to_queue, sqs_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Good for POC. For production, use Alembic migrations instead.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

origins = ["*"] if settings.CORS_ORIGINS == "*" else [o.strip() for o in settings.CORS_ORIGINS.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    checks: dict[str, str] = {}

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "error"

    try:
        sqs_client.get_queue_attributes(
            QueueUrl=settings.SQS_QUEUE_URL,
            AttributeNames=["QueueArn"],
        )
        checks["sqs"] = "ok"
    except Exception:
        checks["sqs"] = "error"

    overall_status = "ok" if all(value == "ok" for value in checks.values()) else "degraded"
    status_code = 200 if overall_status == "ok" else 503

    return JSONResponse(
        status_code=status_code,
        content={
            "status": overall_status,
            "service": "backend-api",
            "environment": settings.ENVIRONMENT,
            "checks": checks,
        },
    )


def to_job_response(job: ImageJob, email: str) -> JobResponse:
    image_url = None
    if job.status == "COMPLETED" and job.s3_key:
        image_url = create_presigned_image_url(job.s3_key)

    return JobResponse(
        job_id=job.id,
        email=email,
        prompt=job.prompt,
        size=job.size,
        quality=job.quality,
        model=job.model,
        status=job.status,
        image_url=image_url,
        s3_key=job.s3_key,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@app.post("/api/generate", response_model=GenerateImageResponse)
def generate_image(payload: GenerateImageRequest, db: Session = Depends(get_db)):
    email = str(payload.email).lower()

    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email)
        db.add(user)
        db.flush()

    job = ImageJob(
        user_id=user.id,
        prompt=payload.prompt,
        size=payload.size,
        quality=payload.quality,
        model=settings.OPENAI_IMAGE_MODEL,
        status="QUEUED",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    try:
        send_image_job_to_queue(
            job_id=job.id,
            email=email,
            prompt=payload.prompt,
            size=payload.size,
            quality=payload.quality,
            model=settings.OPENAI_IMAGE_MODEL,
        )
    except Exception as exc:
        job.status = "FAILED"
        job.error = f"SQS enqueue failed: {exc}"
        db.commit()
        raise HTTPException(status_code=500, detail="Could not enqueue image generation job") from exc

    return GenerateImageResponse(
        job_id=job.id,
        status=job.status,
        message="Image generation job queued successfully",
    )


@app.get("/api/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: UUID, db: Session = Depends(get_db)):
    job = db.query(ImageJob).filter(ImageJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    user = db.query(User).filter(User.id == job.user_id).first()
    return to_job_response(job, user.email)


@app.get("/api/users/{email}/images", response_model=list[JobResponse])
def list_user_images(email: str, db: Session = Depends(get_db)):
    normalized_email = email.lower()
    user = db.query(User).filter(User.email == normalized_email).first()
    if not user:
        return []

    jobs = (
        db.query(ImageJob)
        .filter(ImageJob.user_id == user.id)
        .order_by(ImageJob.created_at.desc())
        .limit(100)
        .all()
    )

    return [to_job_response(job, user.email) for job in jobs]
