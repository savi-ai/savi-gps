"""Pydantic models for GPS service"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime
from enum import Enum


class ArtifactType(str, Enum):
    """Types of artifacts that can be validated"""
    STORY = "story"
    ARCHITECTURE = "architecture"
    INFRA = "infra"
    PIPELINE = "pipeline"


class SOPCategory(str, Enum):
    """SOP categories"""
    SECURITY = "security"
    PERFORMANCE = "performance"
    LOGGING = "logging"
    INFRASTRUCTURE = "infrastructure"
    CI_CD = "ci_cd"
    ARCHITECTURE = "architecture"


class RunUntil(str, Enum):
    """Workflow execution stop points"""
    STORIES = "stories"
    ARCHITECTURE = "architecture"
    SCAFFOLDING = "scaffolding"


# SOP Models
class SOPRule(BaseModel):
    """A rule defined in an SOP"""
    id: str
    title: str
    description: str
    severity: str  # critical, high, medium, low
    guidelines: List[str]


class SOPCheck(BaseModel):
    """A check defined in an SOP"""
    type: Literal["pattern", "questionnaire", "metric"]
    description: str
    pattern: Optional[str] = None
    questions: Optional[List[str]] = None
    metric_name: Optional[str] = None
    threshold: Optional[float] = None


class SOP(BaseModel):
    """Standard Operating Procedure"""
    id: str
    name: str
    version: str
    category: str
    status: str
    description: str
    rules: List[SOPRule] = []
    applies_to: List[str] = []
    enforcement: str = "required"
    validation: List[str] = []
    
    # Legacy fields for backward compatibility
    title: Optional[str] = None
    tags: List[str] = []
    checks: List[SOPCheck] = []
    remediation_hints: Dict[str, str] = {}
    
    def __init__(self, **data):
        # If title is not provided, use name
        if 'title' not in data and 'name' in data:
            data['title'] = data['name']
        super().__init__(**data)


class SOPValidationRequest(BaseModel):
    """Request to validate an artifact against SOPs"""
    artifact_type: ArtifactType
    context: Dict[str, Any] = Field(default_factory=dict)
    artifact_content: str


class Violation(BaseModel):
    """A violation found during SOP validation"""
    sop_id: str
    sop_title: str
    check_type: str
    description: str
    remediation_hint: Optional[str] = None


class SOPValidationResponse(BaseModel):
    """Response from SOP validation"""
    valid: bool
    violations: List[Violation] = Field(default_factory=list)
    applicable_sops: List[str] = Field(default_factory=list)


# Workflow Models
class IdeaInput(BaseModel):
    """Input for idea agent"""
    idea: str
    clarifying_questions: Optional[List[str]] = None


class Feature(BaseModel):
    """Feature definition"""
    title: str
    description: str
    business_value: str
    actors: List[str] = []
    high_level_flow: str
    acceptance_criteria: List[str] = []


class Story(BaseModel):
    """User story"""
    title: str
    description: str
    persona: str
    goal: str
    gherkin_acceptance_criteria: str
    nfrs: List[str] = []
    status: Literal["approved", "needs_changes"] = "needs_changes"


class Component(BaseModel):
    """System component"""
    name: str
    responsibility: str
    apis: List[str] = []
    data_stores: List[str] = []
    interactions: List[str] = []


class Architecture(BaseModel):
    """System architecture"""
    pattern: str
    description: str
    containers: List[Dict[str, Any]] = []
    components: List[Component] = []
    bounded_contexts: List[str] = []
    domain_events: List[str] = []


class StackSelection(BaseModel):
    """Stack and blueprint selection"""
    component_name: str
    implementation_stack: str
    infra_patterns: List[str] = []
    template_id: Optional[str] = None


class GoldenPathRunRequest(BaseModel):
    """Request to run golden path workflow"""
    idea: Optional[str] = None
    feature_ids: Optional[List[str]] = None
    options: Dict[str, Any] = Field(default_factory=lambda: {"run_until": "scaffolding"})


class WorkflowState(BaseModel):
    """Workflow state snapshot"""
    run_id: str
    stage: str
    idea: Optional[str] = None
    vision: Optional[str] = None
    candidate_features: List[Dict[str, Any]] = Field(default_factory=list)
    features: List[Dict[str, Any]] = Field(default_factory=list)
    stories: List[Dict[str, Any]] = Field(default_factory=list)
    domain_model: Optional[Dict[str, Any]] = None
    architecture: Optional[Dict[str, Any]] = None
    stack_selections: List[Dict[str, Any]] = Field(default_factory=list)
    scaffolding: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class GoldenPathRunResponse(BaseModel):
    """Response from golden path run"""
    run_id: str
    status: str
    state: WorkflowState
    results: List[Dict[str, Any]] = []


class WorkflowRunStatus(BaseModel):
    """Workflow run status"""
    run_id: str
    status: str
    current_stage: str
    created_at: datetime
    updated_at: datetime


# ── v2 Models ──────────────────────────────────────────────────────────


class ExecutionMode(str, Enum):
    """Workflow execution modes"""
    AUTOPILOT = "autopilot"
    COPILOT = "copilot"


class EnhancedGoldenPathRunRequest(BaseModel):
    """Request to run golden path workflow with v2 execution mode support"""
    idea: Optional[str] = None
    feature_ids: Optional[List[str]] = None
    execution_mode: ExecutionMode = ExecutionMode.COPILOT
    options: Dict[str, Any] = Field(default_factory=lambda: {"run_until": "scaffolding"})


class PolicyViolation(BaseModel):
    """A policy violation found during validation"""
    policy_name: str
    rule_violated: str
    remediation_hint: Optional[str] = None


class ValidationResult(BaseModel):
    """Unified validation result combining SOP and policy checks"""
    passed: bool
    sop_violations: List[Violation] = Field(default_factory=list)
    policy_violations: List[PolicyViolation] = Field(default_factory=list)
    warnings: List[Violation] = Field(default_factory=list)
    remediation_hints: List[str] = Field(default_factory=list)


class ApprovalRequest(BaseModel):
    """Request to create an approval checkpoint"""
    project_id: str
    stage_name: str
    from_user_id: str
    to_roles: List[str]
    workflow_run_id: Optional[str] = None


class ApprovalDecision(BaseModel):
    """Decision submitted for an approval checkpoint"""
    approval_id: str
    decision: Literal["approved", "rejected"]
    approver_id: str
    comments: Optional[str] = None
    edited_output: Optional[Dict[str, Any]] = None


class DeploymentStatus(BaseModel):
    """Deployment status and details"""
    deployment_id: str
    workflow_run_id: str
    status: str  # provisioning, deploying, health_checking, live, failed, torn_down
    provider: Optional[str] = None
    region: Optional[str] = None
    resource_type: Optional[str] = None
    resource_identifiers: Optional[Dict[str, Any]] = None
    environment_url: Optional[str] = None
    health_check_status: Optional[str] = None
    failure_reason: Optional[str] = None
    last_successful_step: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class NotificationCreate(BaseModel):
    """Request to create a notification"""
    recipient: str
    notification_type: str  # completion, failure, approval_request, deployment_success, deployment_failure
    content: str
    context: Optional[Dict[str, Any]] = None


class ResolvedPolicy(BaseModel):
    """A single resolved policy within the effective set"""
    policy_id: str
    name: str
    category: str
    level: str  # global, tenant, project
    content: Any
    version: Optional[str] = None
    updated_at: Optional[datetime] = None


class EffectivePolicySet(BaseModel):
    """Resolved policy set keyed by category after merge"""
    policies_by_category: Dict[str, ResolvedPolicy] = Field(default_factory=dict)
    tenant_id: Optional[str] = None
    project_id: Optional[str] = None
    resolved_at: Optional[datetime] = None

