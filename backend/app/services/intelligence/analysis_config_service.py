"""Admin-configurable analysis attribute definitions and fleet-wide search."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.database import AnalysisAttributeDefinition, Repository, RepositoryAnalysisAttribute
from app.core.logger import logger

DEFAULT_ATTRIBUTES = [
    {
        "key": "java_version",
        "label": "Java Version",
        "category": "runtime",
        "data_type": "string",
        "extraction_hint": "Extract from pom.xml <java.version> or maven.compiler.source",
    },
    {
        "key": "node_version",
        "label": "Node.js Version",
        "category": "runtime",
        "data_type": "string",
        "extraction_hint": "Extract from package.json engines.node",
    },
    {
        "key": "python_version",
        "label": "Python Version",
        "category": "runtime",
        "data_type": "string",
        "extraction_hint": "Extract from pyproject.toml or .python-version",
    },
    {
        "key": "golden_image",
        "label": "Golden Image",
        "category": "infra",
        "data_type": "string",
        "extraction_hint": "Extract FROM line in Dockerfile",
    },
    {
        "key": "base_docker_image",
        "label": "Base Docker Image",
        "category": "infra",
        "data_type": "string",
        "extraction_hint": "First FROM instruction in Dockerfile",
    },
    {
        "key": "database_type",
        "label": "Database Type",
        "category": "infra",
        "data_type": "string",
        "extraction_hint": "Infer from docker-compose, ORM config, or connection strings",
    },
    {
        "key": "framework",
        "label": "Primary Framework",
        "category": "build",
        "data_type": "string",
        "extraction_hint": "e.g. FastAPI, Spring Boot, Next.js from dependencies",
    },
]


class AnalysisConfigService:
    def __init__(self, db: Session):
        self.db = db

    def seed_defaults(self, tenant_id: str, created_by: Optional[str] = None) -> int:
        created = 0
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
                    created_by=created_by,
                )
            )
            created += 1
        if created:
            self.db.commit()
            logger.info(f"Seeded {created} default analysis attributes for tenant {tenant_id}")
        return created

    def list_definitions(self, tenant_id: str, active_only: bool = True) -> List[Dict[str, Any]]:
        q = self.db.query(AnalysisAttributeDefinition).filter(
            AnalysisAttributeDefinition.tenant_id == tenant_id
        )
        if active_only:
            q = q.filter(AnalysisAttributeDefinition.is_active == True)
        defs = q.order_by(AnalysisAttributeDefinition.category, AnalysisAttributeDefinition.label).all()
        return [self._def_dict(d) for d in defs]

    def create_definition(
        self,
        tenant_id: str,
        key: str,
        label: str,
        category: str = "general",
        data_type: str = "string",
        extraction_hint: Optional[str] = None,
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
            category=category,
            data_type=data_type,
            extraction_hint=extraction_hint,
            is_active=True,
            is_searchable=True,
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

        for field in ("label", "description", "category", "data_type", "extraction_hint", "is_active", "is_searchable"):
            if field in updates:
                setattr(defn, field, updates[field])
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

    def _def_dict(self, d: AnalysisAttributeDefinition) -> Dict[str, Any]:
        return {
            "id": d.id,
            "key": d.key,
            "label": d.label,
            "description": d.description,
            "category": d.category,
            "data_type": d.data_type,
            "extraction_hint": d.extraction_hint,
            "is_active": d.is_active,
            "is_searchable": d.is_searchable,
        }

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
