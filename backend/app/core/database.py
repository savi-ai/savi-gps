"""Database setup and models"""
from sqlalchemy import create_engine, Column, String, Integer, DateTime, Text, JSON, ForeignKey, Boolean, text, UniqueConstraint, Index
from sqlalchemy import inspect
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
from app.core.config import settings
from app.core.logger import logger
import json

Base = declarative_base()


class WorkflowRun(Base):
    """Workflow run persistence"""
    __tablename__ = "workflow_runs"
    
    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=True, index=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=True, index=True)
    status = Column(String)
    current_stage = Column(String)
    execution_mode = Column(String, nullable=False, default="copilot")  # autopilot, copilot
    policy_bundle = Column(JSON, nullable=True)  # Serialized Effective Policy Set
    approval_required = Column(Boolean, default=True)
    deployment_url = Column(String, nullable=True)
    state_snapshot = Column(JSON)
    initiated_by = Column(String, ForeignKey("users.id"), nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # Relationships
    stage_executions = relationship("StageExecution", back_populates="workflow_run", cascade="all, delete-orphan")


class StageExecution(Base):
    """Tracks individual stage executions within a workflow run"""
    __tablename__ = "stage_executions"

    id = Column(String, primary_key=True)
    workflow_run_id = Column(String, ForeignKey("workflow_runs.id"), nullable=False, index=True)
    stage_name = Column(String, nullable=False)
    status = Column(String, nullable=False)  # pending, in_progress, completed, failed, awaiting_approval
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    output_summary = Column(JSON, nullable=True)
    validation_result = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    # Relationships
    workflow_run = relationship("WorkflowRun", back_populates="stage_executions")


class BusinessApplication(Base):
    """Business application persistence"""
    __tablename__ = "business_applications"
    
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)  # e.g., "Web App", "API", "Mobile App"
    status = Column(String, nullable=False, default="draft")  # draft, in_progress, completed
    workflow_run_id = Column(String, nullable=True)  # Link to workflow run
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class Tenant(Base):
    """Tenant model for multi-tenancy"""
    __tablename__ = "tenants"
    
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class Project(Base):
    """Project persistence with conversation history and progress"""
    __tablename__ = "projects"
    
    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=True, index=True)  # Made nullable for migration compatibility
    name = Column(String, nullable=False)
    
    # Unique constraint on name+tenant_id (added via migration, not in model for compatibility)
    description = Column(Text, nullable=True)
    business_value = Column(Text, nullable=True)
    domain = Column(String, nullable=True)  # e.g., "E-commerce", "Healthcare", "Finance"
    priority = Column(String, nullable=True)  # "low", "medium", "high", "critical"
    target_audience = Column(String, nullable=True)
    github_repo_url = Column(String, nullable=True)  # GitHub repository URL for code push
    conversation_history = Column(JSON, nullable=True)  # List of {role, content}
    vision = Column(Text, nullable=True)
    features = Column(JSON, nullable=True)  # Generated features
    architecture = Column(JSON, nullable=True)
    stories = Column(JSON, nullable=True)
    code_implementation = Column(JSON, nullable=True)
    tests = Column(JSON, nullable=True)
    default_execution_mode = Column(String, nullable=False, default="copilot")  # autopilot, copilot — project-level default
    current_step = Column(String, default="idea")  # idea, features, architecture, stories, developer, testing
    step_status = Column(String, nullable=True)  # ReadyForNext, Completed, InProgress, etc.
    feature_generation_status = Column(String, nullable=True)  # pending, started, completed, failed
    pillar = Column(String, nullable=False, default="build")  # build | modernize
    source_plan_id = Column(String, ForeignKey("modernization_plans.id"), nullable=True, index=True)
    # Target Application for this delivery workstream (ADR 0006). Name kept for DB compat;
    # API also exposes target_application_id as an alias.
    source_application_id = Column(String, ForeignKey("applications.id"), nullable=True, index=True)
    mode = Column(String, nullable=True)  # greenfield | enhance | extend (ADR 0006)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class Task(Base):
    """Background task tracking for async agent execution"""
    __tablename__ = "tasks"
    
    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    task_type = Column(String, nullable=False, index=True)  # generate_features, generate_stories, generate_architecture, generate_code, generate_tests
    status = Column(String, nullable=False, default="pending", index=True)  # pending, running, completed, failed, cancelled
    progress = Column(Integer, default=0)  # 0-100
    input_data = Column(JSON, nullable=True)  # Input parameters for the task
    result = Column(JSON, nullable=True)  # Task result data
    error = Column(Text, nullable=True)  # Error message if failed
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now, index=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    project = relationship("Project", backref="tasks")


class User(Base):
    """User model for authentication and authorization"""
    __tablename__ = "users"
    
    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=True, index=True)  # Made nullable for migration compatibility
    username = Column(String, nullable=False, index=True)
    email = Column(String, nullable=False, index=True)
    
    # Unique constraint on username+tenant_id and email+tenant_id (only if tenant_id exists)
    # Note: These constraints will be added via migration, not in model definition for compatibility
    password_hash = Column(String, nullable=False)  # Password (plain text for now, will hash later)
    full_name = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    user_roles = relationship("UserRole", primaryjoin="User.id == UserRole.user_id", back_populates="user", cascade="all, delete-orphan")


class Role(Base):
    """Role model for RBAC"""
    __tablename__ = "roles"
    
    id = Column(String, primary_key=True)
    name = Column(String, unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    
    # Relationships
    user_roles = relationship("UserRole", back_populates="role", cascade="all, delete-orphan")


class UserRole(Base):
    """User-Role association table"""
    __tablename__ = "user_roles"
    
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    role_id = Column(String, ForeignKey("roles.id"), nullable=False, index=True)
    assigned_by = Column(String, ForeignKey("users.id"), nullable=True)
    assigned_at = Column(DateTime, default=datetime.now)
    
    # Relationships
    user = relationship("User", foreign_keys=[user_id], back_populates="user_roles")
    role = relationship("Role", back_populates="user_roles")


class WorkflowConfig(Base):
    """Global workflow configuration"""
    __tablename__ = "workflow_config"
    
    id = Column(String, primary_key=True)
    mode = Column(String, nullable=False)  # single_path or role_based
    settings = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class ProjectConfig(Base):
    """Project-specific workflow configuration"""
    __tablename__ = "project_config"
    
    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, unique=True, index=True)
    workflow_mode = Column(String, nullable=False)  # single_path or role_based
    custom_settings = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class Approval(Base):
    """Workflow approval tracking"""
    __tablename__ = "approvals"
    
    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=True, index=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    workflow_run_id = Column(String, ForeignKey("workflow_runs.id"), nullable=True, index=True)
    step_name = Column(String, nullable=False)
    from_user_id = Column(String, ForeignKey("users.id"), nullable=False)
    to_roles = Column(JSON, nullable=False)  # List of role names that can approve
    status = Column(String, nullable=False)  # pending, approved, rejected
    decision = Column(String, nullable=True)  # approved, rejected
    approved_by = Column(String, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    comments = Column(Text, nullable=True)
    feedback = Column(Text, nullable=True)  # Rejection feedback for stage re-run
    edited_output = Column(JSON, nullable=True)  # User-edited stage output before approval
    created_at = Column(DateTime, default=datetime.now)


class Handoff(Base):
    """Workflow handoff tracking"""
    __tablename__ = "handoffs"
    
    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    from_step = Column(String, nullable=False)
    to_step = Column(String, nullable=False)
    from_user_id = Column(String, ForeignKey("users.id"), nullable=False)
    to_roles = Column(JSON, nullable=False)  # List of role names
    created_at = Column(DateTime, default=datetime.now)


class StandardsSource(Base):
    """External standards source configuration"""
    __tablename__ = "standards_sources"
    
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    source_type = Column(String, nullable=False)  # confluence, github, local_file
    connection_config = Column(JSON, nullable=False)
    sync_schedule = Column(String, nullable=True)
    enabled = Column(Boolean, default=True)
    last_sync_at = Column(DateTime, nullable=True)
    last_sync_status = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class SOPVersion(Base):
    """SOP version history"""
    __tablename__ = "sop_versions"
    
    id = Column(String, primary_key=True)
    sop_id = Column(String, nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    content = Column(JSON, nullable=False)
    source_id = Column(String, ForeignKey("standards_sources.id"), nullable=True)
    change_description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)


class AuditTrail(Base):
    """Audit trail for compliance"""
    __tablename__ = "audit_trail"
    
    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    action_type = Column(String, nullable=False, index=True)
    resource_type = Column(String, nullable=False)
    resource_id = Column(String, nullable=False, index=True)
    details = Column(JSON, nullable=True)
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.now, index=True)


class Notification(Base):
    """User notifications"""
    __tablename__ = "notifications"
    
    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    notification_type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    context = Column(JSON, nullable=True)
    is_read = Column(Boolean, default=False)
    read_at = Column(DateTime, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)


class ProjectTemplate(Base):
    """Project templates"""
    __tablename__ = "project_templates"
    
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String, nullable=True)
    template_data = Column(JSON, nullable=False)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    is_system_template = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class StateSnapshot(Base):
    """Workflow state snapshots"""
    __tablename__ = "state_snapshots"
    
    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    workflow_step = Column(String, nullable=False)
    state_data = Column(JSON, nullable=False)
    is_milestone = Column(Boolean, default=False)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now)


class ProjectLineage(Base):
    """Project parent-child relationships"""
    __tablename__ = "project_lineage"
    
    id = Column(String, primary_key=True)
    parent_project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    child_project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    relationship_type = Column(String, nullable=False)  # clone, branch
    branch_point = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.now)


class TenantConfig(Base):
    """Per-tenant feature capabilities and onboarding preferences"""
    __tablename__ = "tenant_configs"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, unique=True, index=True)
    capabilities = Column(JSON, nullable=False)
    onboarding_path = Column(String, nullable=True)  # wiki_only, modernization, full
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    tenant = relationship("Tenant", backref="config")


class GitHubCredential(Base):
    """Tenant-scoped GitHub PAT for repository discovery and cloning"""
    __tablename__ = "github_credentials"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    label = Column(String, nullable=False, default="GitHub PAT")
    token_encrypted = Column(Text, nullable=False)
    github_login = Column(String, nullable=True)
    github_name = Column(String, nullable=True)
    scopes = Column(JSON, nullable=True)
    is_active = Column(Boolean, default=True)
    last_validated_at = Column(DateTime, nullable=True)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    tenant = relationship("Tenant", backref="github_credentials")


class Repository(Base):
    """Connected source repository for Intelligence (wiki, chat, search)"""
    __tablename__ = "repositories"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    provider = Column(String, nullable=False, default="github")
    url = Column(String, nullable=False)
    github_owner = Column(String, nullable=True, index=True)
    github_repo = Column(String, nullable=True, index=True)
    github_org = Column(String, nullable=True, index=True)  # org namespace; null for personal repos
    github_full_name = Column(String, nullable=True, index=True)  # owner/repo
    github_credential_id = Column(String, ForeignKey("github_credentials.id"), nullable=True, index=True)
    default_branch = Column(String, nullable=False, default="main")
    include_globs = Column(JSON, nullable=True)
    exclude_globs = Column(JSON, nullable=True)
    status = Column(String, nullable=False, default="pending")  # pending, indexing, ready, error
    last_indexed_at = Column(DateTime, nullable=True)
    last_index_error = Column(Text, nullable=True)
    config_yaml = Column(JSON, nullable=True)
    spec_layer_enabled = Column(Boolean, default=False)
    agent_enabled = Column(Boolean, default=False)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    tenant = relationship("Tenant", backref="repositories")
    github_credential = relationship("GitHubCredential", backref="repositories")


class Application(Base):
    """Estate inventory — a real-world product grouping multiple repositories."""
    __tablename__ = "applications"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    domain = Column(String, nullable=True)
    # ADR 0006: imported | generated | hybrid
    origin = Column(String, nullable=False, default="imported")
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    tenant = relationship("Tenant", backref="applications")
    repository_memberships = relationship(
        "ApplicationRepository",
        back_populates="application",
        cascade="all, delete-orphan",
    )


class ApplicationRepository(Base):
    """Many-to-many: one repository belongs to at most one application."""
    __tablename__ = "application_repositories"

    id = Column(String, primary_key=True)
    application_id = Column(String, ForeignKey("applications.id"), nullable=False, index=True)
    repository_id = Column(String, ForeignKey("repositories.id"), nullable=False, unique=True, index=True)
    role = Column(String, nullable=True)  # backend | frontend | api | worker | infra | library | other
    created_at = Column(DateTime, default=datetime.now)

    application = relationship("Application", back_populates="repository_memberships")
    repository = relationship("Repository", backref="application_membership")


class Team(Base):
    """Work + ACL + Savi roster boundary (ADR 0007)."""
    __tablename__ = "teams"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, nullable=False, index=True)
    description = Column(Text, nullable=True)
    # Reserved for Portfolio / Business Units (nullable until F1)
    business_unit_id = Column(String, nullable=True, index=True)
    is_default = Column(Boolean, default=False)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    tenant = relationship("Tenant", backref="teams")
    members = relationship(
        "TeamMember",
        back_populates="team",
        cascade="all, delete-orphan",
    )
    application_links = relationship(
        "TeamApplication",
        back_populates="team",
        cascade="all, delete-orphan",
    )


class TeamMember(Base):
    __tablename__ = "team_members"

    id = Column(String, primary_key=True)
    team_id = Column(String, ForeignKey("teams.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    # lead | member
    role = Column(String, nullable=False, default="member")
    created_at = Column(DateTime, default=datetime.now)

    team = relationship("Team", back_populates="members")
    user = relationship("User", backref="team_memberships")


class TeamApplication(Base):
    """Team owns or shares an Application for ACL / Savi scope."""
    __tablename__ = "team_applications"

    id = Column(String, primary_key=True)
    team_id = Column(String, ForeignKey("teams.id"), nullable=False, index=True)
    application_id = Column(String, ForeignKey("applications.id"), nullable=False, index=True)
    # own | share
    access = Column(String, nullable=False, default="own")
    created_at = Column(DateTime, default=datetime.now)

    team = relationship("Team", back_populates="application_links")
    application = relationship("Application", backref="team_links")


class SaviInstance(Base):
    """Rostered Savi Teammate on a Team (ADR 0007 / Teammate plan T2 shell)."""
    __tablename__ = "savi_instances"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    team_id = Column(String, ForeignKey("teams.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, nullable=False, index=True)
    # pending | active | disabled
    status = Column(String, nullable=False, default="pending")
    # Optional link to GPS user used for audit attribution
    machine_user_id = Column(String, ForeignKey("users.id"), nullable=True)
    # T7: company-managed identity attached by admin (IdP service account / SP)
    # entra | okta | google | github | custom | None
    external_identity_provider = Column(String, nullable=True)
    # UPN, email, object id, or SP client id — company source of truth
    external_identity_subject = Column(String, nullable=True, index=True)
    external_identity_display = Column(String, nullable=True)
    external_identity_metadata = Column(JSON, nullable=True)
    external_identity_linked_at = Column(DateTime, nullable=True)
    external_identity_linked_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    tenant = relationship("Tenant", backref="savi_instances")
    team = relationship("Team", backref="savi_instances")


class SaviCodingAgentSeat(Base):
    """Coding-agent seat binding for a Savi (T7 / ADR 0009). One active per Savi in V1."""
    __tablename__ = "savi_coding_agent_seats"
    __table_args__ = (
        UniqueConstraint("savi_instance_id", name="uq_savi_coding_agent_seat"),
    )

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    team_id = Column(String, ForeignKey("teams.id"), nullable=False, index=True)
    savi_instance_id = Column(
        String, ForeignKey("savi_instances.id"), nullable=False, index=True
    )
    # github_copilot | cursor | kiro | claude_code | custom
    agent_type = Column(String, nullable=False)
    # active | disabled | pending_license
    status = Column(String, nullable=False, default="pending_license")
    # Vendor seat id / licensed email / installation id (company-managed)
    external_seat_ref = Column(String, nullable=True)
    # heuristic | llm | cli | claude_cli | copilot_cli | kiro_cli | api | remote_runner
    execution_mode = Column(String, nullable=False, default="cli")
    config_json = Column(JSON, nullable=True)
    secret_encrypted = Column(Text, nullable=True)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    tenant = relationship("Tenant", backref="savi_coding_agent_seats")
    team = relationship("Team", backref="savi_coding_agent_seats")
    savi_instance = relationship("SaviInstance", backref="coding_agent_seat")


class SaviWorkItem(Base):
    """Per-Savi work queue item (Teammate Phase T3). Never tenant-global."""
    __tablename__ = "savi_work_items"
    __table_args__ = (
        Index("ix_savi_work_savi_state", "savi_instance_id", "state"),
        Index("ix_savi_work_team_state", "team_id", "state"),
    )

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    team_id = Column(String, ForeignKey("teams.id"), nullable=False, index=True)
    savi_instance_id = Column(
        String, ForeignKey("savi_instances.id"), nullable=False, index=True
    )
    application_id = Column(
        String, ForeignKey("applications.id"), nullable=True, index=True
    )

    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    # manual | jira | slack
    source = Column(String, nullable=False, default="manual")
    external_ref = Column(String, nullable=True)

    # inbox | needs_info | queued | in_progress | in_review | done | blocked | cancelled
    state = Column(String, nullable=False, default="inbox", index=True)
    # Lower number = higher priority. Null while awaiting_priority.
    priority = Column(Integer, nullable=True)
    awaiting_priority = Column(Boolean, default=False)

    ready_questions = Column(JSON, nullable=True)  # [{id, prompt}]
    clarification_answers = Column(JSON, nullable=True)  # {question_id: answer}
    # Portal intake until T5 connectors: [{type, label?, value}] + extra_repository_ids stored here
    context_refs = Column(JSON, nullable=True)
    context_pack = Column(JSON, nullable=True)  # Assembled brief (T4)

    # T5 connector linkage
    pr_url = Column(String, nullable=True)
    pr_number = Column(Integer, nullable=True)
    pr_repository_id = Column(String, ForeignKey("repositories.id"), nullable=True)
    connector_meta = Column(JSON, nullable=True)  # jira status, slack thread, check runs, …

    # T6 orchestrator
    # ready | ground | plan | code | test | pr | awaiting_approval | wait_feedback | done | failed
    orchestrator_phase = Column(String, nullable=True, index=True)
    orchestrator_timeline = Column(JSON, nullable=True)  # [{phase, at, detail, tokens, cost}]
    orchestrator_tokens = Column(Integer, nullable=True, default=0)
    orchestrator_error = Column(Text, nullable=True)
    # ADR 0010 kill switch + approval binding
    cancel_requested = Column(Boolean, default=False)
    approval_base_sha = Column(String, nullable=True)
    approval_diff_hash = Column(String, nullable=True)
    approval_bound_at = Column(DateTime, nullable=True)

    assigned_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    tenant = relationship("Tenant", backref="savi_work_items")
    team = relationship("Team", backref="savi_work_items")
    savi_instance = relationship("SaviInstance", backref="work_items")
    application = relationship("Application", backref="savi_work_items")


class SaviConnectorBinding(Base):
    """Per-Savi connector credentials + external IDs (Teammate Phase T5)."""
    __tablename__ = "savi_connector_bindings"
    __table_args__ = (
        UniqueConstraint(
            "savi_instance_id",
            "connector_type",
            name="uq_savi_connector_type",
        ),
    )

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    team_id = Column(String, ForeignKey("teams.id"), nullable=False, index=True)
    savi_instance_id = Column(
        String, ForeignKey("savi_instances.id"), nullable=False, index=True
    )
    # github | jira | slack | confluence
    connector_type = Column(String, nullable=False, index=True)
    # active | disabled
    status = Column(String, nullable=False, default="active")
    # Non-secret config: github_credential_id, project_key, channel_id, base_url, webhook_secret, …
    config_json = Column(JSON, nullable=True)
    secret_encrypted = Column(Text, nullable=True)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    tenant = relationship("Tenant", backref="savi_connector_bindings")
    team = relationship("Team", backref="savi_connector_bindings")
    savi_instance = relationship("SaviInstance", backref="connector_bindings")


class RepositoryProjectLink(Base):
    """Links a repository to a Build / Evolve project (context or modernization)."""
    __tablename__ = "repository_project_links"

    id = Column(String, primary_key=True)
    repository_id = Column(String, ForeignKey("repositories.id"), nullable=False, index=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    link_type = Column(String, nullable=False, default="modernization")  # context | modernization
    created_at = Column(DateTime, default=datetime.now)

    repository = relationship("Repository", backref="project_links")
    project = relationship("Project", backref="repository_links")


class ModernizationPlaybook(Base):
    """Reusable modernization templates (Java 8→17, Spring upgrades, etc.)"""
    __tablename__ = "modernization_playbooks"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    checklist_json = Column(JSON, nullable=True)
    seed_content_md = Column(Text, nullable=True)
    is_system = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    tenant = relationship("Tenant", backref="modernization_playbooks")


class ModernizationPlan(Base):
    """Per-repository modernization assessment and execution plan"""
    __tablename__ = "modernization_plans"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    repository_id = Column(String, ForeignKey("repositories.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    state = Column(String, nullable=False, default="assessing")
    # assessing | planned | executing | verifying | complete | cancelled
    playbook_id = Column(String, ForeignKey("modernization_playbooks.id"), nullable=True, index=True)
    assessment_json = Column(JSON, nullable=True)
    plan_md = Column(Text, nullable=True)
    spawned_project_id = Column(String, ForeignKey("projects.id"), nullable=True, index=True)
    source_application_id = Column(String, ForeignKey("applications.id"), nullable=True, index=True)
    plan_bundle_id = Column(String, nullable=True, index=True)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    tenant = relationship("Tenant", backref="modernization_plans")
    repository = relationship("Repository", backref="modernization_plans")
    playbook = relationship("ModernizationPlaybook", backref="plans")
    spawned_project = relationship(
        "Project",
        foreign_keys=[spawned_project_id],
        backref="modernization_plan_spawned",
    )


class PortfolioSnapshot(Base):
    """Point-in-time portfolio metrics for CTO/CIO trends (Phase 5)"""
    __tablename__ = "portfolio_snapshots"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    captured_at = Column(DateTime, nullable=False, default=datetime.now)
    metrics_json = Column(JSON, nullable=False)

    tenant = relationship("Tenant", backref="portfolio_snapshots")


class IndexRun(Base):
    """Tracks repository indexing jobs"""
    __tablename__ = "index_runs"

    id = Column(String, primary_key=True)
    repository_id = Column(String, ForeignKey("repositories.id"), nullable=False, index=True)
    status = Column(String, nullable=False, default="pending")
    progress = Column(Integer, nullable=False, default=0)
    loc = Column(Integer, nullable=True)
    token_spend = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    repository = relationship("Repository", backref="index_runs")


class CodeChunk(Base):
    """Indexed code chunks for retrieval (embeddings stored as JSON for SQLite MVP)"""
    __tablename__ = "code_chunks"

    id = Column(String, primary_key=True)
    repository_id = Column(String, ForeignKey("repositories.id"), nullable=False, index=True)
    file_path = Column(String, nullable=False, index=True)
    start_line = Column(Integer, nullable=False, default=1)
    end_line = Column(Integer, nullable=False, default=1)
    content = Column(Text, nullable=False)
    content_hash = Column(String, nullable=False, index=True)
    language = Column(String, nullable=True)
    embedding = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    repository = relationship("Repository", backref="code_chunks")


class WikiPage(Base):
    """Generated wiki pages per repository"""
    __tablename__ = "wiki_pages"

    id = Column(String, primary_key=True)
    repository_id = Column(String, ForeignKey("repositories.id"), nullable=False, index=True)
    index_run_id = Column(String, ForeignKey("index_runs.id"), nullable=True, index=True)
    slug = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    template_type = Column(String, nullable=False, default="custom")
    content_md = Column(Text, nullable=False)
    content_hash = Column(String, nullable=True, index=True)
    mermaid = Column(Text, nullable=True)
    state = Column(String, nullable=False, default="draft")  # draft | live
    version = Column(Integer, nullable=False, default=1)
    freshness_at = Column(DateTime, nullable=True)
    drift_status = Column(String, nullable=False, default="pending_review")  # none | pending_review | stale
    verified_claim_count = Column(Integer, nullable=False, default=0)
    total_claim_count = Column(Integer, nullable=False, default=0)
    approved_by = Column(String, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    review_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    repository = relationship("Repository", backref="wiki_pages")
    index_run = relationship("IndexRun", backref="wiki_pages")

    __table_args__ = (
        UniqueConstraint("repository_id", "slug", name="uq_wiki_page_repo_slug"),
    )


class WikiClaim(Base):
    """Citation claims extracted from wiki pages for verification"""
    __tablename__ = "wiki_claims"

    id = Column(String, primary_key=True)
    page_id = Column(String, ForeignKey("wiki_pages.id"), nullable=False, index=True)
    claim_text = Column(Text, nullable=False)
    citation_file = Column(String, nullable=False, index=True)
    line_start = Column(Integer, nullable=True)
    line_end = Column(Integer, nullable=True)
    verified = Column(Boolean, nullable=False, default=False)
    status = Column(String, nullable=False, default="unverified")  # verified | unverified | missing_file
    created_at = Column(DateTime, default=datetime.now)

    page = relationship("WikiPage", backref="claims")


class AnalysisAttributeDefinition(Base):
    """Tenant-scoped attribute definitions for repository analysis (admin-configured)."""
    __tablename__ = "analysis_attribute_definitions"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    key = Column(String, nullable=False, index=True)
    label = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String, nullable=False, default="general")  # runtime, build, security, infra
    data_type = Column(String, nullable=False, default="string")  # string, number, boolean, json
    extraction_hint = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, index=True)
    is_searchable = Column(Boolean, default=True, index=True)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    tenant = relationship("Tenant", backref="analysis_attribute_definitions")

    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_analysis_attr_tenant_key"),
    )


class RepositoryAnalysisAttribute(Base):
    """Extracted attribute values per repository index run — searchable fleet metadata."""
    __tablename__ = "repository_analysis_attributes"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    repository_id = Column(String, ForeignKey("repositories.id"), nullable=False, index=True)
    index_run_id = Column(String, ForeignKey("index_runs.id"), nullable=True, index=True)
    attribute_key = Column(String, nullable=False, index=True)
    attribute_label = Column(String, nullable=False)
    value_text = Column(String, nullable=True, index=True)
    value_json = Column(JSON, nullable=True)
    source_file = Column(String, nullable=True)
    line_start = Column(Integer, nullable=True)
    confidence = Column(String, nullable=False, default="medium")  # high, medium, low
    extracted_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    repository = relationship("Repository", backref="analysis_attributes")
    index_run = relationship("IndexRun", backref="analysis_attributes")

    __table_args__ = (
        Index("idx_repo_analysis_attr_key_value", "attribute_key", "value_text"),
    )


class RepositoryWikiSite(Base):
    """Unified HTML wiki generated by Wiki Agent for a repository."""
    __tablename__ = "repository_wiki_sites"

    id = Column(String, primary_key=True)
    repository_id = Column(String, ForeignKey("repositories.id"), nullable=False, index=True)
    index_run_id = Column(String, ForeignKey("index_runs.id"), nullable=True, index=True)
    title = Column(String, nullable=False)
    html_content = Column(Text, nullable=False)
    summary_json = Column(JSON, nullable=True)
    state = Column(String, nullable=False, default="draft")  # draft | live
    version = Column(Integer, nullable=False, default=1)
    generated_by = Column(String, nullable=False, default="wiki_agent")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    repository = relationship("Repository", backref="wiki_sites")
    index_run = relationship("IndexRun", backref="wiki_sites")


class ApplicationWikiSite(Base):
    """Unified HTML wiki generated by Wiki Agent across an application's member repos."""
    __tablename__ = "application_wiki_sites"

    id = Column(String, primary_key=True)
    application_id = Column(String, ForeignKey("applications.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    html_content = Column(Text, nullable=False)
    summary_json = Column(JSON, nullable=True)
    state = Column(String, nullable=False, default="draft")  # draft | live
    version = Column(Integer, nullable=False, default=1)
    generated_by = Column(String, nullable=False, default="wiki_agent_application")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    application = relationship("Application", backref="wiki_sites")


class RepoAnalysisView(Base):
    """Derived analysis views per repository (blast-radius, domain graph, …)."""
    __tablename__ = "repo_analysis_views"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    repository_id = Column(String, ForeignKey("repositories.id"), nullable=False, index=True)
    view_type = Column(String, nullable=False, index=True)
    anchor_symbol = Column(String, nullable=True)
    summary_sentence = Column(Text, nullable=False)
    mermaid = Column(Text, nullable=True)
    derivation_json = Column(JSON, nullable=True)
    index_run_id = Column(String, ForeignKey("index_runs.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    repository = relationship("Repository", backref="analysis_views")
    index_run = relationship("IndexRun", backref="analysis_views")

    __table_args__ = (
        Index(
            "idx_repo_analysis_view_lookup",
            "repository_id",
            "view_type",
            "anchor_symbol",
        ),
    )


# Create database engine
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Initialize database tables"""
    from app.core.migrations import run_migrations

    try:
        run_migrations()
    except Exception as e:
        logger.warning(f"Alembic migration step skipped or failed: {e}")

    # Legacy SQLite inline migrations — disable with USE_LEGACY_SQLITE_MIGRATIONS=false
    if settings.USE_LEGACY_SQLITE_MIGRATIONS and "sqlite" in settings.DATABASE_URL:
        try:
            with engine.connect() as conn:
                from sqlalchemy import inspect
                inspector = inspect(engine)
                
                # Create tenants table first if it doesn't exist
                if not inspector.has_table("tenants"):
                    conn.execute(text("""
                        CREATE TABLE tenants (
                            id TEXT PRIMARY KEY,
                            name TEXT NOT NULL UNIQUE,
                            description TEXT,
                            is_active INTEGER DEFAULT 1,
                            created_at TEXT,
                            updated_at TEXT
                        )
                    """))
                    conn.execute(text("CREATE INDEX idx_tenants_name ON tenants(name)"))
                    conn.commit()
                    logger.info("Created tenants table")
                
                # Ensure two default tenants exist
                tenant_result = conn.execute(text("SELECT COUNT(*) as count FROM tenants"))
                tenant_count = tenant_result.fetchone()[0]
                
                if tenant_count == 0:
                    # Create two default tenants
                    import uuid
                    tenant1_id = str(uuid.uuid4())
                    tenant2_id = str(uuid.uuid4())
                    conn.execute(text("""
                        INSERT INTO tenants (id, name, description, is_active, created_at, updated_at)
                        VALUES 
                        (:id1, 'tenant1', 'Tenant 1', 1, datetime('now'), datetime('now')),
                        (:id2, 'tenant2', 'Tenant 2', 1, datetime('now'), datetime('now'))
                    """), {"id1": tenant1_id, "id2": tenant2_id})
                    conn.commit()
                    logger.info(f"Created two default tenants: tenant1 (id: {tenant1_id}) and tenant2 (id: {tenant2_id})")
                elif tenant_count == 1:
                    # Check if we need to add tenant2
                    existing_tenant = conn.execute(text("SELECT name FROM tenants LIMIT 1")).fetchone()
                    if existing_tenant:
                        import uuid
                        tenant2_id = str(uuid.uuid4())
                        conn.execute(text("""
                            INSERT INTO tenants (id, name, description, is_active, created_at, updated_at)
                            VALUES (:id, 'tenant2', 'Tenant 2', 1, datetime('now'), datetime('now'))
                        """), {"id": tenant2_id})
                        conn.commit()
                        logger.info(f"Created tenant2 (id: {tenant2_id})")
                
                # Migration: Add tenant_id to users table
                if inspector.has_table("users"):
                    result = conn.execute(text("PRAGMA table_info(users)"))
                    user_columns = [row[1] for row in result]
                    
                    if 'tenant_id' not in user_columns:
                        # Get default tenant ID
                        tenant_result = conn.execute(text("SELECT id FROM tenants LIMIT 1"))
                        default_tenant = tenant_result.fetchone()
                        if default_tenant:
                            default_tenant_id = default_tenant[0]
                            conn.execute(text("ALTER TABLE users ADD COLUMN tenant_id TEXT"))
                            conn.execute(text("UPDATE users SET tenant_id = :tenant_id WHERE tenant_id IS NULL"), 
                                       {"tenant_id": default_tenant_id})
                            conn.execute(text("CREATE INDEX idx_users_tenant_id ON users(tenant_id)"))
                            conn.commit()
                            logger.info("Added tenant_id column to users table")
                
                # Migration: Add tenant_id to projects table
                if inspector.has_table("projects"):
                    result = conn.execute(text("PRAGMA table_info(projects)"))
                    project_columns = [row[1] for row in result]
                    
                    if 'tenant_id' not in project_columns:
                        # Get default tenant ID
                        tenant_result = conn.execute(text("SELECT id FROM tenants LIMIT 1"))
                        default_tenant = tenant_result.fetchone()
                        if default_tenant:
                            default_tenant_id = default_tenant[0]
                            conn.execute(text("ALTER TABLE projects ADD COLUMN tenant_id TEXT"))
                            conn.execute(text("UPDATE projects SET tenant_id = :tenant_id WHERE tenant_id IS NULL"), 
                                       {"tenant_id": default_tenant_id})
                            conn.execute(text("CREATE INDEX idx_projects_tenant_id ON projects(tenant_id)"))
                            conn.commit()
                            logger.info("Added tenant_id column to projects table")

                    # Backfill projects missing tenant_id (create endpoint omitted tenant_id before fix)
                    orphan_count = conn.execute(
                        text("SELECT COUNT(*) FROM projects WHERE tenant_id IS NULL")
                    ).fetchone()[0]
                    if orphan_count > 0:
                        tenant_row = conn.execute(
                            text("SELECT id FROM tenants WHERE name = 'tenant1' LIMIT 1")
                        ).fetchone()
                        if not tenant_row:
                            tenant_row = conn.execute(text("SELECT id FROM tenants LIMIT 1")).fetchone()
                        if tenant_row:
                            conn.execute(
                                text("UPDATE projects SET tenant_id = :tid WHERE tenant_id IS NULL"),
                                {"tid": tenant_row[0]},
                            )
                            conn.commit()
                            logger.info(f"Backfilled tenant_id on {orphan_count} orphan project(s)")
                
                # Migration: Add password_hash column if it doesn't exist
                if inspector.has_table("users"):
                    result = conn.execute(text("PRAGMA table_info(users)"))
                    columns = [row[1] for row in result]
                    
                    if 'password_hash' not in columns:
                        # Add password_hash column
                        conn.execute(text("""
                            ALTER TABLE users 
                            ADD COLUMN password_hash TEXT NOT NULL DEFAULT ''
                        """))
                        conn.commit()
                        logger.info("Added password_hash column to users table")
                
                # Migration: Add new project columns if they don't exist
                if inspector.has_table("projects"):
                    result = conn.execute(text("PRAGMA table_info(projects)"))
                    project_columns = [row[1] for row in result]
                    
                    new_columns = {
                        'description': 'TEXT',
                        'business_value': 'TEXT',
                        'domain': 'TEXT',
                        'priority': 'TEXT',
                        'target_audience': 'TEXT',
                        'step_status': 'TEXT',
                        'github_repo_url': 'TEXT',
                        'default_execution_mode': "TEXT DEFAULT 'copilot'"
                    }
                    
                    for col_name, col_type in new_columns.items():
                        if col_name not in project_columns:
                            conn.execute(text(f"""
                                ALTER TABLE projects 
                                ADD COLUMN {col_name} {col_type}
                            """))
                            conn.commit()
                            logger.info(f"Added {col_name} column to projects table")
                
                # Migration: Add storage_key column to policy_versions table if it doesn't exist
                if inspector.has_table("policy_versions"):
                    result = conn.execute(text("PRAGMA table_info(policy_versions)"))
                    version_columns = [row[1] for row in result]
                    
                    if 'storage_key' not in version_columns:
                        conn.execute(text("ALTER TABLE policy_versions ADD COLUMN storage_key TEXT"))
                        conn.commit()
                        logger.info("Added storage_key column to policy_versions table")
                
                # Migration: Add level and project_id columns to policies table
                if inspector.has_table("policies"):
                    result = conn.execute(text("PRAGMA table_info(policies)"))
                    policy_columns = [row[1] for row in result]
                    
                    if 'level' not in policy_columns:
                        conn.execute(text("ALTER TABLE policies ADD COLUMN level TEXT NOT NULL DEFAULT 'tenant'"))
                        conn.commit()
                        try:
                            conn.execute(text("CREATE INDEX idx_policy_level ON policies(level)"))
                            conn.commit()
                        except Exception:
                            pass  # Index may already exist
                        logger.info("Added level column to policies table")
                    
                    if 'project_id' not in policy_columns:
                        conn.execute(text("ALTER TABLE policies ADD COLUMN project_id TEXT"))
                        conn.commit()
                        try:
                            conn.execute(text("CREATE INDEX idx_policy_project_id ON policies(project_id)"))
                            conn.commit()
                        except Exception:
                            pass  # Index may already exist
                        logger.info("Added project_id column to policies table")
                
                # Migration: Create tasks table if it doesn't exist
                if not inspector.has_table("tasks"):
                    conn.execute(text("""
                        CREATE TABLE tasks (
                            id TEXT PRIMARY KEY,
                            project_id TEXT NOT NULL,
                            task_type TEXT NOT NULL,
                            status TEXT NOT NULL DEFAULT 'pending',
                            progress INTEGER DEFAULT 0,
                            input_data TEXT,
                            result TEXT,
                            error TEXT,
                            created_by TEXT,
                            started_at TEXT,
                            completed_at TEXT,
                            created_at TEXT DEFAULT (datetime('now')),
                            updated_at TEXT DEFAULT (datetime('now')),
                            FOREIGN KEY (project_id) REFERENCES projects(id),
                            FOREIGN KEY (created_by) REFERENCES users(id)
                        )
                    """))
                    conn.execute(text("CREATE INDEX idx_tasks_project_id ON tasks(project_id)"))
                    conn.execute(text("CREATE INDEX idx_tasks_task_type ON tasks(task_type)"))
                    conn.execute(text("CREATE INDEX idx_tasks_status ON tasks(status)"))
                    conn.execute(text("CREATE INDEX idx_tasks_created_at ON tasks(created_at)"))
                    conn.commit()
                    logger.info("Created tasks table with indexes")
                
                # Migration: Add v2 fields to workflow_runs table
                if inspector.has_table("workflow_runs"):
                    result = conn.execute(text("PRAGMA table_info(workflow_runs)"))
                    wr_columns = [row[1] for row in result]
                    
                    v2_columns = {
                        'tenant_id': 'TEXT',
                        'project_id': 'TEXT',
                        'execution_mode': "TEXT NOT NULL DEFAULT 'copilot'",
                        'policy_bundle': 'TEXT',
                        'approval_required': 'INTEGER DEFAULT 1',
                        'deployment_url': 'TEXT',
                        'initiated_by': 'TEXT',
                        'error': 'TEXT',
                    }
                    
                    for col_name, col_type in v2_columns.items():
                        if col_name not in wr_columns:
                            conn.execute(text(f"ALTER TABLE workflow_runs ADD COLUMN {col_name} {col_type}"))
                            conn.commit()
                            logger.info(f"Added {col_name} column to workflow_runs table")
                    
                    # Add indexes for tenant_id and project_id if they were just added
                    if 'tenant_id' not in wr_columns:
                        try:
                            conn.execute(text("CREATE INDEX idx_workflow_runs_tenant_id ON workflow_runs(tenant_id)"))
                            conn.commit()
                        except Exception:
                            pass  # Index may already exist
                    if 'project_id' not in wr_columns:
                        try:
                            conn.execute(text("CREATE INDEX idx_workflow_runs_project_id ON workflow_runs(project_id)"))
                            conn.commit()
                        except Exception:
                            pass  # Index may already exist
                
                # Migration: Create stage_executions table if it doesn't exist
                if not inspector.has_table("stage_executions"):
                    conn.execute(text("""
                        CREATE TABLE stage_executions (
                            id TEXT PRIMARY KEY,
                            workflow_run_id TEXT NOT NULL,
                            stage_name TEXT NOT NULL,
                            status TEXT NOT NULL,
                            started_at TEXT,
                            completed_at TEXT,
                            output_summary TEXT,
                            validation_result TEXT,
                            error TEXT,
                            created_at TEXT DEFAULT (datetime('now')),
                            FOREIGN KEY (workflow_run_id) REFERENCES workflow_runs(id)
                        )
                    """))
                    conn.execute(text("CREATE INDEX idx_stage_executions_workflow_run_id ON stage_executions(workflow_run_id)"))
                    conn.commit()
                    logger.info("Created stage_executions table with indexes")
                
                # Migration: Add v2 fields to approvals table
                if inspector.has_table("approvals"):
                    result = conn.execute(text("PRAGMA table_info(approvals)"))
                    approval_columns = [row[1] for row in result]
                    
                    v2_approval_columns = {
                        'tenant_id': 'TEXT',
                        'workflow_run_id': 'TEXT',
                        'decision': 'TEXT',
                        'feedback': 'TEXT',
                        'edited_output': 'TEXT',
                    }
                    
                    for col_name, col_type in v2_approval_columns.items():
                        if col_name not in approval_columns:
                            conn.execute(text(f"ALTER TABLE approvals ADD COLUMN {col_name} {col_type}"))
                            conn.commit()
                            logger.info(f"Added {col_name} column to approvals table")
                    
                    # Add indexes for new columns
                    if 'tenant_id' not in approval_columns:
                        try:
                            conn.execute(text("CREATE INDEX idx_approvals_tenant_id ON approvals(tenant_id)"))
                            conn.commit()
                        except Exception:
                            pass  # Index may already exist
                    if 'workflow_run_id' not in approval_columns:
                        try:
                            conn.execute(text("CREATE INDEX idx_approvals_workflow_run_id ON approvals(workflow_run_id)"))
                            conn.commit()
                        except Exception:
                            pass  # Index may already exist
                
                # Migration: Create deployments table if it doesn't exist
                if not inspector.has_table("deployments"):
                    conn.execute(text("""
                        CREATE TABLE deployments (
                            id TEXT PRIMARY KEY,
                            tenant_id TEXT NOT NULL,
                            project_id TEXT NOT NULL,
                            workflow_run_id TEXT NOT NULL,
                            status TEXT NOT NULL,
                            provider TEXT NOT NULL,
                            region TEXT NOT NULL,
                            resource_type TEXT,
                            resource_identifiers TEXT,
                            environment_url TEXT,
                            health_check_status TEXT,
                            infrastructure_artifacts TEXT,
                            failure_reason TEXT,
                            last_successful_step TEXT,
                            logs TEXT,
                            created_at TEXT DEFAULT (datetime('now')),
                            updated_at TEXT DEFAULT (datetime('now')),
                            FOREIGN KEY (tenant_id) REFERENCES tenants(id),
                            FOREIGN KEY (project_id) REFERENCES projects(id),
                            FOREIGN KEY (workflow_run_id) REFERENCES workflow_runs(id)
                        )
                    """))
                    conn.execute(text("CREATE INDEX idx_deployments_tenant_id ON deployments(tenant_id)"))
                    conn.execute(text("CREATE INDEX idx_deployments_project_id ON deployments(project_id)"))
                    conn.execute(text("CREATE INDEX idx_deployments_workflow_run_id ON deployments(workflow_run_id)"))
                    conn.commit()
                    logger.info("Created deployments table with indexes")
                
                # Migration: Create execution_logs table if it doesn't exist
                if not inspector.has_table("execution_logs"):
                    conn.execute(text("""
                        CREATE TABLE execution_logs (
                            id TEXT PRIMARY KEY,
                            workflow_run_id TEXT NOT NULL,
                            stage_name TEXT NOT NULL,
                            log_level TEXT NOT NULL DEFAULT 'info',
                            message TEXT NOT NULL,
                            metadata TEXT,
                            created_at TEXT DEFAULT (datetime('now')),
                            FOREIGN KEY (workflow_run_id) REFERENCES workflow_runs(id)
                        )
                    """))
                    conn.execute(text("CREATE INDEX idx_execution_logs_workflow_run_id ON execution_logs(workflow_run_id)"))
                    conn.execute(text("CREATE INDEX idx_execution_logs_stage_name ON execution_logs(stage_name)"))
                    conn.execute(text("CREATE INDEX idx_execution_logs_created_at ON execution_logs(created_at)"))
                    conn.commit()
                    logger.info("Created execution_logs table with indexes")
                
                # Migration: Add tenant_id and sent_at columns to notifications table
                if inspector.has_table("notifications"):
                    result = conn.execute(text("PRAGMA table_info(notifications)"))
                    notif_columns = [row[1] for row in result]
                    
                    if 'tenant_id' not in notif_columns:
                        conn.execute(text("ALTER TABLE notifications ADD COLUMN tenant_id TEXT"))
                        conn.commit()
                        try:
                            conn.execute(text("CREATE INDEX idx_notifications_tenant_id ON notifications(tenant_id)"))
                            conn.commit()
                        except Exception:
                            pass
                        logger.info("Added tenant_id column to notifications table")
                    
                    if 'sent_at' not in notif_columns:
                        conn.execute(text("ALTER TABLE notifications ADD COLUMN sent_at TEXT"))
                        conn.commit()
                        logger.info("Added sent_at column to notifications table")
                
                # Migration: Add tenant_id column to audit_trail table
                if inspector.has_table("audit_trail"):
                    result = conn.execute(text("PRAGMA table_info(audit_trail)"))
                    audit_columns = [row[1] for row in result]
                    
                    if 'tenant_id' not in audit_columns:
                        conn.execute(text("ALTER TABLE audit_trail ADD COLUMN tenant_id TEXT"))
                        conn.commit()
                        try:
                            conn.execute(text("CREATE INDEX idx_audit_trail_tenant_id ON audit_trail(tenant_id)"))
                            conn.commit()
                        except Exception:
                            pass
                        logger.info("Added tenant_id column to audit_trail table")

                # Migration: extend repositories table for GitHub metadata
                if inspector.has_table("repositories"):
                    result = conn.execute(text("PRAGMA table_info(repositories)"))
                    repo_columns = [row[1] for row in result]
                    for col_name, col_type in {
                        "github_owner": "TEXT",
                        "github_repo": "TEXT",
                        "github_org": "TEXT",
                        "github_full_name": "TEXT",
                        "github_credential_id": "TEXT",
                        "last_index_error": "TEXT",
                    }.items():
                        if col_name not in repo_columns:
                            conn.execute(text(f"ALTER TABLE repositories ADD COLUMN {col_name} {col_type}"))
                            conn.commit()
                            logger.info(f"Added {col_name} column to repositories table")

                # Migration: wiki governance columns on wiki_pages
                if inspector.has_table("wiki_pages"):
                    result = conn.execute(text("PRAGMA table_info(wiki_pages)"))
                    wiki_columns = [row[1] for row in result]
                    for col_name, col_type in {
                        "index_run_id": "TEXT",
                        "drift_status": "TEXT DEFAULT 'pending_review'",
                        "verified_claim_count": "INTEGER DEFAULT 0",
                        "total_claim_count": "INTEGER DEFAULT 0",
                        "approved_by": "TEXT",
                        "approved_at": "TEXT",
                        "review_notes": "TEXT",
                    }.items():
                        if col_name not in wiki_columns:
                            conn.execute(text(f"ALTER TABLE wiki_pages ADD COLUMN {col_name} {col_type}"))
                            conn.commit()
                            logger.info(f"Added {col_name} column to wiki_pages table")

                # Migration: Phase 0 — project pillar + modernization link
                if inspector.has_table("projects"):
                    result = conn.execute(text("PRAGMA table_info(projects)"))
                    project_columns = [row[1] for row in result]
                    if "pillar" not in project_columns:
                        conn.execute(text(
                            "ALTER TABLE projects ADD COLUMN pillar TEXT NOT NULL DEFAULT 'build'"
                        ))
                        conn.commit()
                        logger.info("Added pillar column to projects table")
                    if "source_plan_id" not in project_columns:
                        conn.execute(text(
                            "ALTER TABLE projects ADD COLUMN source_plan_id TEXT"
                        ))
                        conn.commit()
                        logger.info("Added source_plan_id column to projects table")
                    if "source_application_id" not in project_columns:
                        conn.execute(text(
                            "ALTER TABLE projects ADD COLUMN source_application_id TEXT"
                        ))
                        conn.commit()
                        logger.info("Added source_application_id column to projects table")
                    if "mode" not in project_columns:
                        conn.execute(text(
                            "ALTER TABLE projects ADD COLUMN mode TEXT"
                        ))
                        conn.commit()
                        logger.info("Added mode column to projects table")
                    conn.execute(text(
                        "UPDATE projects SET pillar = 'build' WHERE pillar IS NULL OR pillar = ''"
                    ))
                    conn.commit()

                if inspector.has_table("applications"):
                    result = conn.execute(text("PRAGMA table_info(applications)"))
                    app_columns = [row[1] for row in result]
                    if "origin" not in app_columns:
                        conn.execute(text(
                            "ALTER TABLE applications ADD COLUMN origin TEXT NOT NULL DEFAULT 'imported'"
                        ))
                        conn.commit()
                        logger.info("Added origin column to applications table")
                    conn.execute(text(
                        "UPDATE applications SET origin = 'imported' "
                        "WHERE origin IS NULL OR origin = ''"
                    ))
                    conn.commit()

                if inspector.has_table("modernization_plans"):
                    result = conn.execute(text("PRAGMA table_info(modernization_plans)"))
                    plan_columns = [row[1] for row in result]
                    for col_name, col_type in {
                        "source_application_id": "TEXT",
                        "plan_bundle_id": "TEXT",
                    }.items():
                        if col_name not in plan_columns:
                            conn.execute(text(
                                f"ALTER TABLE modernization_plans ADD COLUMN {col_name} {col_type}"
                            ))
                            conn.commit()
                            logger.info(f"Added {col_name} column to modernization_plans table")

                if inspector.has_table("savi_work_items"):
                    result = conn.execute(text("PRAGMA table_info(savi_work_items)"))
                    work_columns = [row[1] for row in result]
                    if "context_refs" not in work_columns:
                        conn.execute(text(
                            "ALTER TABLE savi_work_items ADD COLUMN context_refs JSON"
                        ))
                        conn.commit()
                        logger.info("Added context_refs column to savi_work_items table")
                    for col_name, col_type in {
                        "pr_url": "TEXT",
                        "pr_number": "INTEGER",
                        "pr_repository_id": "TEXT",
                        "connector_meta": "JSON",
                        "orchestrator_phase": "TEXT",
                        "orchestrator_timeline": "JSON",
                        "orchestrator_tokens": "INTEGER",
                        "orchestrator_error": "TEXT",
                        "cancel_requested": "BOOLEAN",
                        "approval_base_sha": "TEXT",
                        "approval_diff_hash": "TEXT",
                        "approval_bound_at": "DATETIME",
                    }.items():
                        if col_name not in work_columns:
                            conn.execute(text(
                                f"ALTER TABLE savi_work_items ADD COLUMN {col_name} {col_type}"
                            ))
                            conn.commit()
                            logger.info(
                                f"Added {col_name} column to savi_work_items table"
                            )

                if inspector.has_table("wiki_pages"):
                    result = conn.execute(text("PRAGMA table_info(wiki_pages)"))
                    wiki_cols = [row[1] for row in result]
                    if "content_hash" not in wiki_cols:
                        conn.execute(text(
                            "ALTER TABLE wiki_pages ADD COLUMN content_hash TEXT"
                        ))
                        conn.commit()
                        logger.info("Added content_hash column to wiki_pages table")

                if inspector.has_table("savi_instances"):
                    result = conn.execute(text("PRAGMA table_info(savi_instances)"))
                    savi_columns = [row[1] for row in result]
                    for col_name, col_type in {
                        "external_identity_provider": "TEXT",
                        "external_identity_subject": "TEXT",
                        "external_identity_display": "TEXT",
                        "external_identity_metadata": "JSON",
                        "external_identity_linked_at": "DATETIME",
                        "external_identity_linked_by": "TEXT",
                    }.items():
                        if col_name not in savi_columns:
                            conn.execute(text(
                                f"ALTER TABLE savi_instances ADD COLUMN {col_name} {col_type}"
                            ))
                            conn.commit()
                            logger.info(
                                f"Added {col_name} column to savi_instances table"
                            )

        except Exception as e:
            logger.warning(f"Could not migrate database: {e}")
    
    # Create all tables AFTER migrations (for new tables)
    Base.metadata.create_all(bind=engine)

    # Seed default tenant configs for tenants without one
    try:
        from app.services.tenant_config_service import TenantConfigService, default_capabilities
        import uuid as _uuid
        db = SessionLocal()
        try:
            tenants = db.query(Tenant).all()
            for tenant in tenants:
                existing = db.query(TenantConfig).filter(TenantConfig.tenant_id == tenant.id).first()
                if not existing:
                    has_projects = db.query(Project).filter(Project.tenant_id == tenant.id).count() > 0
                    # Existing tenants with projects skip onboarding; new tenants choose a path
                    onboarding = "full" if has_projects else None
                    caps = default_capabilities() if not has_projects else {
                        **default_capabilities(),
                    }
                    if onboarding == "full" and settings.INTELLIGENCE_ENABLED:
                        caps["intelligence"] = True
                    db.add(TenantConfig(
                        id=str(_uuid.uuid4()),
                        tenant_id=tenant.id,
                        capabilities=caps,
                        onboarding_path=onboarding,
                    ))
                else:
                    # Merge Phase 0 capability keys into existing tenant configs
                    merged = {
                        **default_capabilities(),
                        **(existing.capabilities or {}),
                    }
                    if merged != existing.capabilities:
                        existing.capabilities = merged
            db.commit()
            _seed_system_modernization_playbooks(db)
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Could not seed tenant configs: {e}")


def _seed_system_modernization_playbooks(db) -> None:
    """Seed built-in modernization playbooks (tenant_id NULL = global)."""
    import uuid as _uuid

    defaults = [
        {
            "name": "Java 8 → 17",
            "description": "Upgrade JDK and resolve deprecated API usage.",
            "checklist_json": [
                "Inventory JDK / Maven / Gradle targets",
                "Run compatibility analysis",
                "Update build toolchain",
                "Fix compile errors and deprecated APIs",
                "Run full test suite",
            ],
            "seed_content_md": "# Modernization: Java 8 → 17\n\nMigrate runtime and build to Java 17 LTS.",
        },
        {
            "name": "Spring Boot 2 → 3",
            "description": "Migrate Spring Boot application to Jakarta EE namespace.",
            "checklist_json": [
                "Identify Spring Boot version and starters",
                "Update javax → jakarta imports",
                "Upgrade Spring Security config if present",
                "Validate REST endpoints and integration tests",
            ],
            "seed_content_md": "# Modernization: Spring Boot 2 → 3\n\nUpgrade framework and dependencies.",
        },
    ]
    for item in defaults:
        exists = (
            db.query(ModernizationPlaybook)
            .filter(
                ModernizationPlaybook.name == item["name"],
                ModernizationPlaybook.is_system == True,  # noqa: E712
            )
            .first()
        )
        if exists:
            continue
        db.add(
            ModernizationPlaybook(
                id=str(_uuid.uuid4()),
                tenant_id=None,
                name=item["name"],
                description=item["description"],
                checklist_json=item["checklist_json"],
                seed_content_md=item["seed_content_md"],
                is_system=True,
            )
        )
    db.commit()


def get_db():
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================================
# Policy Management Models
# ============================================================================

class PolicyCategory(Base):
    """Policy category lookup"""
    __tablename__ = "policy_categories"
    
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False, unique=True, index=True)  # ideation, requirements, stories, architecture, coding, testing, security, infra, building_blocks
    display_name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)


class Policy(Base):
    """Policy registry - metadata and status"""
    __tablename__ = "policies"
    
    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=True, index=True)
    policy_id = Column(String, nullable=False, index=True)  # e.g., "PIPE-001", "IDEA-001"
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String, nullable=False, index=True)  # References policy_categories.name
    status = Column(String, nullable=False, default="draft", index=True)  # draft, active, deprecated
    applies_to = Column(JSON, nullable=True)  # ["story", "architecture", "backend", "frontend", "pipeline", "infra"]
    stacks = Column(JSON, nullable=True)  # ["Java/Spring", "Next/React", "Nuxt/Vue"]
    tags = Column(JSON, nullable=True)  # ["PII", "PCI", "Public API", "Internal"]
    level = Column(String, nullable=False, default="tenant", index=True)  # global, tenant, project
    project_id = Column(String, ForeignKey("projects.id"), nullable=True, index=True)  # For project-level policies
    active_version_id = Column(String, ForeignKey("policy_versions.id"), nullable=True)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    updated_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    versions = relationship(
        "PolicyVersion",
        primaryjoin="Policy.id == PolicyVersion.policy_id",
        back_populates="policy",
        cascade="all, delete-orphan",
        order_by="PolicyVersion.version_number"
    )
    active_version = relationship("PolicyVersion", foreign_keys=[active_version_id], post_update=True)
    tenant = relationship("Tenant", backref="policies")
    project = relationship("Project", backref="policies")
    
    __table_args__ = (
        UniqueConstraint('policy_id', 'tenant_id', name='uq_policy_id_tenant'),
        Index('idx_policy_status_category', 'status', 'category'),
        Index('idx_policy_level', 'level'),
        Index('idx_policy_project_id', 'project_id'),
    )


class PolicyVersion(Base):
    """Policy version - stores content and versioning"""
    __tablename__ = "policy_versions"
    
    id = Column(String, primary_key=True)
    policy_id = Column(String, ForeignKey("policies.id"), nullable=False, index=True)
    version_number = Column(String, nullable=False)  # e.g., "1.0.0", "1.2.0-draft.3"
    content = Column(JSON, nullable=True)  # Full policy content (YAML/JSON structure) - cached in DB for quick access
    content_yaml = Column(Text, nullable=True)  # Raw YAML content for advanced editor - cached in DB
    storage_key = Column(String, nullable=True)  # Path/key to file in storage (local or S3)
    is_draft = Column(Boolean, default=True, index=True)
    requires_approval = Column(Boolean, default=False)
    approved_by = Column(String, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    
    # Relationships
    policy = relationship("Policy", foreign_keys=[policy_id], back_populates="versions")
    
    __table_args__ = (
        UniqueConstraint('policy_id', 'version_number', name='uq_policy_version'),
        Index('idx_policy_version_draft', 'policy_id', 'is_draft'),
    )


class PolicyAttachment(Base):
    """Attachments for policies (PDFs, links, etc.)"""
    __tablename__ = "policy_attachments"
    
    id = Column(String, primary_key=True)
    policy_id = Column(String, ForeignKey("policies.id"), nullable=False, index=True)
    attachment_type = Column(String, nullable=False)  # pdf, link, repo, confluence
    name = Column(String, nullable=False)
    url = Column(String, nullable=True)  # For links, S3 path for files
    s3_key = Column(String, nullable=True)  # S3 object key if stored in S3
    description = Column(Text, nullable=True)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    
    # Relationships
    policy = relationship("Policy", backref="attachments")


class PolicyBundle(Base):
    """Policy bundles - coherent sets of policies"""
    __tablename__ = "policy_bundles"
    
    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=True, index=True)
    name = Column(String, nullable=False)  # e.g., "baseline", "public-api", "pii", "regulated"
    description = Column(Text, nullable=True)
    version = Column(String, nullable=False)  # e.g., "v1.0.0"
    is_active = Column(Boolean, default=False, index=True)
    policy_ids = Column(JSON, nullable=False)  # List of policy IDs in this bundle
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    activated_at = Column(DateTime, nullable=True)
    
    # Relationships
    tenant = relationship("Tenant", backref="policy_bundles")
    
    __table_args__ = (
        UniqueConstraint('name', 'version', 'tenant_id', name='uq_bundle_name_version_tenant'),
    )


class BuildingBlock(Base):
    """Building blocks catalog - reusable libraries, templates, etc."""
    __tablename__ = "building_blocks"
    
    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=True, index=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False, index=True)  # repo, template, pdf, yaml, json
    description = Column(Text, nullable=True)
    url = Column(String, nullable=True)  # Git repo URL, S3 path, etc.
    s3_key = Column(String, nullable=True)  # S3 object key if stored in S3
    applicable_stacks = Column(JSON, nullable=True)  # ["Java/Spring", "Next/React"]
    enforcement = Column(String, nullable=False, default="recommended")  # required, recommended, deprecated
    version = Column(String, nullable=True)  # Git tag, commit SHA, version number
    owner = Column(String, nullable=True)
    usage_guidance = Column(Text, nullable=True)
    when_to_use = Column(Text, nullable=True)
    tags = Column(JSON, nullable=True)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    tenant = relationship("Tenant", backref="building_blocks")
    
    __table_args__ = (
        UniqueConstraint('name', 'tenant_id', name='uq_building_block_name_tenant'),
    )


class PolicyAuditLog(Base):
    """Audit trail for policy changes"""
    __tablename__ = "policy_audit_logs"
    
    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=True, index=True)
    policy_id = Column(String, ForeignKey("policies.id"), nullable=True, index=True)
    action_type = Column(String, nullable=False, index=True)  # created, updated, published, deprecated, deleted
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    changes = Column(JSON, nullable=True)  # What changed
    previous_version = Column(String, nullable=True)
    new_version = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.now, index=True)
    
    # Relationships
    user = relationship("User", foreign_keys=[user_id])
    policy = relationship("Policy", foreign_keys=[policy_id])
    tenant = relationship("Tenant", foreign_keys=[tenant_id])


# ============================================================================
# Deployment Model
# ============================================================================

class Deployment(Base):
    """Tracks ephemeral environment deployments"""
    __tablename__ = "deployments"

    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    workflow_run_id = Column(String, ForeignKey("workflow_runs.id"), nullable=False, index=True)
    status = Column(String, nullable=False)  # provisioning, deploying, health_checking, live, failed, torn_down
    provider = Column(String, nullable=False)  # ecs, eks, lambda
    region = Column(String, nullable=False)
    resource_type = Column(String, nullable=True)
    resource_identifiers = Column(JSON, nullable=True)
    environment_url = Column(String, nullable=True)
    health_check_status = Column(String, nullable=True)
    infrastructure_artifacts = Column(JSON, nullable=True)  # Terraform/Helm references
    failure_reason = Column(Text, nullable=True)
    last_successful_step = Column(String, nullable=True)
    logs = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # Relationships
    tenant = relationship("Tenant", backref="deployments")
    project = relationship("Project", backref="deployments")
    workflow_run = relationship("WorkflowRun", backref="deployments")


# ============================================================================
# ExecutionLog Model
# ============================================================================

class ExecutionLog(Base):
    """Stores streaming execution log entries for the Live Run Monitor"""
    __tablename__ = "execution_logs"

    id = Column(String, primary_key=True)
    workflow_run_id = Column(String, ForeignKey("workflow_runs.id"), nullable=False, index=True)
    stage_name = Column(String, nullable=False, index=True)
    log_level = Column(String, nullable=False, default="info")  # info, warning, error
    message = Column(Text, nullable=False)
    metadata_ = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.now, index=True)

    # Relationships
    workflow_run = relationship("WorkflowRun", backref="execution_logs")
