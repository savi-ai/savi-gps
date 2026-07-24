"""Resolve wiki generation mode / LLM prefs (env + tenant overrides)."""
from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.core.config import settings

VALID_MODES = ("cli", "api", "auto")
VALID_PROVIDERS = ("claude", "anthropic", "openai", "bedrock", "ollama")


def env_llm_status() -> Dict[str, Any]:
    """Non-secret status for Admin UI (never returns key values)."""
    provider = (settings.LLM_PROVIDER or "claude").lower()
    region = settings.BEDROCK_AWS_REGION or settings.AWS_REGION
    has_anthropic = bool(settings.ANTHROPIC_API_KEY)
    has_openai = bool(settings.OPENAI_API_KEY)
    has_bedrock_keys = bool(
        settings.AWS_ACCESS_KEY_ID
        or settings.BEDROCK_AWS_ACCESS_KEY_ID
        or settings.AWS_SECRET_ACCESS_KEY
        or settings.BEDROCK_AWS_SECRET_ACCESS_KEY
    )
    return {
        "wiki_generation_mode_default": (settings.WIKI_GENERATION_MODE or "auto").lower(),
        "llm_provider_default": provider,
        "anthropic_model": settings.ANTHROPIC_MODEL,
        "bedrock_model_id": settings.BEDROCK_MODEL_ID,
        "bedrock_region": region,
        "llm_max_retries": settings.LLM_MAX_RETRIES,
        "credentials": {
            "anthropic": has_anthropic,
            "openai": has_openai,
            "bedrock_explicit_keys": has_bedrock_keys,
            "bedrock_model_configured": bool(settings.BEDROCK_MODEL_ID),
        },
    }


def resolve_wiki_generation_settings(
    db: Optional[Session] = None,
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Merge env defaults with optional tenant LLM settings (non-secret)."""
    mode = (settings.WIKI_GENERATION_MODE or "auto").lower()
    provider = (settings.LLM_PROVIDER or "claude").lower()
    model = settings.ANTHROPIC_MODEL
    if provider == "bedrock":
        model = settings.BEDROCK_MODEL_ID
    elif provider == "openai":
        model = "gpt-4"

    tenant_override: Dict[str, Any] = {}
    if db is not None and tenant_id:
        from app.services.tenant_config_service import TenantConfigService

        tenant_override = TenantConfigService(db).get_llm_settings(tenant_id)

    if tenant_override.get("wiki_generation_mode") in VALID_MODES:
        mode = tenant_override["wiki_generation_mode"]
    if tenant_override.get("llm_provider") in VALID_PROVIDERS:
        provider = tenant_override["llm_provider"]
    if tenant_override.get("llm_model"):
        model = tenant_override["llm_model"]

    return {
        "wiki_generation_mode": mode if mode in VALID_MODES else "auto",
        "llm_provider": provider,
        "llm_model": model,
        "bedrock_region": settings.BEDROCK_AWS_REGION or settings.AWS_REGION,
        "source": "tenant" if tenant_override else "env",
    }
