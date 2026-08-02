"""Policy management router"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid

from app.core.database import (
    get_db, User, Tenant, Role, UserRole,
    Policy, PolicyVersion, PolicyAttachment, PolicyBundle, BuildingBlock, PolicyAuditLog, PolicyCategory
)
from app.core.auth import get_current_user, has_permission
from app.core.tenant_isolation import verify_tenant_access
from app.core.audit_service import log_policy_audit, POLICY_CREATED
from app.services.policy_merge_engine import PolicyMergeEngine
from app.core.logger import logger
from app.core.storage import storage_service
from pathlib import Path
import re

router = APIRouter(prefix="/policies", tags=["policies"])


# ============================================================================
# Pydantic Models
# ============================================================================

class PolicyCreate(BaseModel):
    policy_id: str = Field(..., description="Unique policy identifier (e.g., PIPE-001)")
    name: str
    description: Optional[str] = None
    category: str  # ideation, requirements, stories, architecture, coding, testing, security, infra, building_blocks
    applies_to: Optional[List[str]] = None
    stacks: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    content: Dict[str, Any] = Field(..., description="Policy content as JSON")
    content_yaml: Optional[str] = None
    requires_approval: bool = False


class PolicyUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    applies_to: Optional[List[str]] = None
    stacks: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    content: Optional[Dict[str, Any]] = None
    content_yaml: Optional[str] = None
    requires_approval: Optional[bool] = None


class PolicyVersionCreate(BaseModel):
    version_number: str
    content: Dict[str, Any]
    content_yaml: Optional[str] = None
    is_draft: bool = True
    requires_approval: bool = False


class PolicyResponse(BaseModel):
    id: str
    policy_id: str
    name: str
    description: Optional[str]
    category: str
    status: str
    applies_to: Optional[List[str]]
    stacks: Optional[List[str]]
    tags: Optional[List[str]]
    active_version_id: Optional[str]
    active_version_number: Optional[str]
    created_by: Optional[str]
    updated_by: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PolicyVersionResponse(BaseModel):
    id: str
    policy_id: str
    version_number: str
    content: Dict[str, Any]
    content_yaml: Optional[str]
    is_draft: bool
    requires_approval: bool
    approved_by: Optional[str]
    approved_at: Optional[datetime]
    created_by: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class BuildingBlockCreate(BaseModel):
    name: str
    type: str  # repo, template, pdf, yaml, json
    description: Optional[str] = None
    url: Optional[str] = None
    applicable_stacks: Optional[List[str]] = None
    enforcement: str = "recommended"  # required, recommended, deprecated
    version: Optional[str] = None
    owner: Optional[str] = None
    usage_guidance: Optional[str] = None
    when_to_use: Optional[str] = None
    tags: Optional[List[str]] = None


class BuildingBlockResponse(BaseModel):
    id: str
    name: str
    type: str
    description: Optional[str]
    url: Optional[str]
    applicable_stacks: Optional[List[str]]
    enforcement: str
    version: Optional[str]
    owner: Optional[str]
    usage_guidance: Optional[str]
    when_to_use: Optional[str]
    tags: Optional[List[str]]
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Policy Endpoints
# ============================================================================

@router.get("", response_model=List[PolicyResponse])
async def list_policies(
    category: Optional[str] = Query(None, description="Filter by category"),
    status: Optional[str] = Query(None, description="Filter by status (draft, active, deprecated)"),
    applies_to: Optional[str] = Query(None, description="Filter by applies_to"),
    stack: Optional[str] = Query(None, description="Filter by stack"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    search: Optional[str] = Query(None, description="Search in name and description"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """List all policies with optional filters"""
    if not has_permission(user, "can_manage_policies", db):
        raise HTTPException(status_code=403, detail="Permission denied")
    
    query = db.query(Policy).filter(Policy.tenant_id == user.tenant_id)
    
    if category:
        query = query.filter(Policy.category == category)
    if status:
        query = query.filter(Policy.status == status)
    if applies_to:
        query = query.filter(Policy.applies_to.contains([applies_to]))
    if stack:
        query = query.filter(Policy.stacks.contains([stack]))
    if tag:
        query = query.filter(Policy.tags.contains([tag]))
    if search:
        query = query.filter(
            or_(
                Policy.name.ilike(f"%{search}%"),
                Policy.description.ilike(f"%{search}%")
            )
        )
    
    policies = query.order_by(Policy.updated_at.desc()).all()
    
    result = []
    for policy in policies:
        version_number = None
        if policy.active_version:
            version_number = policy.active_version.version_number
        elif policy.active_version_id:
            ver = (
                db.query(PolicyVersion)
                .filter(PolicyVersion.id == policy.active_version_id)
                .first()
            )
            if ver:
                version_number = ver.version_number
        policy_dict = {
            "id": policy.id,
            "policy_id": policy.policy_id,
            "name": policy.name,
            "description": policy.description,
            "category": policy.category,
            "status": policy.status,
            "applies_to": policy.applies_to,
            "stacks": policy.stacks,
            "tags": policy.tags,
            "active_version_id": policy.active_version_id,
            "active_version_number": version_number,
            "created_by": policy.created_by,
            "updated_by": policy.updated_by,
            "created_at": policy.created_at,
            "updated_at": policy.updated_at
        }
        result.append(PolicyResponse(**policy_dict))
    
    return result


@router.post("/load-defaults", status_code=status.HTTP_200_OK)
async def load_default_policies(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Load default policies from docs/default_agentic_ai_policies/"""
    if not has_permission(user, "can_manage_policies", db):
        raise HTTPException(status_code=403, detail="Permission denied")
    
    # Path to default policies
    project_root = Path(__file__).parent.parent.parent.parent
    defaults_dir = project_root / "docs" / "default_agentic_ai_policies"
    
    if not defaults_dir.exists():
        raise HTTPException(status_code=404, detail="Default policies directory not found")
    
    loaded_count = 0
    
    # Map of file names to policy metadata
    policy_map = {
        "01_idea_ideation_policy.md": {
            "policy_id": "IDEA-001",
            "name": "Idea & Ideation Standards",
            "category": "ideation"
        },
        "02_requirements_and_features_policy.md": {
            "policy_id": "REQ-001",
            "name": "Requirements & Feature Generation Standards",
            "category": "requirements"
        },
        "03_coding_standards_policy.md": {
            "policy_id": "CODE-001",
            "name": "Coding Standards",
            "category": "coding"
        },
        "04_architectural_standards_policy.md": {
            "policy_id": "ARCH-001",
            "name": "Architectural Standards",
            "category": "architecture"
        },
        "05_testing_and_pipeline_standards_policy.md": {
            "policy_id": "TEST-001",
            "name": "Testing & Pipeline Standards",
            "category": "testing"
        }
    }
    
    for file_path in defaults_dir.glob("*.md"):
        filename = file_path.name
        if filename not in policy_map:
            continue
        
        metadata = policy_map[filename]
        
        # Check if policy already exists
        existing = db.query(Policy).filter(
            and_(
                Policy.policy_id == metadata["policy_id"],
                Policy.tenant_id == user.tenant_id
            )
        ).first()
        
        if existing:
            logger.info(f"Policy {metadata['policy_id']} already exists, skipping")
            continue
        
        # Read markdown content
        with open(file_path, 'r') as f:
            content = f.read()
        
        # Convert markdown to structured content
        content_dict = {
            "source": "default",
            "markdown": content,
            "title": metadata["name"],
            "filename": filename
        }
        
        # Create policy
        policy = Policy(
            id=str(uuid.uuid4()),
            tenant_id=user.tenant_id,
            policy_id=metadata["policy_id"],
            name=metadata["name"],
            description=f"Default policy loaded from {filename}",
            category=metadata["category"],
            status="active",
            created_by=user.id,
            updated_by=user.id
        )
        db.add(policy)
        db.flush()
        
        # Save to storage
        storage_key = storage_service.save_policy_content(
            tenant_id=user.tenant_id or "default",
            policy_id=metadata["policy_id"],
            category=metadata["category"],
            content=content_dict,
            version="1.0.0",
            content_yaml=None
        )
        
        # Create version
        version = PolicyVersion(
            id=str(uuid.uuid4()),
            policy_id=policy.id,
            version_number="1.0.0",
            content=content_dict,
            content_yaml=None,
            storage_key=storage_key,
            is_draft=False,
            requires_approval=False,
            created_by=user.id
        )
        db.add(version)
        
        # Set as active version
        policy.active_version_id = version.id
        
        # Create audit log
        audit_log = PolicyAuditLog(
            id=str(uuid.uuid4()),
            tenant_id=user.tenant_id,
            policy_id=policy.id,
            action_type="created",
            user_id=user.id,
            new_version=version.version_number
        )
        db.add(audit_log)
        
        loaded_count += 1
    
    db.commit()
    
    return {"message": f"Loaded {loaded_count} default policies", "count": loaded_count}


@router.post("/import-sops", status_code=status.HTTP_200_OK)
async def import_sops_as_policies(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Import file-based SOPs (backend/sops/*.yaml) into the tenant Policy catalog.

    Keeps Build/validation SOPs available under Admin → Policies so the separate
    SOPs UI is unnecessary. Skips SOPs that already exist for this tenant.
    """
    if not has_permission(user, "can_manage_policies", db):
        raise HTTPException(status_code=403, detail="Permission denied")

    from app.services.sop_service import sop_service

    try:
        sop_service.reload_sops()
    except Exception as e:
        logger.warning("SOP reload before import failed: %s", e)

    imported = 0
    skipped = 0
    for sop in sop_service.get_all_sops():
        policy_key = (sop.id or "").upper().replace("_", "-")
        if not policy_key:
            continue

        existing = (
            db.query(Policy)
            .filter(
                and_(
                    Policy.policy_id == policy_key,
                    Policy.tenant_id == user.tenant_id,
                )
            )
            .first()
        )
        if existing:
            skipped += 1
            continue

        tags = list(sop.tags or [])
        if "sop" not in [t.lower() for t in tags]:
            tags = ["sop", *tags]

        content_dict = {
            "source": "sop_yaml",
            "sop_id": sop.id,
            "title": sop.title or sop.name,
            "version": sop.version,
            "category": sop.category,
            "description": sop.description,
            "rules": [r.model_dump() if hasattr(r, "model_dump") else r.dict() for r in (sop.rules or [])],
            "checks": [c.model_dump() if hasattr(c, "model_dump") else c.dict() for c in (sop.checks or [])],
            "remediation_hints": sop.remediation_hints or {},
            "applies_to": list(sop.applies_to or []),
            "enforcement": sop.enforcement,
            "validation": list(sop.validation or []),
        }

        policy = Policy(
            id=str(uuid.uuid4()),
            tenant_id=user.tenant_id,
            policy_id=policy_key,
            name=sop.title or sop.name,
            description=sop.description,
            category=(sop.category or "coding").lower().replace("-", "_"),
            status=sop.status if sop.status in ("draft", "active", "deprecated") else "active",
            applies_to=list(sop.applies_to or []),
            tags=tags,
            created_by=user.id,
            updated_by=user.id,
        )
        db.add(policy)
        db.flush()

        version_number = sop.version or "1.0.0"
        try:
            storage_key = storage_service.save_policy_content(
                tenant_id=user.tenant_id or "default",
                policy_id=policy_key,
                category=policy.category,
                content=content_dict,
                version=version_number,
                content_yaml=None,
            )
        except Exception as e:
            logger.warning("Storage save for imported SOP %s failed: %s", sop.id, e)
            storage_key = None

        version = PolicyVersion(
            id=str(uuid.uuid4()),
            policy_id=policy.id,
            version_number=version_number,
            content=content_dict,
            content_yaml=None,
            storage_key=storage_key,
            is_draft=False,
            requires_approval=False,
            created_by=user.id,
        )
        db.add(version)
        policy.active_version_id = version.id

        db.add(
            PolicyAuditLog(
                id=str(uuid.uuid4()),
                tenant_id=user.tenant_id,
                policy_id=policy.id,
                action_type="created",
                user_id=user.id,
                new_version=version.version_number,
            )
        )
        imported += 1

    db.commit()
    return {
        "message": f"Imported {imported} SOPs as policies ({skipped} already present)",
        "count": imported,
        "skipped": skipped,
    }


@router.post("/seed-modernize-readiness", status_code=status.HTTP_200_OK)
async def seed_modernize_readiness_policy(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create the default Modernize readiness policy (machine-readable rules) if missing."""
    if not has_permission(user, "can_manage_policies", db):
        raise HTTPException(status_code=403, detail="Permission denied")

    from app.services.modernize.policy_readiness import (
        DEFAULT_MODERNIZE_POLICY_CONTENT,
        MODERNIZE_CATEGORY,
        MODERNIZE_TAG,
    )

    policy_key = "MOD-READY-001"
    existing = (
        db.query(Policy)
        .filter(
            and_(
                Policy.policy_id == policy_key,
                Policy.tenant_id == user.tenant_id,
            )
        )
        .first()
    )
    if existing:
        return {
            "message": "Modernize readiness policy already exists",
            "count": 0,
            "policy_id": existing.id,
            "skipped": True,
        }

    content = dict(DEFAULT_MODERNIZE_POLICY_CONTENT)
    policy = Policy(
        id=str(uuid.uuid4()),
        tenant_id=user.tenant_id,
        policy_id=policy_key,
        name="Modernization Readiness Standards",
        description=(
            "Machine-readable rules that clamp modernization readiness scores "
            "(Java ≥17, required wiki sections, citation floor, tests, index freshness)."
        ),
        category=MODERNIZE_CATEGORY,
        status="active",
        applies_to=["backend", "architecture"],
        tags=[MODERNIZE_TAG, "sop"],
        level="tenant",
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(policy)
    db.flush()

    try:
        storage_key = storage_service.save_policy_content(
            tenant_id=user.tenant_id or "default",
            policy_id=policy_key,
            category=MODERNIZE_CATEGORY,
            content=content,
            version="1.0.0",
            content_yaml=None,
        )
    except Exception as e:
        logger.warning("Storage save for modernize policy failed: %s", e)
        storage_key = None

    version = PolicyVersion(
        id=str(uuid.uuid4()),
        policy_id=policy.id,
        version_number="1.0.0",
        content=content,
        content_yaml=None,
        storage_key=storage_key,
        is_draft=False,
        requires_approval=False,
        created_by=user.id,
    )
    db.add(version)
    policy.active_version_id = version.id
    db.add(
        PolicyAuditLog(
            id=str(uuid.uuid4()),
            tenant_id=user.tenant_id,
            policy_id=policy.id,
            action_type="created",
            user_id=user.id,
            new_version=version.version_number,
        )
    )
    db.commit()
    return {
        "message": "Seeded modernize readiness policy",
        "count": 1,
        "policy_id": policy.id,
        "version_id": version.id,
    }


@router.post("", response_model=PolicyResponse, status_code=status.HTTP_201_CREATED)
async def create_policy(
    policy_data: PolicyCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Create a new policy"""
    if not has_permission(user, "can_manage_policies", db):
        raise HTTPException(status_code=403, detail="Permission denied")
    
    # Check if policy_id already exists for this tenant
    existing = db.query(Policy).filter(
        and_(
            Policy.policy_id == policy_data.policy_id,
            Policy.tenant_id == user.tenant_id
        )
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Policy with ID {policy_data.policy_id} already exists")
    
    # Create policy
    policy = Policy(
        id=str(uuid.uuid4()),
        tenant_id=user.tenant_id,
        policy_id=policy_data.policy_id,
        name=policy_data.name,
        description=policy_data.description,
        category=policy_data.category,
        applies_to=policy_data.applies_to,
        stacks=policy_data.stacks,
        tags=policy_data.tags,
        status="draft",
        created_by=user.id,
        updated_by=user.id
    )
    db.add(policy)
    db.flush()
    
    # Save policy content to storage (mimics S3 structure)
    storage_key = storage_service.save_policy_content(
        tenant_id=user.tenant_id or "default",
        policy_id=policy_data.policy_id,
        category=policy_data.category,
        content=policy_data.content,
        version="1.0.0-draft.1",
        content_yaml=policy_data.content_yaml
    )
    
    # Create initial version
    version = PolicyVersion(
        id=str(uuid.uuid4()),
        policy_id=policy.id,
        version_number="1.0.0-draft.1",
        content=policy_data.content,  # Cache in DB for quick access
        content_yaml=policy_data.content_yaml,  # Cache in DB for quick access
        storage_key=storage_key,  # Reference to file in storage
        is_draft=True,
        requires_approval=policy_data.requires_approval,
        created_by=user.id
    )
    db.add(version)
    
    # Create audit log
    audit_log = PolicyAuditLog(
        id=str(uuid.uuid4()),
        tenant_id=user.tenant_id,
        policy_id=policy.id,
        action_type="created",
        user_id=user.id,
        new_version=version.version_number
    )
    db.add(audit_log)
    
    db.commit()
    db.refresh(policy)
    
    return PolicyResponse(
        id=policy.id,
        policy_id=policy.policy_id,
        name=policy.name,
        description=policy.description,
        category=policy.category,
        status=policy.status,
        applies_to=policy.applies_to,
        stacks=policy.stacks,
        tags=policy.tags,
        active_version_id=None,
        active_version_number=None,
        created_by=policy.created_by,
        updated_by=policy.updated_by,
        created_at=policy.created_at,
        updated_at=policy.updated_at
    )


@router.get("/{policy_id}", response_model=PolicyResponse)
async def get_policy(
    policy_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Get a specific policy"""
    if not has_permission(user, "can_manage_policies", db):
        raise HTTPException(status_code=403, detail="Permission denied")
    
    policy = db.query(Policy).filter(
        and_(
            Policy.id == policy_id,
            Policy.tenant_id == user.tenant_id
        )
    ).first()
    
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    
    return PolicyResponse(
        id=policy.id,
        policy_id=policy.policy_id,
        name=policy.name,
        description=policy.description,
        category=policy.category,
        status=policy.status,
        applies_to=policy.applies_to,
        stacks=policy.stacks,
        tags=policy.tags,
        active_version_id=policy.active_version_id,
        active_version_number=policy.active_version.version_number if policy.active_version else None,
        created_by=policy.created_by,
        updated_by=policy.updated_by,
        created_at=policy.created_at,
        updated_at=policy.updated_at
    )


@router.put("/{policy_id}", response_model=PolicyResponse)
async def update_policy(
    policy_id: str,
    policy_data: PolicyUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Update a policy (creates a new draft version)"""
    if not has_permission(user, "can_manage_policies", db):
        raise HTTPException(status_code=403, detail="Permission denied")
    
    policy = db.query(Policy).filter(
        and_(
            Policy.id == policy_id,
            Policy.tenant_id == user.tenant_id
        )
    ).first()
    
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    
    # Update metadata
    if policy_data.name is not None:
        policy.name = policy_data.name
    if policy_data.description is not None:
        policy.description = policy_data.description
    if policy_data.category is not None:
        policy.category = policy_data.category
    if policy_data.applies_to is not None:
        policy.applies_to = policy_data.applies_to
    if policy_data.stacks is not None:
        policy.stacks = policy_data.stacks
    if policy_data.tags is not None:
        policy.tags = policy_data.tags
    policy.updated_by = user.id
    policy.updated_at = datetime.now()
    
    # Create new draft version if content changed
    latest_version = None
    new_version = None
    if policy_data.content is not None or policy_data.content_yaml is not None:
        # Get latest version to increment
        latest_version = db.query(PolicyVersion).filter(
            PolicyVersion.policy_id == policy.id
        ).order_by(PolicyVersion.created_at.desc()).first()
        
        if latest_version:
            # Increment draft version
            base_version = latest_version.version_number.split("-")[0] if "-" in latest_version.version_number else latest_version.version_number
            draft_count = 1
            if latest_version.is_draft and "-draft." in latest_version.version_number:
                try:
                    draft_count = int(latest_version.version_number.split("-draft.")[1]) + 1
                except Exception:
                    pass
            new_version_number = f"{base_version}-draft.{draft_count}"
        else:
            new_version_number = "1.0.0-draft.1"
        
        # Determine content to save
        if policy_data.content is not None:
            new_content = policy_data.content
        elif latest_version:
            new_content = latest_version.content or {}
        else:
            new_content = {}
        if policy_data.content_yaml is not None:
            new_content_yaml = policy_data.content_yaml
        elif latest_version:
            new_content_yaml = latest_version.content_yaml
        else:
            new_content_yaml = None
        
        # Save policy content to storage (mimics S3 structure)
        storage_key = storage_service.save_policy_content(
            tenant_id=user.tenant_id or "default",
            policy_id=policy.policy_id,
            category=policy.category,
            content=new_content,
            version=new_version_number,
            content_yaml=new_content_yaml
        )
        
        new_version = PolicyVersion(
            id=str(uuid.uuid4()),
            policy_id=policy.id,
            version_number=new_version_number,
            content=new_content,  # Cache in DB for quick access
            content_yaml=new_content_yaml,  # Cache in DB for quick access
            storage_key=storage_key,  # Reference to file in storage
            is_draft=True,
            requires_approval=policy_data.requires_approval if policy_data.requires_approval is not None else (latest_version.requires_approval if latest_version else False),
            created_by=user.id
        )
        db.add(new_version)
        db.flush()
    
    # Create audit log
    audit_log = PolicyAuditLog(
        id=str(uuid.uuid4()),
        tenant_id=user.tenant_id,
        policy_id=policy.id,
        action_type="updated",
        user_id=user.id,
        previous_version=latest_version.version_number if latest_version else None,
        new_version=new_version.version_number if new_version else None
    )
    db.add(audit_log)
    
    db.commit()
    db.refresh(policy)

    # Return draft version id so clients can publish immediately
    active_number = None
    if policy.active_version:
        active_number = policy.active_version.version_number
    elif policy.active_version_id:
        ver = db.query(PolicyVersion).filter(PolicyVersion.id == policy.active_version_id).first()
        if ver:
            active_number = ver.version_number

    response = PolicyResponse(
        id=policy.id,
        policy_id=policy.policy_id,
        name=policy.name,
        description=policy.description,
        category=policy.category,
        status=policy.status,
        applies_to=policy.applies_to,
        stacks=policy.stacks,
        tags=policy.tags,
        active_version_id=policy.active_version_id,
        active_version_number=active_number,
        created_by=policy.created_by,
        updated_by=policy.updated_by,
        created_at=policy.created_at,
        updated_at=policy.updated_at
    )
    # Attach draft id via response model extras is awkward; clients re-fetch versions.
    return response


@router.delete("/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_policy(
    policy_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Delete a policy"""
    if not has_permission(user, "can_manage_policies", db):
        raise HTTPException(status_code=403, detail="Permission denied")
    
    policy = db.query(Policy).filter(
        and_(
            Policy.id == policy_id,
            Policy.tenant_id == user.tenant_id
        )
    ).first()
    
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    
    # Delete all versions and their storage files
    for version in policy.versions:
        if version.storage_key:
            try:
                # Delete from storage
                storage_service.delete_policy_content(
                    tenant_id=user.tenant_id or "default",
                    policy_id=policy.policy_id,
                    category=policy.category,
                    version=version.version_number
                )
            except Exception as e:
                logger.warning(f"Error deleting policy file from storage: {e}")
    
    # Delete audit logs
    db.query(PolicyAuditLog).filter(PolicyAuditLog.policy_id == policy.id).delete()
    
    # Delete attachments
    db.query(PolicyAttachment).filter(PolicyAttachment.policy_id == policy.id).delete()
    
    # Delete the policy (cascade will delete versions)
    db.delete(policy)
    db.commit()
    
    return None


@router.post("/{policy_id}/publish", response_model=PolicyResponse)
async def publish_policy(
    policy_id: str,
    version_id: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Publish a policy version (activate it)"""
    if not has_permission(user, "can_manage_policies", db):
        raise HTTPException(status_code=403, detail="Permission denied")
    
    policy = db.query(Policy).filter(
        and_(
            Policy.id == policy_id,
            Policy.tenant_id == user.tenant_id
        )
    ).first()
    
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    
    # Get version to publish
    if version_id:
        version = db.query(PolicyVersion).filter(
            and_(
                PolicyVersion.id == version_id,
                PolicyVersion.policy_id == policy.id
            )
        ).first()
    else:
        # Get latest draft version
        version = db.query(PolicyVersion).filter(
            and_(
                PolicyVersion.policy_id == policy.id,
                PolicyVersion.is_draft == True
            )
        ).order_by(PolicyVersion.created_at.desc()).first()
    
    if not version:
        raise HTTPException(status_code=404, detail="No draft version found to publish")
    
    # Check if approval required
    if version.requires_approval and not version.approved_by:
        raise HTTPException(status_code=400, detail="This policy version requires approval before publishing")
    
    # Deactivate current active version if exists
    if policy.active_version_id:
        old_version = db.query(PolicyVersion).filter(PolicyVersion.id == policy.active_version_id).first()
        if old_version:
            old_version.is_draft = True
    
    # Activate new version
    version.is_draft = False
    version.approved_by = user.id
    version.approved_at = datetime.now()
    policy.active_version_id = version.id
    policy.status = "active"
    policy.updated_by = user.id
    policy.updated_at = datetime.now()
    
    # Create audit log
    audit_log = PolicyAuditLog(
        id=str(uuid.uuid4()),
        tenant_id=user.tenant_id,
        policy_id=policy.id,
        action_type="published",
        user_id=user.id,
        previous_version=old_version.version_number if policy.active_version_id and old_version else None,
        new_version=version.version_number
    )
    db.add(audit_log)
    
    db.commit()
    db.refresh(policy)
    
    return PolicyResponse(
        id=policy.id,
        policy_id=policy.policy_id,
        name=policy.name,
        description=policy.description,
        category=policy.category,
        status=policy.status,
        applies_to=policy.applies_to,
        stacks=policy.stacks,
        tags=policy.tags,
        active_version_id=policy.active_version_id,
        active_version_number=version.version_number,
        created_by=policy.created_by,
        updated_by=policy.updated_by,
        created_at=policy.created_at,
        updated_at=policy.updated_at
    )


@router.post("/{policy_id}/deprecate", response_model=PolicyResponse)
async def deprecate_policy(
    policy_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Deprecate a policy"""
    if not has_permission(user, "can_manage_policies", db):
        raise HTTPException(status_code=403, detail="Permission denied")
    
    policy = db.query(Policy).filter(
        and_(
            Policy.id == policy_id,
            Policy.tenant_id == user.tenant_id
        )
    ).first()
    
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    
    policy.status = "deprecated"
    policy.updated_by = user.id
    policy.updated_at = datetime.now()
    
    # Create audit log
    audit_log = PolicyAuditLog(
        id=str(uuid.uuid4()),
        tenant_id=user.tenant_id,
        policy_id=policy.id,
        action_type="deprecated",
        user_id=user.id
    )
    db.add(audit_log)
    
    db.commit()
    db.refresh(policy)
    
    return PolicyResponse(
        id=policy.id,
        policy_id=policy.policy_id,
        name=policy.name,
        description=policy.description,
        category=policy.category,
        status=policy.status,
        applies_to=policy.applies_to,
        stacks=policy.stacks,
        tags=policy.tags,
        active_version_id=policy.active_version_id,
        active_version_number=policy.active_version.version_number if policy.active_version else None,
        created_by=policy.created_by,
        updated_by=policy.updated_by,
        created_at=policy.created_at,
        updated_at=policy.updated_at
    )


@router.get("/{policy_id}/versions", response_model=List[PolicyVersionResponse])
async def list_policy_versions(
    policy_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """List all versions of a policy"""
    if not has_permission(user, "can_manage_policies", db):
        raise HTTPException(status_code=403, detail="Permission denied")
    
    policy = db.query(Policy).filter(
        and_(
            Policy.id == policy_id,
            Policy.tenant_id == user.tenant_id
        )
    ).first()
    
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    
    versions = db.query(PolicyVersion).filter(
        PolicyVersion.policy_id == policy.id
    ).order_by(PolicyVersion.created_at.desc()).all()
    
    return [PolicyVersionResponse(**{
        "id": v.id,
        "policy_id": v.policy_id,
        "version_number": v.version_number,
        "content": v.content,
        "content_yaml": v.content_yaml,
        "is_draft": v.is_draft,
        "requires_approval": v.requires_approval,
        "approved_by": v.approved_by,
        "approved_at": v.approved_at,
        "created_by": v.created_by,
        "created_at": v.created_at
    }) for v in versions]


# ============================================================================
# Building Blocks Endpoints
# ============================================================================

@router.get("/building-blocks", response_model=List[BuildingBlockResponse])
async def list_building_blocks(
    type: Optional[str] = Query(None, description="Filter by type"),
    enforcement: Optional[str] = Query(None, description="Filter by enforcement"),
    stack: Optional[str] = Query(None, description="Filter by stack"),
    search: Optional[str] = Query(None, description="Search in name and description"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """List all building blocks"""
    if not has_permission(user, "can_manage_building_blocks", db):
        raise HTTPException(status_code=403, detail="Permission denied")
    
    query = db.query(BuildingBlock).filter(BuildingBlock.tenant_id == user.tenant_id)
    
    if type:
        query = query.filter(BuildingBlock.type == type)
    if enforcement:
        query = query.filter(BuildingBlock.enforcement == enforcement)
    if stack:
        query = query.filter(BuildingBlock.applicable_stacks.contains([stack]))
    if search:
        query = query.filter(
            or_(
                BuildingBlock.name.ilike(f"%{search}%"),
                BuildingBlock.description.ilike(f"%{search}%")
            )
        )
    
    blocks = query.order_by(BuildingBlock.name).all()
    return [BuildingBlockResponse(**{
        "id": b.id,
        "name": b.name,
        "type": b.type,
        "description": b.description,
        "url": b.url,
        "applicable_stacks": b.applicable_stacks,
        "enforcement": b.enforcement,
        "version": b.version,
        "owner": b.owner,
        "usage_guidance": b.usage_guidance,
        "when_to_use": b.when_to_use,
        "tags": b.tags,
        "created_by": b.created_by,
        "created_at": b.created_at,
        "updated_at": b.updated_at
    }) for b in blocks]


@router.post("/building-blocks", response_model=BuildingBlockResponse, status_code=status.HTTP_201_CREATED)
async def create_building_block(
    block_data: BuildingBlockCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Create a new building block"""
    if not has_permission(user, "can_manage_building_blocks", db):
        raise HTTPException(status_code=403, detail="Permission denied")
    
    # Check if name already exists for this tenant
    existing = db.query(BuildingBlock).filter(
        and_(
            BuildingBlock.name == block_data.name,
            BuildingBlock.tenant_id == user.tenant_id
        )
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Building block with name {block_data.name} already exists")
    
    block = BuildingBlock(
        id=str(uuid.uuid4()),
        tenant_id=user.tenant_id,
        name=block_data.name,
        type=block_data.type,
        description=block_data.description,
        url=block_data.url,
        applicable_stacks=block_data.applicable_stacks,
        enforcement=block_data.enforcement,
        version=block_data.version,
        owner=block_data.owner,
        usage_guidance=block_data.usage_guidance,
        when_to_use=block_data.when_to_use,
        tags=block_data.tags,
        created_by=user.id
    )
    db.add(block)
    db.commit()
    db.refresh(block)
    
    return BuildingBlockResponse(**{
        "id": block.id,
        "name": block.name,
        "type": block.type,
        "description": block.description,
        "url": block.url,
        "applicable_stacks": block.applicable_stacks,
        "enforcement": block.enforcement,
        "version": block.version,
        "owner": block.owner,
        "usage_guidance": block.usage_guidance,
        "when_to_use": block.when_to_use,
        "tags": block.tags,
        "created_by": block.created_by,
        "created_at": block.created_at,
        "updated_at": block.updated_at
    })


# ============================================================================
# v2 Pydantic Models
# ============================================================================

class PolicyBundleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    version: str = "v1.0.0"
    policy_ids: List[str] = Field(..., description="List of policy IDs to include in the bundle")


class PolicyBundleResponse(BaseModel):
    id: str
    tenant_id: Optional[str]
    name: str
    description: Optional[str]
    version: str
    is_active: bool
    policy_ids: List[str]
    created_by: Optional[str]
    created_at: datetime
    activated_at: Optional[datetime]

    class Config:
        from_attributes = True


class ResolvedPolicyResponse(BaseModel):
    policy_id: str
    name: str
    category: str
    level: str
    content: Any
    version: Optional[str] = None
    updated_at: Optional[datetime] = None


class EffectivePolicySetResponse(BaseModel):
    policies_by_category: Dict[str, ResolvedPolicyResponse]
    tenant_id: Optional[str] = None
    project_id: Optional[str] = None
    resolved_at: Optional[datetime] = None


# ============================================================================
# v2 Policy Endpoints
# ============================================================================

def _get_user_role_names(user: User, db: Session) -> List[str]:
    """Get role names for a user."""
    user_roles = db.query(UserRole).join(Role).filter(UserRole.user_id == user.id).all()
    return [db.query(Role).filter(Role.id == ur.role_id).first().name for ur in user_roles if db.query(Role).filter(Role.id == ur.role_id).first()]


@router.get("/effective/{project_id}", response_model=EffectivePolicySetResponse)
async def get_effective_policies(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return the resolved Effective Policy Set for a project.

    Requirements: 1.6, 3.5
    """
    engine = PolicyMergeEngine(db)
    effective_set = engine.resolve_effective_policies(
        tenant_id=user.tenant_id or "", project_id=project_id
    )

    # Convert to response model
    policies_resp: Dict[str, ResolvedPolicyResponse] = {}
    for cat, rp in effective_set.policies_by_category.items():
        policies_resp[cat] = ResolvedPolicyResponse(
            policy_id=rp.policy_id,
            name=rp.name,
            category=rp.category,
            level=rp.level,
            content=rp.content,
            version=rp.version,
            updated_at=rp.updated_at,
        )

    return EffectivePolicySetResponse(
        policies_by_category=policies_resp,
        tenant_id=effective_set.tenant_id,
        project_id=effective_set.project_id,
        resolved_at=effective_set.resolved_at,
    )


@router.post("/bundles", response_model=PolicyBundleResponse, status_code=status.HTTP_201_CREATED)
async def create_policy_bundle(
    bundle_data: PolicyBundleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a policy bundle.

    Admin role required for tenant-level bundles.
    Product_Manager or Architect role can also create bundles.
    Requirements: 2.8, 2.9, 2.10
    """
    role_names = _get_user_role_names(user, db)
    allowed_roles = {"admin", "product_manager", "architect"}
    if not (allowed_roles & set(role_names)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: requires Admin, Product_Manager, or Architect role",
        )

    # Check for duplicate name+version+tenant
    existing = db.query(PolicyBundle).filter(
        and_(
            PolicyBundle.name == bundle_data.name,
            PolicyBundle.version == bundle_data.version,
            PolicyBundle.tenant_id == user.tenant_id,
        )
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Bundle '{bundle_data.name}' version '{bundle_data.version}' already exists",
        )

    bundle = PolicyBundle(
        id=str(uuid.uuid4()),
        tenant_id=user.tenant_id,
        name=bundle_data.name,
        description=bundle_data.description,
        version=bundle_data.version,
        is_active=False,
        policy_ids=bundle_data.policy_ids,
        created_by=user.id,
    )
    db.add(bundle)

    # Audit log
    log_policy_audit(
        db=db,
        tenant_id=user.tenant_id or "",
        user_id=user.id,
        action_type=POLICY_CREATED,
        policy_id=bundle.id,
        change_details={"entity": "policy_bundle", "name": bundle_data.name, "version": bundle_data.version},
    )

    return PolicyBundleResponse(
        id=bundle.id,
        tenant_id=bundle.tenant_id,
        name=bundle.name,
        description=bundle.description,
        version=bundle.version,
        is_active=bundle.is_active,
        policy_ids=bundle.policy_ids,
        created_by=bundle.created_by,
        created_at=bundle.created_at,
        activated_at=bundle.activated_at,
    )


@router.put("/bundles/{bundle_id}/activate", response_model=PolicyBundleResponse)
async def activate_policy_bundle(
    bundle_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Activate a policy bundle for the tenant.

    Admin role required.
    Requirements: 2.9, 2.10
    """
    role_names = _get_user_role_names(user, db)
    if "admin" not in role_names:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: Admin role required to activate bundles",
        )

    bundle = db.query(PolicyBundle).filter(PolicyBundle.id == bundle_id).first()
    if not bundle:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy bundle not found")

    # Tenant isolation check
    verify_tenant_access(bundle, user.tenant_id or "")

    bundle.is_active = True
    bundle.activated_at = datetime.utcnow()
    db.commit()
    db.refresh(bundle)

    # Audit log
    log_policy_audit(
        db=db,
        tenant_id=user.tenant_id or "",
        user_id=user.id,
        action_type="bundle_activated",
        policy_id=bundle.id,
        change_details={"entity": "policy_bundle", "name": bundle.name, "activated": True},
    )

    return PolicyBundleResponse(
        id=bundle.id,
        tenant_id=bundle.tenant_id,
        name=bundle.name,
        description=bundle.description,
        version=bundle.version,
        is_active=bundle.is_active,
        policy_ids=bundle.policy_ids,
        created_by=bundle.created_by,
        created_at=bundle.created_at,
        activated_at=bundle.activated_at,
    )


@router.get("/categories", response_model=List[Dict[str, str]])
async def list_categories(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """List all policy categories"""
    categories = [
        {"id": "ideation", "name": "Ideation", "display_name": "Ideation"},
        {"id": "requirements", "name": "Requirements", "display_name": "Requirements"},
        {"id": "stories", "name": "Stories", "display_name": "Stories"},
        {"id": "architecture", "name": "Architecture", "display_name": "Architecture"},
        {"id": "coding", "name": "Coding", "display_name": "Coding Standards"},
        {"id": "testing", "name": "Testing", "display_name": "Testing"},
        {"id": "security", "name": "Security", "display_name": "Security"},
        {"id": "infra", "name": "Infrastructure", "display_name": "Infrastructure"},
        {"id": "building_blocks", "name": "Building Blocks", "display_name": "Building Blocks"},
    ]
    return categories
