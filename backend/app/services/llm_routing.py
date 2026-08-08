"""Tenant-aware LLM / coding-agent routing (Admin → Tenant settings)."""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.llm_client import LLMClient, get_llm_client
from app.core.logger import logger

_CODE_GEN_TO_EXECUTION = {
    "claude": "claude_cli",
    "github_copilot": "copilot_cli",
}


def _tenant_llm_bag(db: Optional[Session], tenant_id: Optional[str]) -> Dict[str, Any]:
    if db is None or not tenant_id:
        return {}
    from app.services.tenant_config_service import TenantConfigService

    return TenantConfigService(db).get_llm_settings(tenant_id)


def resolve_other_llm(
    db: Optional[Session] = None,
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Provider + model for chat, search, idea/feature/architecture, default LLMClient."""
    provider = (settings.LLM_PROVIDER or "claude").lower()
    if provider == "anthropic":
        provider = "claude"
    model: Optional[str] = None
    if provider == "bedrock":
        model = settings.BEDROCK_MODEL_ID
    elif provider == "openai":
        model = "gpt-4"
    elif provider in ("claude", "anthropic"):
        model = settings.ANTHROPIC_MODEL

    bag = _tenant_llm_bag(db, tenant_id)
    if bag.get("llm_provider") in ("claude", "openai", "bedrock", "ollama"):
        provider = bag["llm_provider"]
    if bag.get("llm_model"):
        model = bag["llm_model"]

    return {
        "provider": provider,
        "model": model,
        "source": "tenant" if bag else "env",
    }


def resolve_wiki_generation(
    db: Optional[Session] = None,
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Mode + provider for wiki agent (Copilot ⇒ CLI scripts only)."""
    mode = (settings.WIKI_GENERATION_MODE or "auto").lower()
    provider = (settings.LLM_PROVIDER or "claude").lower()
    if provider == "anthropic":
        provider = "claude"
    model: Optional[str] = settings.ANTHROPIC_MODEL
    if provider == "bedrock":
        model = settings.BEDROCK_MODEL_ID
    elif provider == "openai":
        model = "gpt-4"

    bag = _tenant_llm_bag(db, tenant_id)
    if bag.get("wiki_generation_mode") in ("cli", "api", "auto"):
        mode = bag["wiki_generation_mode"]

    wiki_provider = bag.get("wiki_generation_provider")
    if wiki_provider:
        provider = wiki_provider
    elif bag.get("llm_provider") in (
        "claude",
        "github_copilot",
        "openai",
        "bedrock",
        "ollama",
    ):
        # Legacy tenants stored wiki provider as llm_provider
        provider = (
            "claude" if bag["llm_provider"] == "anthropic" else bag["llm_provider"]
        )

    if bag.get("llm_model"):
        model = bag["llm_model"]

    if mode not in ("cli", "api", "auto"):
        mode = "auto"

    # Copilot wiki is CLI-only
    if provider == "github_copilot" and mode == "api":
        mode = "cli"

    agent_cli = "copilot" if provider == "github_copilot" else "claude"
    if provider not in ("claude", "github_copilot"):
        # API providers still use claude CLI when mode asks for shell path
        agent_cli = "claude"

    return {
        "wiki_generation_mode": mode,
        "wiki_generation_provider": provider,
        # Backward-compatible alias used by wiki_agent / tests
        "llm_provider": provider if provider != "github_copilot" else "claude",
        "llm_model": model,
        "agent_cli": agent_cli,
        "uses_copilot_cli": provider == "github_copilot",
        "bedrock_region": settings.BEDROCK_AWS_REGION or settings.AWS_REGION,
        "source": "tenant" if bag else "env",
    }


def resolve_code_generation(
    db: Optional[Session] = None,
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Tenant code-generation preference → adapter execution mode.

    Used by Build code/test and as Teammate fallback when no active seat.
    """
    bag = _tenant_llm_bag(db, tenant_id)
    provider = bag.get("code_generation_provider")
    if provider not in ("claude", "github_copilot"):
        # Inherit server SAVI_CODING_AGENT when unset
        env_mode = (settings.SAVI_CODING_AGENT or "heuristic").lower()
        return {
            "provider": None,
            "execution_mode": env_mode,
            "source": "env",
        }
    return {
        "provider": provider,
        "execution_mode": _CODE_GEN_TO_EXECUTION[provider],
        "source": "tenant",
    }


def get_other_llm_client(
    db: Optional[Session] = None,
    tenant_id: Optional[str] = None,
) -> LLMClient:
    resolved = resolve_other_llm(db, tenant_id)
    model = resolved.get("model")
    provider = resolved["provider"]
    return get_llm_client(
        provider,
        model_id=model if provider in ("bedrock", "ollama") else None,
    )


def get_build_code_llm_client(
    db: Optional[Session] = None,
    tenant_id: Optional[str] = None,
) -> LLMClient:
    """
    LLM client for Build Developer/Testing agents.

    Claude code-gen → Claude API. Copilot is CLI-oriented (Teammate); Build
    scaffolding still needs structured JSON via API, so fall back to other LLM.
    """
    code = resolve_code_generation(db, tenant_id)
    if code.get("provider") == "claude":
        return get_llm_client("claude")
    if code.get("provider") == "github_copilot":
        logger.info(
            "Tenant code_generation_provider=github_copilot; Build scaffolding "
            "uses Other LLM API (Copilot CLI is Teammate/wiki path)"
        )
    return get_other_llm_client(db, tenant_id)


def resolve_other_llm_tuple(
    db: Optional[Session] = None,
    tenant_id: Optional[str] = None,
) -> Tuple[str, Optional[str]]:
    r = resolve_other_llm(db, tenant_id)
    return r["provider"], r.get("model")
