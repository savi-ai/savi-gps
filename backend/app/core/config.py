"""Configuration settings for GPS service"""
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings
from typing import Optional, List
import os
from pathlib import Path

_PLACEHOLDER_SECRETS = frozenset({
    "your-secret-key-change-in-production-min-32-chars",
    "change-me-in-production-min-32-characters",
    "change-me-in-production",
})


class Settings(BaseSettings):
    """Application settings"""

    # Application
    APP_NAME: str = "Savi GPS"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    # API
    API_V1_PREFIX: str = "/api/v1"

    # Authentication
    API_KEY: Optional[str] = None
    ADMIN_TOKEN: Optional[str] = None
    SECRET_KEY: str = "your-secret-key-change-in-production-min-32-chars"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours

    # CORS — comma-separated origins; never use "*" with credentials in production
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    # LLM Configuration
    LLM_PROVIDER: str = "claude"
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_MODEL: str = "claude-sonnet-4-5-20250929"
    AWS_REGION: Optional[str] = "us-east-1"
    # Standard AWS SDK keys (preferred) — also accept BEDROCK_AWS_* aliases via env
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    BEDROCK_AWS_ACCESS_KEY_ID: Optional[str] = None
    BEDROCK_AWS_SECRET_ACCESS_KEY: Optional[str] = None
    BEDROCK_AWS_REGION: Optional[str] = None
    BEDROCK_MODEL_ID: Optional[str] = "anthropic.claude-3-sonnet-20240229-v1:0"
    LLM_MAX_RETRIES: int = 3
    # Wiki generation: cli | api | auto (CLI then API then heuristic)
    WIKI_GENERATION_MODE: str = "auto"
    # Incremental wiki: compare last stored git_head to clone HEAD
    WIKI_INCREMENTAL_ENABLED: bool = True
    WIKI_INCREMENTAL_MAX_FILES: int = 40
    WIKI_INCREMENTAL_MAX_DIFF_CHARS: int = 24000
    # Repo-relative path for optional GitHub wiki export (also ignored for regen)
    WIKI_GITHUB_EXPORT_PATH: str = "docs/savi-wiki"

    # SOP Configuration
    SOP_DIRECTORY: str = str(Path(__file__).parent.parent.parent / "sops")
    SOP_SCHEMA_PATH: str = str(Path(__file__).parent.parent.parent / "schemas" / "sop.schema.json")

    # Database
    DATABASE_URL: str = "sqlite:///./gps.db"
    INTELLIGENCE_DATABASE_URL: Optional[str] = None
    INTELLIGENCE_ENABLED: bool = False
    FLEET_ENABLED: bool = False
    PORTFOLIO_ENABLED: Optional[bool] = None
    MODERNIZE_ENABLED: Optional[bool] = None
    # ADR 0007: when true, Application/Project mutations require Team membership
    TEAM_ACL_ENFORCED: bool = False

    # Legacy SQLite boot-time ALTER migrations (disable once Alembic-only path is verified)
    USE_LEGACY_SQLITE_MIGRATIONS: bool = True

    # Neo4j
    NEO4J_URI: Optional[str] = None
    NEO4J_USER: Optional[str] = "neo4j"
    NEO4J_PASSWORD: Optional[str] = None
    NEO4J_DATABASE: str = "neo4j"

    # Embeddings
    EMBEDDINGS_PROVIDER: str = "openai"
    EMBEDDINGS_MODEL: str = "text-embedding-3-small"
    VOYAGE_API_KEY: Optional[str] = None

    # Storage
    STORAGE_BASE_PATH: Optional[str] = None
    STORAGE_TYPE: str = "local"

    # S3 Configuration
    S3_BUCKET_NAME: Optional[str] = None
    S3_REGION: Optional[str] = None
    S3_ACCESS_KEY_ID: Optional[str] = None
    S3_SECRET_ACCESS_KEY: Optional[str] = None

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"

    # External Integrations
    JIRA_ENABLED: bool = False
    CONFLUENCE_ENABLED: bool = False
    GITHUB_ENABLED: bool = False
    HARNESS_ENABLED: bool = False
    SLACK_ENABLED: bool = False
    GITHUB_TOKEN: Optional[str] = None
    # Optional shared webhook verification (per-binding secret preferred)
    SAVI_WEBHOOK_SHARED_SECRET: Optional[str] = None
    # T6/B2: orchestrator jobs
    SAVI_ORCHESTRATOR_INLINE: bool = True
    SAVI_USE_ARQ: bool = False
    REDIS_URL: Optional[str] = "redis://localhost:6379"
    SAVI_CODING_AGENT: str = "llm"  # llm | heuristic | claude_cli | copilot_cli | kiro_cli

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug(cls, value):
        if isinstance(value, bool):
            return value
        return str(value).lower() in {"1", "true", "yes", "on"}

    @field_validator(
        "INTELLIGENCE_ENABLED",
        "FLEET_ENABLED",
        "USE_LEGACY_SQLITE_MIGRATIONS",
        "TEAM_ACL_ENFORCED",
        "SAVI_ORCHESTRATOR_INLINE",
        "SAVI_USE_ARQ",
        mode="before",
    )
    @classmethod
    def parse_bool_flags(cls, value):
        if isinstance(value, bool):
            return value
        return str(value).lower() in {"1", "true", "yes", "on"}

    @property
    def cors_origins_list(self) -> List[str]:
        if not self.CORS_ORIGINS.strip():
            return []
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @model_validator(mode="after")
    def validate_environment(self) -> "Settings":
        if self.S3_REGION is None:
            object.__setattr__(self, "S3_REGION", self.AWS_REGION)

        mode = (self.WIKI_GENERATION_MODE or "auto").lower().strip()
        if mode not in {"cli", "api", "auto"}:
            mode = "auto"
        object.__setattr__(self, "WIKI_GENERATION_MODE", mode)

        if self.ENVIRONMENT != "production":
            return self

        errors: List[str] = []

        if not self.SECRET_KEY or self.SECRET_KEY in _PLACEHOLDER_SECRETS:
            errors.append("SECRET_KEY must be set to a non-placeholder value in production")
        elif len(self.SECRET_KEY) < 32:
            errors.append("SECRET_KEY must be at least 32 characters in production")

        if self.LLM_PROVIDER in {"claude", "anthropic"} and not self.ANTHROPIC_API_KEY:
            errors.append("ANTHROPIC_API_KEY is required in production when LLM_PROVIDER=claude")
        if self.LLM_PROVIDER == "openai" and not self.OPENAI_API_KEY:
            errors.append("OPENAI_API_KEY is required in production when LLM_PROVIDER=openai")
        if self.LLM_PROVIDER == "bedrock" and not self.BEDROCK_MODEL_ID:
            errors.append("BEDROCK_MODEL_ID is required in production when LLM_PROVIDER=bedrock")

        if self.CORS_ORIGINS.strip() == "*":
            errors.append("CORS_ORIGINS must be an explicit allowlist in production (not '*')")

        if "sqlite" in self.DATABASE_URL.lower():
            errors.append("SQLite DATABASE_URL is not allowed in production; use Postgres")

        if errors:
            raise ValueError("Production configuration invalid:\n- " + "\n- ".join(errors))

        return self

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"


settings = Settings()
