from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr, Field, field_validator

# Lowercased here, at the schema boundary, so every downstream consumer (AuthService,
# UserRepository, the stored User.email column) always sees the same casing — rather than
# each call site needing to remember to normalize it independently. Without this, an account
# registered as "Name@Example.com" could never log in typing "name@example.com": User.email
# equality in UserRepository.get_by_email is a case-sensitive Postgres `=`, so a login attempt
# with different casing than what was typed at signup silently fails as "no such user."


def _normalize_email(value: str) -> str:
    return value.strip().lower()


class RegisterRequest(BaseModel):
    org_name: str = Field(min_length=1, max_length=200)
    org_slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=12, max_length=200)

    _normalize_email = field_validator("email", mode="after")(_normalize_email)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str

    _normalize_email = field_validator("email", mode="after")(_normalize_email)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr

    _normalize_email = field_validator("email", mode="after")(_normalize_email)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1)
    new_password: str = Field(min_length=12, max_length=200)


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    name: str

    model_config = {"from_attributes": True}


class OrganizationResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str

    model_config = {"from_attributes": True}
