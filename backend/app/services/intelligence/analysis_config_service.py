"""Admin-configurable analysis attribute definitions and fleet-wide search."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.database import AnalysisAttributeDefinition, Repository, RepositoryAnalysisAttribute
from app.core.logger import logger

VALID_REMEDIATION_SCOPES = frozenset({"simple_fix", "modernization", "either"})


def normalize_remediation_scope(value: Optional[str], *, default: str = "either") -> str:
    scope = (value or default).strip().lower()
    if scope not in VALID_REMEDIATION_SCOPES:
        return default
    return scope


# Seed definitions: extraction for wiki + optional modernization assessment signals.
DEFAULT_ATTRIBUTES: List[Dict[str, Any]] = [
    {
        "key": "java_version",
        "label": "Java Version",
        "category": "runtime",
        "data_type": "string",
        "extraction_hint": "Extract from pom.xml <java.version> or maven.compiler.source",
        "use_in_assessment": True,
        "assessment_weight": 3,
        "remediation_scope": "modernization",
        "assessment_rules": {
            "legacy_contains": ["1.8", "java 8", "java8", "jdk8"],
            "warn_contains": ["11", "java 11"],
            "good_contains": ["17", "21", "java 17", "java 21"],
            "missing_score": 35,
        },
        "recommendation_template": (
            "Plan a JDK upgrade path; Java 8/11 increase modernization risk and agent effort."
        ),
        "applies_when": {
            "any_file": ["pom.xml", "build.gradle", "build.gradle.kts"],
            "any_stack": ["java", "spring", "kotlin", "maven", "gradle"],
        },
    },
    {
        "key": "node_version",
        "label": "Node.js Version",
        "category": "runtime",
        "data_type": "string",
        "extraction_hint": "Extract from package.json engines.node",
        "use_in_assessment": True,
        "assessment_weight": 2,
        "remediation_scope": "modernization",
        "assessment_rules": {
            "legacy_contains": ["10", "12", "14"],
            "warn_contains": ["16"],
            "good_contains": ["18", "20", "22"],
            "missing_score": 40,
        },
        "recommendation_template": "Upgrade Node to an Active LTS release before large refactors.",
        "applies_when": {
            "any_file": ["package.json"],
            "any_stack": ["node", "javascript", "typescript", "next.js", "react", "vue"],
        },
    },
    {
        "key": "python_version",
        "label": "Python Version",
        "category": "runtime",
        "data_type": "string",
        "extraction_hint": "Extract from pyproject.toml or .python-version",
        "use_in_assessment": True,
        "assessment_weight": 2,
        "remediation_scope": "modernization",
        "assessment_rules": {
            "legacy_contains": ["2.7", "3.6", "3.7", "3.8"],
            "warn_contains": ["3.9"],
            "good_contains": ["3.10", "3.11", "3.12", "3.13"],
            "missing_score": 40,
        },
        "recommendation_template": "Move to a supported Python 3.10+ runtime for library and security support.",
        "applies_when": {
            "any_file": ["pyproject.toml", "requirements.txt", "setup.py", "Pipfile", ".python-version"],
            "any_stack": ["python", "django", "fastapi", "flask"],
        },
    },
    {
        "key": "framework",
        "label": "Primary Framework",
        "category": "build",
        "data_type": "string",
        "extraction_hint": "e.g. FastAPI, Spring Boot, Next.js from dependencies",
        "use_in_assessment": True,
        "assessment_weight": 3,
        "remediation_scope": "modernization",
        "assessment_rules": {
            "legacy_contains": [
                "spring boot 1",
                "spring boot 2",
                "struts",
                "jsf",
                "angularjs",
                "jquery",
            ],
            "warn_contains": ["spring boot 2.7", "vue 2", "react 16", "react 17"],
            "good_contains": ["spring boot 3", "next.js", "fastapi", "react 18", "react 19"],
            "missing_score": 45,
        },
        "recommendation_template": (
            "Framework major upgrades are high-leverage modernization work — scope in the plan."
        ),
    },
    {
        "key": "spring_boot_version",
        "label": "Spring Boot Version",
        "category": "build",
        "data_type": "string",
        "extraction_hint": "Extract from pom.xml spring-boot-starter-parent or gradle",
        "use_in_assessment": True,
        "assessment_weight": 3,
        "remediation_scope": "modernization",
        "assessment_rules": {
            "legacy_contains": ["1.", "2.0", "2.1", "2.2", "2.3", "2.4", "2.5"],
            "warn_contains": ["2.6", "2.7"],
            "good_contains": ["3."],
            "missing_score": 50,
        },
        "recommendation_template": "Spring Boot 2.x → 3.x is a common modernization track; estimate agent Code/Test stages accordingly.",
        "applies_when": {
            "any_file": ["pom.xml", "build.gradle", "build.gradle.kts"],
            "any_stack": ["spring", "java", "spring boot"],
        },
    },
    {
        "key": "golden_image",
        "label": "Golden Image",
        "category": "infra",
        "data_type": "string",
        "extraction_hint": "Extract FROM line in Dockerfile",
        "use_in_assessment": True,
        "assessment_weight": 2,
        "remediation_scope": "either",
        "assessment_rules": {
            "legacy_contains": ["jdk8", "java:8", "openjdk:8", "node:12", "node:14", "centos:7"],
            "warn_contains": ["jdk11", "openjdk:11", "node:16"],
            "good_contains": ["jdk17", "jdk21", "node:20", "node:22", "distroless", "alpine"],
            "missing_score": 45,
        },
        "recommendation_template": "Align container base images with supported LTS runtimes and org golden images.",
    },
    {
        "key": "base_docker_image",
        "label": "Base Docker Image",
        "category": "infra",
        "data_type": "string",
        "extraction_hint": "First FROM instruction in Dockerfile",
        "use_in_assessment": False,
        "assessment_weight": 1,
        "remediation_scope": "either",
        "assessment_rules": None,
        "recommendation_template": None,
    },
    {
        "key": "database_type",
        "label": "Database Type",
        "category": "infra",
        "data_type": "string",
        "extraction_hint": "Infer from docker-compose, ORM config, or connection strings",
        "use_in_assessment": True,
        "assessment_weight": 2,
        "remediation_scope": "modernization",
        "assessment_rules": {
            "legacy_contains": ["db2", "sybase", "informix", "access"],
            "warn_contains": ["oracle 11", "mysql 5.6", "mysql 5.7"],
            "good_contains": ["postgres", "postgresql", "mysql 8", "mongodb", "dynamodb"],
            "missing_score": 50,
        },
        "recommendation_template": "Data store choice drives migration risk — call out in Requirements/Tasks.",
    },
    {
        "key": "ci_cd_present",
        "label": "CI/CD Present",
        "category": "build",
        "data_type": "string",
        "extraction_hint": "Detect .github/workflows, Jenkinsfile, .gitlab-ci.yml, azure-pipelines",
        "use_in_assessment": True,
        "assessment_weight": 2,
        "remediation_scope": "simple_fix",
        "assessment_rules": {
            "legacy_contains": ["none", "missing", "no", "false"],
            "good_contains": ["github actions", "gitlab", "jenkins", "azure", "circle", "yes", "true"],
            "missing_score": 40,
        },
        "recommendation_template": "Add or modernize CI before large agent-driven code pushes.",
    },
]


_ASSESSMENT_FIELDS = (
    "use_in_assessment",
    "assessment_weight",
    "assessment_rules",
    "recommendation_template",
    "remediation_scope",
)


class AnalysisConfigService:
    def __init__(self, db: Session):
        self.db = db

    def seed_defaults(self, tenant_id: str, created_by: Optional[str] = None) -> int:
        created = 0
        updated = 0
        for item in DEFAULT_ATTRIBUTES:
            exists = (
                self.db.query(AnalysisAttributeDefinition)
                .filter(
                    AnalysisAttributeDefinition.tenant_id == tenant_id,
                    AnalysisAttributeDefinition.key == item["key"],
                )
                .first()
            )
            if exists:
                changed = False
                # Backfill assessment metadata on older seeds (no rules yet)
                if exists.assessment_rules is None and item.get("use_in_assessment"):
                    exists.use_in_assessment = bool(item.get("use_in_assessment"))
                    exists.assessment_weight = int(item.get("assessment_weight") or 1)
                    exists.assessment_rules = item.get("assessment_rules")
                    exists.recommendation_template = item.get("recommendation_template")
                    changed = True
                if not getattr(exists, "remediation_scope", None) and item.get("remediation_scope"):
                    exists.remediation_scope = normalize_remediation_scope(
                        item.get("remediation_scope")
                    )
                    changed = True
                if changed:
                    exists.updated_at = datetime.now()
                    updated += 1
                continue
            self.db.add(
                AnalysisAttributeDefinition(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    key=item["key"],
                    label=item["label"],
                    category=item["category"],
                    data_type=item["data_type"],
                    extraction_hint=item["extraction_hint"],
                    is_active=True,
                    is_searchable=True,
                    use_in_assessment=bool(item.get("use_in_assessment")),
                    assessment_weight=int(item.get("assessment_weight") or 1),
                    assessment_rules=item.get("assessment_rules"),
                    recommendation_template=item.get("recommendation_template"),
                    remediation_scope=normalize_remediation_scope(
                        item.get("remediation_scope")
                    ),
                    created_by=created_by,
                )
            )
            created += 1
        if created or updated:
            self.db.commit()
            logger.info(
                "Analysis attributes for tenant %s: created=%s assessment_backfill=%s",
                tenant_id,
                created,
                updated,
            )
        return created

    def list_definitions(self, tenant_id: str, active_only: bool = True) -> List[Dict[str, Any]]:
        q = self.db.query(AnalysisAttributeDefinition).filter(
            AnalysisAttributeDefinition.tenant_id == tenant_id
        )
        if active_only:
            q = q.filter(AnalysisAttributeDefinition.is_active == True)
        defs = q.order_by(AnalysisAttributeDefinition.category, AnalysisAttributeDefinition.label).all()
        return [self._def_dict(d) for d in defs]

    def list_assessment_definitions(self, tenant_id: str) -> List[Dict[str, Any]]:
        """Active definitions flagged for modernization assessment."""
        self.seed_defaults(tenant_id)
        q = (
            self.db.query(AnalysisAttributeDefinition)
            .filter(
                AnalysisAttributeDefinition.tenant_id == tenant_id,
                AnalysisAttributeDefinition.is_active == True,
                AnalysisAttributeDefinition.use_in_assessment == True,
            )
            .order_by(
                AnalysisAttributeDefinition.assessment_weight.desc(),
                AnalysisAttributeDefinition.label,
            )
        )
        return [self._def_dict(d, include_applies_when=True) for d in q.all()]

    def create_definition(
        self,
        tenant_id: str,
        key: str,
        label: str,
        category: str = "general",
        data_type: str = "string",
        extraction_hint: Optional[str] = None,
        description: Optional[str] = None,
        use_in_assessment: bool = False,
        assessment_weight: int = 1,
        assessment_rules: Optional[Dict[str, Any]] = None,
        recommendation_template: Optional[str] = None,
        remediation_scope: Optional[str] = "either",
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        existing = (
            self.db.query(AnalysisAttributeDefinition)
            .filter(
                AnalysisAttributeDefinition.tenant_id == tenant_id,
                AnalysisAttributeDefinition.key == key,
            )
            .first()
        )
        if existing:
            raise ValueError(f"Attribute key '{key}' already exists")

        defn = AnalysisAttributeDefinition(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            key=key,
            label=label,
            description=description,
            category=category,
            data_type=data_type,
            extraction_hint=extraction_hint,
            is_active=True,
            is_searchable=True,
            use_in_assessment=bool(use_in_assessment),
            assessment_weight=max(1, min(5, int(assessment_weight or 1))),
            assessment_rules=assessment_rules,
            recommendation_template=recommendation_template,
            remediation_scope=normalize_remediation_scope(remediation_scope),
            created_by=created_by,
        )
        self.db.add(defn)
        self.db.commit()
        self.db.refresh(defn)
        return self._def_dict(defn)

    def update_definition(
        self, tenant_id: str, definition_id: str, updates: Dict[str, Any]
    ) -> Dict[str, Any]:
        defn = (
            self.db.query(AnalysisAttributeDefinition)
            .filter(
                AnalysisAttributeDefinition.id == definition_id,
                AnalysisAttributeDefinition.tenant_id == tenant_id,
            )
            .first()
        )
        if not defn:
            raise ValueError("Definition not found")

        allowed = (
            "label",
            "description",
            "category",
            "data_type",
            "extraction_hint",
            "is_active",
            "is_searchable",
            *_ASSESSMENT_FIELDS,
        )
        for field in allowed:
            if field not in updates:
                continue
            value = updates[field]
            if field == "assessment_weight" and value is not None:
                value = max(1, min(5, int(value)))
            if field == "remediation_scope":
                value = normalize_remediation_scope(value)
            setattr(defn, field, value)
        defn.updated_at = datetime.now()
        self.db.commit()
        return self._def_dict(defn)

    def save_repository_attributes(
        self,
        tenant_id: str,
        repository_id: str,
        index_run_id: Optional[str],
        attributes: List[Dict[str, Any]],
    ) -> int:
        self.db.query(RepositoryAnalysisAttribute).filter(
            RepositoryAnalysisAttribute.repository_id == repository_id,
            RepositoryAnalysisAttribute.index_run_id == index_run_id,
        ).delete(synchronize_session=False)

        count = 0
        for attr in attributes:
            self.db.add(
                RepositoryAnalysisAttribute(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    repository_id=repository_id,
                    index_run_id=index_run_id,
                    attribute_key=attr.get("key", ""),
                    attribute_label=attr.get("label", attr.get("key", "")),
                    value_text=str(attr.get("value", ""))[:2000] if attr.get("value") is not None else None,
                    value_json=attr.get("value_json"),
                    source_file=attr.get("source_file"),
                    line_start=attr.get("line_start"),
                    confidence=attr.get("confidence", "medium"),
                )
            )
            count += 1
        self.db.flush()
        return count

    def list_repository_attributes(
        self, tenant_id: str, repository_id: str, latest_only: bool = True
    ) -> List[Dict[str, Any]]:
        q = self.db.query(RepositoryAnalysisAttribute).filter(
            RepositoryAnalysisAttribute.tenant_id == tenant_id,
            RepositoryAnalysisAttribute.repository_id == repository_id,
        )
        if latest_only:
            attrs = q.order_by(RepositoryAnalysisAttribute.extracted_at.desc()).all()
            seen = set()
            result = []
            for a in attrs:
                if a.attribute_key in seen:
                    continue
                seen.add(a.attribute_key)
                result.append(self._attr_dict(a))
            return result
        return [self._attr_dict(a) for a in q.all()]

    def search_repositories(
        self,
        tenant_id: str,
        attribute_key: Optional[str] = None,
        value_contains: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        q = (
            self.db.query(RepositoryAnalysisAttribute, Repository)
            .join(Repository, Repository.id == RepositoryAnalysisAttribute.repository_id)
            .filter(RepositoryAnalysisAttribute.tenant_id == tenant_id)
        )
        if attribute_key:
            q = q.filter(RepositoryAnalysisAttribute.attribute_key == attribute_key)
        if value_contains:
            q = q.filter(
                or_(
                    RepositoryAnalysisAttribute.value_text.ilike(f"%{value_contains}%"),
                    RepositoryAnalysisAttribute.attribute_label.ilike(f"%{value_contains}%"),
                )
            )
        rows = q.order_by(RepositoryAnalysisAttribute.extracted_at.desc()).limit(limit).all()
        return [
            {
                **self._attr_dict(attr),
                "repository_name": repo.name,
                "repository_full_name": repo.github_full_name,
                "repository_url": repo.url,
            }
            for attr, repo in rows
        ]

    def _def_dict(
        self, d: AnalysisAttributeDefinition, *, include_applies_when: bool = False
    ) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "id": d.id,
            "key": d.key,
            "label": d.label,
            "description": d.description,
            "category": d.category,
            "data_type": d.data_type,
            "extraction_hint": d.extraction_hint,
            "is_active": d.is_active,
            "is_searchable": d.is_searchable,
            "use_in_assessment": bool(d.use_in_assessment),
            "assessment_weight": int(d.assessment_weight or 1),
            "assessment_rules": d.assessment_rules,
            "recommendation_template": d.recommendation_template,
            "remediation_scope": normalize_remediation_scope(
                getattr(d, "remediation_scope", None)
            ),
        }
        if include_applies_when:
            from app.services.modernize.signal_applicability import default_applies_when_for_key

            seed = default_applies_when_for_key(d.key)
            if seed:
                out["applies_when"] = seed
        return out

    def _attr_dict(self, a: RepositoryAnalysisAttribute) -> Dict[str, Any]:
        return {
            "id": a.id,
            "repository_id": a.repository_id,
            "index_run_id": a.index_run_id,
            "attribute_key": a.attribute_key,
            "attribute_label": a.attribute_label,
            "value_text": a.value_text,
            "value_json": a.value_json,
            "source_file": a.source_file,
            "line_start": a.line_start,
            "confidence": a.confidence,
            "extracted_at": a.extracted_at.isoformat() if a.extracted_at else None,
        }
