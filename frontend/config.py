from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    backend_url: str = Field(
        default="http://backend:8080",
        min_length=1,
    )

    @field_validator("backend_url", mode="before")
    @classmethod
    def strip_backend_url(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("backend_url")
    @classmethod
    def validate_backend_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("BACKEND_URL must be a valid http or https URL")
        return value


__all__ = ["Settings"]
