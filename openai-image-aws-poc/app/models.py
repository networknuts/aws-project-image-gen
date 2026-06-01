import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(320), unique=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    jobs = relationship("ImageJob", back_populates="user")


class ImageJob(Base):
    __tablename__ = "image_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)

    prompt = Column(Text, nullable=False)
    size = Column(String(32), nullable=False, default="1024x1024")
    quality = Column(String(32), nullable=False, default="medium")
    model = Column(String(64), nullable=False, default="gpt-image-2")

    status = Column(String(32), nullable=False, default="QUEUED", index=True)
    s3_key = Column(Text, nullable=True)
    error = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user = relationship("User", back_populates="jobs")


Index("idx_image_jobs_user_created", ImageJob.user_id, ImageJob.created_at.desc())
