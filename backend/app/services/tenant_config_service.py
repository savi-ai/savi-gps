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
CODE_GENERATION_PROVIDERS = ("claude", "github_copilot")
WIKI_GENERATION_PROVIDERS = (
    "claude",
    "github_copilot",
    "openai",
    "bedrock",
    "ollama",
)
OTHER_LLM_PROVIDERS = ("claude", "anthropic", "openai", "bedrock", "ollama")
DEFAULT_LLM_SETTINGS = {
    # None / missing means inherit from server env / defaults
    "code_generation_provider": None,  # claude | github_copilot
    "wiki_generation_mode": None,  # cli | api | auto
    "wiki_generation_provider": None,  # claude | github_copilot | openai | bedrock | ollama
    # Other LLM calls (chat, search, ideation agents)
    "llm_provider": None,  # claude | openai | bedrock | ollama
    "llm_model": None,
    # Push generated wiki markdown into the linked GitHub repo as a PR
    "wiki_github_export_enabled": False,
}

SPEC_LAYER_SETTINGS_KEY = "_spec_layer_settings"
CODING_AGENTS = ("kiro", "github_copilot", "cursor", "claude_code")
DEFAULT_SPEC_LAYER_SETTINGS = {
    # Opt-in: when false, Specs & Drift skips scanning on index
    "enabled": False,
    "specs_folder": ".github",
    "coding_agent": "github_copilot",  # kiro | github_copilot | cursor | claude_code
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

        code_gen = raw.get("code_generation_provider")
        if code_gen in CODE_GENERATION_PROVIDERS:
            out["code_generation_provider"] = code_gen

        mode = raw.get("wiki_generation_mode")
        if mode in ("cli", "api", "auto"):
            out["wiki_generation_mode"] = mode

        wiki_provider = raw.get("wiki_generation_provider")
        if wiki_provider in WIKI_GENERATION_PROVIDERS:
            out["wiki_generation_provider"] = wiki_provider
        else:
            # Backward compatible: old llm_provider drove wiki
            legacy = raw.get("llm_provider")
            if legacy in ("claude", "anthropic"):
                out["wiki_generation_provider"] = "claude"
            elif legacy in WIKI_GENERATION_PROVIDERS:
                out["wiki_generation_provider"] = legacy

        provider = raw.get("llm_provider")
        if provider in OTHER_LLM_PROVIDERS:
            out["llm_provider"] = "claude" if provider == "anthropic" else provider
        if raw.get("llm_model"):
            out["llm_model"] = str(raw["llm_model"])[:200]
        out["wiki_github_export_enabled"] = bool(
            raw.get(
                "wiki_github_export_enabled",
                DEFAULT_LLM_SETTINGS["wiki_github_export_enabled"],
            )
        )
        return out

    def get_spec_layer_settings(self, tenant_id: str) -> Dict[str, Any]:
        from app.services.intelligence.spec_drift_service import normalize_specs_folder

        config = self.get_or_create(tenant_id)
        raw = (config.capabilities or {}).get(SPEC_LAYER_SETTINGS_KEY) or {}
        agent = raw.get("coding_agent") or DEFAULT_SPEC_LAYER_SETTINGS["coding_agent"]
        if agent not in CODING_AGENTS:
            agent = DEFAULT_SPEC_LAYER_SETTINGS["coding_agent"]
        return {
            "enabled": bool(
                raw.get("enabled", DEFAULT_SPEC_LAYER_SETTINGS["enabled"])
            ),
            "specs_folder": normalize_specs_folder(
                raw.get("specs_folder"),
                default=DEFAULT_SPEC_LAYER_SETTINGS["specs_folder"],
            ),
            "coding_agent": agent,
        }

    def update_spec_layer_settings(
        self, tenant_id: str, settings_update: Dict[str, Any]
    ) -> TenantConfig:
        from app.services.intelligence.spec_drift_service import normalize_specs_folder

        config = self.get_or_create(tenant_id)
        caps = dict(config.capabilities or {})
        current = {
            **DEFAULT_SPEC_LAYER_SETTINGS,
            **(caps.get(SPEC_LAYER_SETTINGS_KEY) or {}),
        }
        if "enabled" in settings_update and settings_update["enabled"] is not None:
            current["enabled"] = bool(settings_update["enabled"])
        if "specs_folder" in settings_update and settings_update["specs_folder"] is not None:
            current["specs_folder"] = normalize_specs_folder(
                str(settings_update["specs_folder"]),
                default=DEFAULT_SPEC_LAYER_SETTINGS["specs_folder"],
            )
        if "coding_agent" in settings_update and settings_update["coding_agent"] is not None:
            agent = str(settings_update["coding_agent"]).strip()
            if agent not in CODING_AGENTS:
                raise ValueError(
                    "coding_agent must be one of: " + ", ".join(CODING_AGENTS)
                )
            current["coding_agent"] = agent
        caps[SPEC_LAYER_SETTINGS_KEY] = current
        self._preserve_bags(caps, config.capabilities or {})
        for key in ALL_CAPABILITY_KEYS:
            if key not in caps:
                caps[key] = default_capabilities().get(key, False)
        config.capabilities = caps
        self.db.commit()
        self.db.refresh(config)
        return config

    def update_llm_settings(
        self, tenant_id: str, settings_update: Dict[str, Any]
    ) -> TenantConfig:
        config = self.get_or_create(tenant_id)
        caps = dict(config.capabilities or {})
        current = dict(caps.get(LLM_SETTINGS_KEY) or {})

        if "code_generation_provider" in settings_update:
            code_gen = settings_update["code_generation_provider"]
            if code_gen is None or code_gen == "":
                current.pop("code_generation_provider", None)
            elif code_gen in CODE_GENERATION_PROVIDERS:
                current["code_generation_provider"] = code_gen
            else:
                raise ValueError(
                    "code_generation_provider must be claude or github_copilot"
                )

        if "wiki_generation_mode" in settings_update:
            mode = settings_update["wiki_generation_mode"]
            if mode is None or mode == "":
                current.pop("wiki_generation_mode", None)
            elif mode in ("cli", "api", "auto"):
                current["wiki_generation_mode"] = mode
            else:
                raise ValueError("wiki_generation_mode must be cli, api, or auto")

        if "wiki_generation_provider" in settings_update:
            wiki_provider = settings_update["wiki_generation_provider"]
            if wiki_provider is None or wiki_provider == "":
                current.pop("wiki_generation_provider", None)
            elif wiki_provider in WIKI_GENERATION_PROVIDERS:
                current["wiki_generation_provider"] = wiki_provider
            else:
                raise ValueError(
                    "wiki_generation_provider must be one of: "
                    + ", ".join(WIKI_GENERATION_PROVIDERS)
                )

        if "llm_provider" in settings_update:
            provider = settings_update["llm_provider"]
            if provider is None or provider == "":
                current.pop("llm_provider", None)
            elif provider in OTHER_LLM_PROVIDERS:
                current["llm_provider"] = (
                    "claude" if provider == "anthropic" else provider
                )
            else:
                raise ValueError(
                    "llm_provider must be claude, openai, bedrock, or ollama"
                )

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

        mode = current.get("wiki_generation_mode")
        wiki_p = current.get("wiki_generation_provider")
        if wiki_p == "github_copilot" and mode == "api":
            raise ValueError(
                "GitHub Copilot wiki generation requires CLI (or auto); "
                "API mode is not supported for Copilot"
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
        for bag in (ASSESSMENT_SETTINGS_KEY, LLM_SETTINGS_KEY, SPEC_LAYER_SETTINGS_KEY):
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
        llm_settings = {
            **self.get_llm_settings(config.tenant_id),
            "wiki_github_export_path": settings.WIKI_GITHUB_EXPORT_PATH,
            "wiki_app_github_export_path": settings.WIKI_APP_GITHUB_EXPORT_PATH,
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
            "llm_settings": llm_settings,
            "spec_layer_settings": self.get_spec_layer_settings(config.tenant_id),
            "llm_status": env_llm_status(),
            "onboarding_path": config.onboarding_path,
            "updated_at": config.updated_at.isoformat() if config.updated_at else None,
        }
