from typing import Annotated

from pydantic import BaseModel, Field, field_validator


class Login(BaseModel):
    # ponytail: conventional web email syntax; use email-validator if international mailbox rules become required.
    email: Annotated[str, Field(min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]
    password: Annotated[str, Field(min_length=12, max_length=128)]

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


class Register(Login):
    display_name: Annotated[str, Field(min_length=1, max_length=50)]

    @field_validator("display_name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Display name cannot be blank")
        return value.strip()


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class User(BaseModel):
    id: int
    email: str
    display_name: str
