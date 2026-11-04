from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    openai_api_key: str | None = Field(default=None, repr=False)
    openai_embedding_model: str = Field(min_length=1)

    database_path: str = Field(default="emporio.db", min_length=1)
    chroma_persist_dir: str = Field(default="chroma", min_length=1)
    chroma_collection_name: str = Field(default="policy_manual", min_length=1)
    data_dir: str = Field(default="data", min_length=1)
    policy_pdf_path: str = Field(
        default="data/políticas_da_loja.pdf",
        min_length=1,
    )

    rag_top_k: int = Field(default=4, ge=1)
    rag_max_chunk_chars: int = Field(default=1200, ge=1)
    rag_chunk_overlap_chars: int = Field(default=150, ge=0)

    mcp_server_host: str = Field(default="0.0.0.0", min_length=1)
    mcp_server_port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = Field(default="INFO", min_length=1)

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def normalize_api_key(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @field_validator(
        "openai_embedding_model",
        "database_path",
        "chroma_persist_dir",
        "chroma_collection_name",
        "data_dir",
        "policy_pdf_path",
        "mcp_server_host",
        mode="before",
    )
    @classmethod
    def strip_required_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        allowed_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if value not in allowed_levels:
            raise ValueError(
                "LOG_LEVEL must be one of DEBUG, INFO, WARNING, ERROR or CRITICAL"
            )
        return value

    @model_validator(mode="after")
    def validate_chunk_settings(self) -> "Settings":
        if self.rag_chunk_overlap_chars >= self.rag_max_chunk_chars:
            raise ValueError(
                "RAG_CHUNK_OVERLAP_CHARS must be smaller than RAG_MAX_CHUNK_CHARS"
            )
        return self
