"""Tenant capability and onboarding configuration"""
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.database import TenantConfig
from app.core.logger import logger
import uuid
import os


def _capability_flag(env_key: str) -> bool:
    """Env override, else follow INTELLIGENCE_ENABLED."""
    raw = os.getenv(env_key)
    if raw is not None:
        return raw.lower() == "true"
    return settings.INTELLIGENCE_ENABLED


def default_capabilities() -> Dict[str, bool]:
    """Default tenant capabilities — Build on, Intelligence/Fleet gated by env flags."""
    return {
        "build": True,
        "intelligence": settings.INTELLIGENCE_ENABLED,
        "fleet": settings.FLEET_ENABLED,
        "modernize": _capability_flag("MODERNIZE_ENABLED"),
        "portfolio": _capability_flag("PORTFOLIO_ENABLED"),
    }


ONBOARDING_PATHS = ("wiki_only", "modernization", "full")

ALL_CAPABILITY_KEYS = ("build", "intelligence", "fleet", "modernize", "portfolio")

# Stored alongside capabilities in tenant_configs.capabilities JSON (non-boolean bag).
ASSESSMENT_SETTINGS_KEY = "_assessment_settings"
DEFAULT_ASSESSMENT_SETTINGS = {
    "auto_assess_on_repo_index": False,
    "auto_assess_on_application_analysis": False,
}

LLM_SETTINGS_KEY = "_llm_settings"
DEFAULT_LLM_SETTINGS = {
    # None / missing means inherit from server env
    "wiki_generation_mode": None,  # cli | api | auto
    "llm_provider": None,  # claude | openai | bedrock | ollama
    "llm_model": None,
    # Push generated wiki markdown into the linked GitHub repo as a PR
    "wiki_github_export_enabled": False,
}


def capabilities_for_onboarding(path: str) -> Dict[str, bool]:
    """Map onboarding path selection to tenant capabilities."""
    if path == "wiki_only":
        return {
            "build": False,
            "intelligence": True,
            "fleet": False,
            "modernize": False,
            "portfolio": settings.PORTFOLIO_ENABLED,
        }
    if path == "modernization":
        return {
            "build": True,
            "intelligence": True,
            "fleet": False,
            "modernize": True,
            "portfolio": settings.PORTFOLIO_ENABLED,
        }
    if path == "full":
        return {
            "build": True,
            "intelligence": True,
            "fleet": settings.FLEET_ENABLED,
            "modernize": True,
            "portfolio": settings.PORTFOLIO_ENABLED,
        }
    return default_capabilities()


class TenantConfigService:
    def __init__(self, db: Session):
        self.db = db

    def get_or_create(self, tenant_id: str) -> TenantConfig:
        config = self.db.query(TenantConfig).filter(
            TenantConfig.tenant_id == tenant_id
        ).first()
        if config:
            return config

        config = TenantConfig(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            capabilities=default_capabilities(),
            onboarding_path=None,
        )
        self.db.add(config)
        self.db.commit()
        self.db.refresh(config)
        logger.info(f"Created default tenant config for tenant {tenant_id}")
        return config

    def get_capabilities(self, tenant_id: str) -> Dict[str, bool]:
        config = self.get_or_create(tenant_id)
        raw = config.capabilities or {}
        merged = {**default_capabilities(), **raw}
        # Strip non-capability bags so callers only see bool flags
        return {k: bool(merged.get(k, False)) for k in ALL_CAPABILITY_KEYS}

    def get_assessment_settings(self, tenant_id: str) -> Dict[str, bool]:
        config = self.get_or_create(tenant_id)
        raw = (config.capabilities or {}).get(ASSESSMENT_SETTINGS_KEY) or {}
        return {
            **DEFAULT_ASSESSMENT_SETTINGS,
            **{k: bool(raw[k]) for k in DEFAULT_ASSESSMENT_SETTINGS if k in raw},
        }

    def update_assessment_settings(
        self, tenant_id: str, settings: Dict[str, bool]
    ) -> TenantConfig:
        config = self.get_or_create(tenant_id)
        caps = dict(config.capabilities or {})
        current = {
            **DEFAULT_ASSESSMENT_SETTINGS,
            **(caps.get(ASSESSMENT_SETTINGS_KEY) or {}),
        }
        for key in DEFAULT_ASSESSMENT_SETTINGS:
            if key in settings and settings[key] is not None:
                current[key] = bool(settings[key])
        caps[ASSESSMENT_SETTINGS_KEY] = current
        self._preserve_bags(caps, config.capabilities or {})
        for key in ALL_CAPABILITY_KEYS:
            if key not in caps:
                caps[key] = default_capabilities().get(key, False)
        config.capabilities = caps
        self.db.commit()
        self.db.refresh(config)
        return config

    def get_llm_settings(self, tenant_id: str) -> Dict[str, Any]:
        config = self.get_or_create(tenant_id)
        raw = (config.capabilities or {}).get(LLM_SETTINGS_KEY) or {}
        out: Dict[str, Any] = {}
        mode = raw.get("wiki_generation_mode")
        if mode in ("cli", "api", "auto"):
            out["wiki_generation_mode"] = mode
        provider = raw.get("llm_provider")
        if provider in ("claude", "anthropic", "openai", "bedrock", "ollama"):
            out["llm_provider"] = provider
        if raw.get("llm_model"):
            out["llm_model"] = str(raw["llm_model"])[:200]
        out["wiki_github_export_enabled"] = bool(
            raw.get(
                "wiki_github_export_enabled",
                DEFAULT_LLM_SETTINGS["wiki_github_export_enabled"],
            )
        )
        return out

    def update_llm_settings(
        self, tenant_id: str, settings_update: Dict[str, Any]
    ) -> TenantConfig:
        config = self.get_or_create(tenant_id)
        caps = dict(config.capabilities or {})
        current = dict(caps.get(LLM_SETTINGS_KEY) or {})
        if "wiki_generation_mode" in settings_update:
            mode = settings_update["wiki_generation_mode"]
            if mode is None or mode == "":
                current.pop("wiki_generation_mode", None)
            elif mode in ("cli", "api", "auto"):
                current["wiki_generation_mode"] = mode
            else:
                raise ValueError("wiki_generation_mode must be cli, api, or auto")
        if "llm_provider" in settings_update:
            provider = settings_update["llm_provider"]
            if provider is None or provider == "":
                current.pop("llm_provider", None)
            elif provider in ("claude", "anthropic", "openai", "bedrock", "ollama"):
                current["llm_provider"] = provider
            else:
                raise ValueError("invalid llm_provider")
        if "llm_model" in settings_update:
            model = settings_update["llm_model"]
            if model is None or model == "":
                current.pop("llm_model", None)
            else:
                current["llm_model"] = str(model)[:200]
        if "wiki_github_export_enabled" in settings_update:
            current["wiki_github_export_enabled"] = bool(
                settings_update["wiki_github_export_enabled"]
            )
        caps[LLM_SETTINGS_KEY] = current
        self._preserve_bags(caps, config.capabilities or {})
        for key in ALL_CAPABILITY_KEYS:
            if key not in caps:
                caps[key] = default_capabilities().get(key, False)
        config.capabilities = caps
        self.db.commit()
        self.db.refresh(config)
        return config

    @staticmethod
    def _preserve_bags(target: Dict[str, Any], existing: Dict[str, Any]) -> None:
        for bag in (ASSESSMENT_SETTINGS_KEY, LLM_SETTINGS_KEY):
            if bag not in target and bag in existing:
                target[bag] = existing[bag]

    def set_onboarding_path(self, tenant_id: str, path: str) -> TenantConfig:
        if path not in ONBOARDING_PATHS:
            raise ValueError(f"Invalid onboarding path: {path}")

        config = self.get_or_create(tenant_id)
        existing = config.capabilities or {}
        caps = capabilities_for_onboarding(path)
        self._preserve_bags(caps, existing)
        config.onboarding_path = path
        config.capabilities = caps
        self.db.commit()
        self.db.refresh(config)
        return config

    def update_capabilities(
        self, tenant_id: str, capabilities: Dict[str, bool]
    ) -> TenantConfig:
        config = self.get_or_create(tenant_id)
        existing = dict(config.capabilities or {})
        bool_caps = {
            k: bool(v)
            for k, v in {**default_capabilities(), **existing, **capabilities}.items()
            if k in ALL_CAPABILITY_KEYS
        }
        self._preserve_bags(bool_caps, existing)
        config.capabilities = bool_caps
        self.db.commit()
        self.db.refresh(config)
        return config

    def to_dict(self, config: TenantConfig) -> Dict[str, Any]:
        from app.services.intelligence.wiki_generation_settings import env_llm_status

        raw = config.capabilities or {}
        assessment = {
            **DEFAULT_ASSESSMENT_SETTINGS,
            **(raw.get(ASSESSMENT_SETTINGS_KEY) or {}),
        }
        llm_raw = raw.get(LLM_SETTINGS_KEY) or {}
        return {
            "tenant_id": config.tenant_id,
            "capabilities": {
                **default_capabilities(),
                **{k: bool(raw.get(k, default_capabilities().get(k, False))) for k in ALL_CAPABILITY_KEYS},
            },
            "assessment_settings": {
                k: bool(assessment.get(k, DEFAULT_ASSESSMENT_SETTINGS[k]))
                for k in DEFAULT_ASSESSMENT_SETTINGS
            },
            "llm_settings": {
                "wiki_generation_mode": llm_raw.get("wiki_generation_mode"),
                "llm_provider": llm_raw.get("llm_provider"),
                "llm_model": llm_raw.get("llm_model"),
                "wiki_github_export_enabled": bool(
                    llm_raw.get(
                        "wiki_github_export_enabled",
                        DEFAULT_LLM_SETTINGS["wiki_github_export_enabled"],
                    )
                ),
                "wiki_github_export_path": settings.WIKI_GITHUB_EXPORT_PATH,
            },
            "llm_status": env_llm_status(),
            "onboarding_path": config.onboarding_path,
            "updated_at": config.updated_at.isoformat() if config.updated_at else None,
        }
