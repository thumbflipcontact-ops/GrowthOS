from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field, field_validator


def _normalize_email(value: str) -> str:
    return value.strip().lower()


class RedeemLtdCodeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    org_name: str = Field(min_length=1, max_length=200)
    org_slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=12, max_length=200)

    _normalize_email = field_validator("email", mode="after")(_normalize_email)
