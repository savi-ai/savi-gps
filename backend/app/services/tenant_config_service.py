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
        # Keep known capability booleans
        for key in ALL_CAPABILITY_KEYS:
            if key not in caps:
                caps[key] = default_capabilities().get(key, False)
        config.capabilities = caps
        self.db.commit()
        self.db.refresh(config)
        return config

    def set_onboarding_path(self, tenant_id: str, path: str) -> TenantConfig:
        if path not in ONBOARDING_PATHS:
            raise ValueError(f"Invalid onboarding path: {path}")

        config = self.get_or_create(tenant_id)
        assessment = (config.capabilities or {}).get(ASSESSMENT_SETTINGS_KEY)
        caps = capabilities_for_onboarding(path)
        if assessment is not None:
            caps[ASSESSMENT_SETTINGS_KEY] = assessment
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
        assessment = existing.get(ASSESSMENT_SETTINGS_KEY)
        bool_caps = {
            k: bool(v)
            for k, v in {**default_capabilities(), **existing, **capabilities}.items()
            if k in ALL_CAPABILITY_KEYS
        }
        if assessment is not None:
            bool_caps[ASSESSMENT_SETTINGS_KEY] = assessment
        config.capabilities = bool_caps
        self.db.commit()
        self.db.refresh(config)
        return config

    def to_dict(self, config: TenantConfig) -> Dict[str, Any]:
        raw = config.capabilities or {}
        assessment = {
            **DEFAULT_ASSESSMENT_SETTINGS,
            **(raw.get(ASSESSMENT_SETTINGS_KEY) or {}),
        }
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
            "onboarding_path": config.onboarding_path,
            "updated_at": config.updated_at.isoformat() if config.updated_at else None,
        }
