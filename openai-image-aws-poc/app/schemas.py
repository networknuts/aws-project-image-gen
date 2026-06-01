from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


class GenerateImageRequest(BaseModel):
    email: EmailStr
    prompt: str = Field(..., min_length=3, max_length=32000)
    size: str = Field(default="1024x1024", examples=["1024x1024", "1536x1024", "1024x1536"])
    quality: Literal["low", "medium", "high", "auto"] = "medium"

    @field_validator("size")
    @classmethod
    def validate_size(cls, value: str) -> str:
        if value == "auto":
            return value

        try:
            width_text, height_text = value.lower().split("x")
            width = int(width_text)
            height = int(height_text)
        except Exception as exc:
            raise ValueError("size must be 'auto' or WIDTHxHEIGHT, example: 1024x1024") from exc

        if width <= 0 or height <= 0:
            raise ValueError("width and height must be positive")

        if width % 16 != 0 or height % 16 != 0:
            raise ValueError("width and height must both be divisible by 16")

        if max(width, height) > 3840:
            raise ValueError("maximum edge length is 3840px")

        ratio = width / height
        if ratio < 1 / 3 or ratio > 3:
            raise ValueError("aspect ratio must be between 1:3 and 3:1")

        return value


class GenerateImageResponse(BaseModel):
    job_id: UUID
    status: str
    message: str


class JobResponse(BaseModel):
    job_id: UUID
    email: str
    prompt: str
    size: str
    quality: str
    model: str
    status: str
    image_url: str | None = None
    s3_key: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime
