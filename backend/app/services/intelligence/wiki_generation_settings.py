"""Resolve wiki generation mode / LLM prefs (env + tenant overrides)."""
from __future__ import annotations

import os
import shutil
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.core.config import settings


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
    has_copilot_cli = bool(shutil.which("copilot"))
    has_claude_cli = bool(shutil.which("claude"))
    has_copilot_token = bool(
        settings.GITHUB_TOKEN
        or os.environ.get("COPILOT_GITHUB_TOKEN")
        or os.environ.get("GH_TOKEN")
        or os.environ.get("GITHUB_TOKEN")
    )
    return {
        "wiki_generation_mode_default": (settings.WIKI_GENERATION_MODE or "auto").lower(),
        "llm_provider_default": provider,
        "code_generation_default": (settings.SAVI_CODING_AGENT or "heuristic").lower(),
        "anthropic_model": settings.ANTHROPIC_MODEL,
        "bedrock_model_id": settings.BEDROCK_MODEL_ID,
        "bedrock_region": region,
        "llm_max_retries": settings.LLM_MAX_RETRIES,
        "credentials": {
            "anthropic": has_anthropic,
            "openai": has_openai,
            "bedrock_explicit_keys": has_bedrock_keys,
            "bedrock_model_configured": bool(settings.BEDROCK_MODEL_ID),
            "claude_cli_on_path": has_claude_cli,
            "copilot_cli_on_path": has_copilot_cli,
            "copilot_github_token": has_copilot_token,
        },
    }


def resolve_wiki_generation_settings(
    db: Optional[Session] = None,
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Merge env defaults with optional tenant LLM settings (non-secret)."""
    from app.services.llm_routing import resolve_wiki_generation

    return resolve_wiki_generation(db, tenant_id)
