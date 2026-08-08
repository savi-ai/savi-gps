"""Golden Path workflow API endpoints"""
from fastapi import APIRouter, HTTPException, Security, Depends, Query
from starlette.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional, List
from pydantic import BaseModel
from app.core.models import (
    GoldenPathRunRequest, GoldenPathRunResponse, WorkflowRunStatus,
    RunUntil, WorkflowState,
    EnhancedGoldenPathRunRequest, ApprovalDecision, ExecutionMode,
)
from app.services.workflow_orchestrator import WorkflowOrchestrator
from app.services.agents.idea_agent import IdeaAgent
from app.services.agents.feature_agent import FeatureAgent
from app.services.agents.architecture_agent import ArchitectureAgent
from app.services.agents.story_agent import StoryAgent
from app.services.agents.scaffolding_agents import BackendScaffoldingAgent, FrontendScaffoldingAgent
from app.services.agents.developer_agent import DeveloperAgent
from app.services.agents.testing_agent import TestingAgent
from app.core.database import (
    get_db, WorkflowRun, BusinessApplication, Project, User,
    StageExecution, Approval, ExecutionLog,
)
from app.core.auth import verify_api_key, get_current_user, require_permission, has_permission
from app.core.tenant_isolation import verify_tenant_access, scope_query_by_tenant
from app.core.audit_service import log_audit_event, WORKFLOW_STARTED, APPROVAL_APPROVED, APPROVAL_REJECTED
from app.core.logger import logger
from datetime import datetime
import asyncio
import json
import uuid

router = APIRouter(prefix="/golden-path", tags=["Golden Path"])

# Global orchestrator instance
orchestrator = WorkflowOrchestrator()

# Individual agent instances for wizard steps
idea_agent = IdeaAgent()
feature_agent = FeatureAgent()
architecture_agent = ArchitectureAgent()
story_agent = StoryAgent()
backend_scaffolding_agent = BackendScaffoldingAgent()
frontend_scaffolding_agent = FrontendScaffoldingAgent()
developer_agent = DeveloperAgent()
testing_agent = TestingAgent()


class IdeaRequest(BaseModel):
    idea: str


class FeaturesRequest(BaseModel):
    project_name: str
    conversation_history: Optional[list] = None  # Full conversation for context
    vision: Optional[str] = None
    candidate_features: Optional[list] = None


class ArchitectureRequest(BaseModel):
    project_id: str
    project_name: str
    features: list
    domain_model: Optional[dict] = None


class StoriesRequest(BaseModel):
    features: list


class ImplementationRequest(BaseModel):
    stories: list
    architecture: dict
    stack_selections: Optional[list] = None


class ProjectCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    business_value: Optional[str] = None
    domain: Optional[str] = None
    priority: Optional[str] = None
    target_audience: Optional[str] = None
    default_execution_mode: Optional[str] = "copilot"  # autopilot or copilot
    pillar: Optional[str] = "build"  # build | modernize
    repository_ids: Optional[List[str]] = None
    application_id: Optional[str] = None
    target_application_id: Optional[str] = None  # alias of application_id (ADR 0006)
    mode: Optional[str] = None  # greenfield | enhance | extend


class ProjectResponse(BaseModel):
    id: str
    name: str
    current_step: str
    pillar: str = "build"
    mode: Optional[str] = None
    source_plan_id: Optional[str] = None
    source_application_id: Optional[str] = None
    source_application_name: Optional[str] = None
    target_application_id: Optional[str] = None
    target_application_name: Optional[str] = None
    default_execution_mode: Optional[str] = "copilot"
    created_at: str
    updated_at: str


class IdeaChatRequest(BaseModel):
    project_id: str
    message: str
    conversation_history: Optional[list] = None  # List of {role: str, content: str}


class IdeaChatResponse(BaseModel):
    response: str
    questions_answered: int = 0  # Number of questions answered (0-3)
    ready_for_next: bool = False  # True when all 3 questions are answered
    sources: Optional[List[dict]] = None
    citations: Optional[List[str]] = None


class DeveloperRequest(BaseModel):
    story: dict
    architecture: dict
    stack_selections: Optional[list] = None


class TestingRequest(BaseModel):
    stories: list
    code_implementation: Optional[dict] = None
    architecture: dict


@router.post("/run", response_model=GoldenPathRunResponse)
async def run_golden_path(
    request: GoldenPathRunRequest,
    api_key: bool = Security(verify_api_key),
    db: Session = Depends(get_db)
):
    """Run the Golden Path workflow"""
    try:
        run_until = RunUntil(request.options.get("run_until", "scaffolding"))
        
        result = await orchestrator.run(
            idea=request.idea,
            feature_ids=request.feature_ids,
            run_until=run_until
        )
        
        # Persist workflow run
        workflow_run = WorkflowRun(
            id=result["run_id"],
            status=result["status"],
            current_stage=result["state"].get("stage", "unknown"),
            state_snapshot=result["state"]
        )
        db.add(workflow_run)
        db.commit()
        
        # Convert to response model
        state_data = result["state"]
        workflow_state = WorkflowState(
            run_id=result["run_id"],
            stage=state_data.get("stage", ""),
            idea=state_data.get("idea"),
            vision=state_data.get("vision"),
            candidate_features=state_data.get("candidate_features", []),
            features=state_data.get("features", []),
            stories=state_data.get("stories", []),
            domain_model=state_data.get("domain_model", {}),
            architecture=state_data.get("architecture", {}),
            stack_selections=state_data.get("stack_selections", []),
            scaffolding=state_data.get("scaffolding", {}),
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        
        return GoldenPathRunResponse(
            run_id=result["run_id"],
            status=result["status"],
            state=workflow_state,
            results=result.get("results", [])
        )
        
    except Exception as e:
        logger.error(f"Error running Golden Path workflow: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/runs/{run_id}", response_model=WorkflowRunStatus)
async def get_workflow_run(
    run_id: str,
    api_key: bool = Security(verify_api_key),
    db: Session = Depends(get_db)
):
    """Get workflow run status and state"""
    workflow_run = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
    
    if not workflow_run:
        raise HTTPException(status_code=404, detail=f"Workflow run {run_id} not found")
    
    return WorkflowRunStatus(
        run_id=workflow_run.id,
        status=workflow_run.status,
        current_stage=workflow_run.current_stage,
        created_at=workflow_run.created_at,
        updated_at=workflow_run.updated_at
    )


@router.get("/runs/{run_id}/state", response_model=WorkflowState)
async def get_workflow_state(
    run_id: str,
    api_key: bool = Security(verify_api_key),
    db: Session = Depends(get_db)
):
    """Get full workflow state for a run"""
    workflow_run = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
    
    if not workflow_run:
        raise HTTPException(status_code=404, detail=f"Workflow run {run_id} not found")
    
    state_snapshot = workflow_run.state_snapshot or {}
    
    return WorkflowState(
        run_id=workflow_run.id,
        stage=state_snapshot.get("stage", ""),
        idea=state_snapshot.get("idea"),
        vision=state_snapshot.get("vision"),
        candidate_features=state_snapshot.get("candidate_features", []),
        features=state_snapshot.get("features", []),
        stories=state_snapshot.get("stories", []),
        domain_model=state_snapshot.get("domain_model", {}),
        architecture=state_snapshot.get("architecture", {}),
        stack_selections=state_snapshot.get("stack_selections", []),
        scaffolding=state_snapshot.get("scaffolding", {}),
        created_at=workflow_run.created_at,
        updated_at=workflow_run.updated_at
    )




@router.post("/wizard/generate-features")
async def generate_features(
    request: FeaturesRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Start feature generation using task queue (wizard step 2) - returns immediately, use polling endpoint"""
    try:
        from app.services.task_service import TaskService, TaskType
        
        # Get project (filter by tenant)
        project = db.query(Project).filter(
            Project.name == request.project_name,
            Project.tenant_id == user.tenant_id
        ).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Build conversation history
        conversation_history = request.conversation_history or project.conversation_history or []
        if isinstance(conversation_history, str):
            try:
                conversation_history = json.loads(conversation_history)
            except:
                conversation_history = []
        
        # Create task
        task_service = TaskService(db)
        task = task_service.create_task(
            project_id=project.id,
            task_type=TaskType.GENERATE_FEATURES,
            input_data={
                "idea": project.description or "",
                "vision": request.vision or project.vision or "",
                "candidate_features": request.candidate_features or [],
                "conversation_history": conversation_history
            },
            user_id=user.id
        )
        
        # Update project status
        project.feature_generation_status = "started"
        project.current_step = "features"
        db.commit()
        
        logger.info(f"Created feature generation task {task.id} for project {project.id}")
        
        return {
            "status": "started",
            "task_id": task.id,
            "message": "Feature generation started. Use polling endpoint to check status."
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting feature generation: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/wizard/features-status/{project_name}")
async def get_features_status(
    project_name: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Poll for feature generation status"""
    try:
        from app.services.task_service import TaskService, TaskType, TaskStatus
        
        project = db.query(Project).filter(
            Project.name == project_name,
            Project.tenant_id == user.tenant_id
        ).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Get the most recent feature generation task for this project
        task_service = TaskService(db)
        tasks = task_service.get_project_tasks(
            project_id=project.id,
            task_type=TaskType.GENERATE_FEATURES
        )
        
        if not tasks:
            return {
                "status": "pending",
                "message": "No feature generation task found"
            }
        
        # Get the most recent task
        task = tasks[0]
        
        # Map task status to response
        status_map = {
            TaskStatus.PENDING: "pending",
            TaskStatus.RUNNING: "started",
            TaskStatus.COMPLETED: "completed",
            TaskStatus.FAILED: "failed",
            TaskStatus.CANCELLED: "failed"
        }
        
        status = status_map.get(task.status, "pending")
        
        # Update project status
        project.feature_generation_status = status
        
        if task.status == TaskStatus.COMPLETED:
            # Get task result
            result = task_service.get_task_result(task.id)
            if result and "features" in result:
                features_data = result["features"]
                project.features = features_data
                project.feature_generation_status = "completed"
                db.commit()
                
                return {
                    "status": "completed",
                    "features": features_data,
                    "task_id": task.id
                }
        elif task.status == TaskStatus.FAILED:
            project.feature_generation_status = "failed"
            db.commit()
            return {
                "status": "failed",
                "error": task.error,
                "task_id": task.id
            }
        
        db.commit()
        
        return {
            "status": status,
            "progress": task.progress,
            "task_id": task.id,
            "message": "Feature generation in progress. Please poll again." if status == "started" else None
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking features status: {e}")
        raise HTTPException(status_code=500, detail=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/wizard/generate-architecture")
async def generate_architecture(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Start architecture generation using task queue (wizard step 4)"""
    try:
        from app.services.task_service import TaskService, TaskType
        
        # Get project (filter by tenant)
        project = db.query(Project).filter(
            Project.id == project_id,
            Project.tenant_id == user.tenant_id
        ).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Ensure project has features
        if not project.features or len(project.features) == 0:
            raise HTTPException(status_code=400, detail="Project must have features before generating architecture")
        
        # Get stories if available (optional but helpful)
        stories = project.stories or []

        from app.services.build.build_context_service import BuildContextService
        repo_context = BuildContextService(db).get_architecture_context(project.id, user.tenant_id)
        
        # Create task
        task_service = TaskService(db)
        task = task_service.create_task(
            project_id=project.id,
            task_type=TaskType.GENERATE_ARCHITECTURE,
            input_data={
                "features": project.features,
                "stories": stories,
                "repo_context": repo_context,
            },
            user_id=user.id
        )
        
        # Update project status
        project.current_step = "architecture"
        db.commit()
        
        logger.info(f"Created architecture generation task {task.id} for project {project.id}")
        
        return {
            "status": "started",
            "task_id": task.id,
            "message": "Architecture generation started. Poll task status to check progress."
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting architecture generation: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/wizard/architecture-status/{project_id}")
async def get_architecture_status(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Poll for architecture generation status"""
    try:
        from app.services.task_service import TaskService, TaskType, TaskStatus
        
        project = db.query(Project).filter(
            Project.id == project_id,
            Project.tenant_id == user.tenant_id
        ).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Get the most recent architecture generation task for this project
        task_service = TaskService(db)
        tasks = task_service.get_project_tasks(
            project_id=project.id,
            task_type=TaskType.GENERATE_ARCHITECTURE
        )
        
        if not tasks:
            return {
                "status": "pending",
                "message": "No architecture generation task found"
            }
        
        # Get the most recent task
        task = tasks[0]
        
        # Map task status to response
        status_map = {
            TaskStatus.PENDING: "pending",
            TaskStatus.RUNNING: "started",
            TaskStatus.COMPLETED: "completed",
            TaskStatus.FAILED: "failed",
            TaskStatus.CANCELLED: "failed"
        }
        
        status = status_map.get(task.status, "pending")
        
        if task.status == TaskStatus.COMPLETED:
            # Get task result
            result = task_service.get_task_result(task.id)
            if result and "architecture" in result:
                architecture_data = result["architecture"]
                project.architecture = architecture_data
                db.commit()
                
                return {
                    "status": "completed",
                    "architecture": architecture_data,
                    "task_id": task.id
                }
        elif task.status == TaskStatus.FAILED:
            db.commit()
            return {
                "status": "failed",
                "error": task.error,
                "task_id": task.id
            }
        
        db.commit()
        
        return {
            "status": status,
            "progress": task.progress,
            "task_id": task.id,
            "message": "Architecture generation in progress. Please poll again." if status == "started" else None
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking architecture status: {e}")
        raise HTTPException(status_code=500, detail=str(e))




@router.post("/wizard/generate-stories")
async def generate_stories(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Start story generation using task queue (wizard step 3)"""
    try:
        from app.services.task_service import TaskService, TaskType
        
        # Get project (filter by tenant)
        project = db.query(Project).filter(
            Project.id == project_id,
            Project.tenant_id == user.tenant_id
        ).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Ensure project has features
        if not project.features or len(project.features) == 0:
            raise HTTPException(status_code=400, detail="Project must have features before generating stories")
        
        # Create task
        task_service = TaskService(db)
        task = task_service.create_task(
            project_id=project.id,
            task_type=TaskType.GENERATE_STORIES,
            input_data={
                "features": project.features
            },
            user_id=user.id
        )
        
        # Update project status
        project.current_step = "stories"
        db.commit()
        
        logger.info(f"Created story generation task {task.id} for project {project.id}")
        
        return {
            "status": "started",
            "task_id": task.id,
            "message": "Story generation started. Poll task status to check progress."
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting story generation: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/wizard/implement-stories")
async def implement_stories(
    request: ImplementationRequest,
    api_key: bool = Security(verify_api_key)
):
    """Generate code implementation from stories (wizard step 4)"""
    try:
        state = {
            "stories": request.stories,
            "architecture": request.architecture,
            "stack_selections": request.stack_selections or []
        }
        
        # Generate backend scaffolding
        state = await backend_scaffolding_agent.process(state)
        
        # Generate frontend scaffolding
        state = await frontend_scaffolding_agent.process(state)
        
        return {
            "scaffolding": state.get("scaffolding", {}),
            "implementation": {
                "backend": state.get("scaffolding", {}).get("backend", {}),
                "frontend": state.get("scaffolding", {}).get("frontend", {})
            }
        }
    except Exception as e:
        logger.error(f"Error implementing stories: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/projects")
async def create_project(
    request: ProjectCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new project - requires can_create_project permission"""
    # Check permission
    if not has_permission(user, "can_create_project", db):
        raise HTTPException(status_code=403, detail="Permission denied: cannot create projects")
    
    try:
        # Check if project name already exists in this tenant
        existing = db.query(Project).filter(
            Project.name == request.name,
            Project.tenant_id == user.tenant_id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"Project with name '{request.name}' already exists")

        pillar = (request.pillar or "build").lower()
        if pillar not in ("build", "modernize"):
            raise HTTPException(status_code=400, detail="pillar must be 'build' or 'modernize'")

        from app.services.build.project_application_service import (
            ensure_target_application,
            maybe_mark_hybrid_after_link,
            normalize_mode,
            project_target_payload,
            resolve_target_application_id,
        )

        requested_app_id = resolve_target_application_id(
            application_id=request.application_id,
            target_application_id=request.target_application_id,
        )
        # Default mode: greenfield when no target app; enhance when app provided
        try:
            mode = normalize_mode(
                request.mode,
                default="enhance" if requested_app_id else "greenfield",
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        try:
            target_app = ensure_target_application(
                db,
                tenant_id=user.tenant_id,
                user_id=user.id,
                mode=mode,
                project_name=request.name,
                project_description=request.description,
                project_domain=request.domain,
                application_id=requested_app_id,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        project = Project(
            id=str(uuid.uuid4()),
            tenant_id=user.tenant_id,
            name=request.name,
            pillar=pillar,
            mode=mode,
            description=request.description,
            business_value=request.business_value,
            domain=request.domain,
            priority=request.priority,
            target_audience=request.target_audience,
            default_execution_mode=request.default_execution_mode or "copilot",
            conversation_history=json.dumps([]),  # Store as JSON string for SQLite
            current_step="idea",
            source_application_id=target_app.id,
        )
        db.add(project)
        db.flush()

        from app.services.build.project_repository_resolver import resolve_project_repository_ids

        # Greenfield: only explicitly selected repos (usually none).
        # Enhance/extend: merge application members + explicit picks.
        repo_ids_to_link = resolve_project_repository_ids(
            db,
            user.tenant_id,
            repository_ids=request.repository_ids,
            application_id=None if mode == "greenfield" else target_app.id,
        )

        if repo_ids_to_link:
            from app.services.build.build_context_service import attach_repositories
            link_type = "modernization" if pillar == "modernize" else "context"
            try:
                attach_repositories(
                    db,
                    user.tenant_id,
                    project.id,
                    repo_ids_to_link,
                    link_type=link_type,
                )
            except ValueError as e:
                db.rollback()
                raise HTTPException(status_code=400, detail=str(e))

        maybe_mark_hybrid_after_link(
            target_app, mode=mode, linked_repo_count=len(repo_ids_to_link or [])
        )

        db.commit()
        db.refresh(project)

        target_fields = project_target_payload(project, target_app.name)

        return ProjectResponse(
            id=project.id,
            name=project.name,
            current_step=project.current_step,
            pillar=project.pillar or "build",
            mode=project.mode,
            source_plan_id=project.source_plan_id,
            default_execution_mode=project.default_execution_mode,
            created_at=project.created_at.isoformat() if project.created_at else "",
            updated_at=project.updated_at.isoformat() if project.updated_at else "",
            **target_fields,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating project: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/context-preview")
async def preview_project_context(
    repository_ids: Optional[str] = None,
    application_id: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Preview Intelligence context that Build agents will receive for selected scope."""
    from app.services.build.build_context_service import BuildContextService
    from app.services.build.project_repository_resolver import resolve_project_repository_ids

    explicit_ids = [r.strip() for r in (repository_ids or "").split(",") if r.strip()]
    resolved = resolve_project_repository_ids(
        db, user.tenant_id, repository_ids=explicit_ids or None, application_id=application_id
    )
    payload = BuildContextService(db).preview_repositories_context(user.tenant_id, resolved)
    payload["resolved_repository_ids"] = resolved
    return payload


@router.get("/projects")
async def list_projects(
    pillar: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all projects for the current user's tenant"""
    try:
        logger.info(f"Listing all projects for tenant {user.tenant_id}")
        query = db.query(Project).filter(Project.tenant_id == user.tenant_id)
        if pillar:
            normalized = pillar.lower()
            if normalized not in ("build", "modernize"):
                raise HTTPException(status_code=400, detail="pillar must be 'build' or 'modernize'")
            query = query.filter(Project.pillar == normalized)
        projects = query.order_by(Project.updated_at.desc()).all()
        logger.info(f"Found {len(projects)} projects")

        from app.core.database import Application

        app_ids = {p.source_application_id for p in projects if p.source_application_id}
        app_names: dict = {}
        if app_ids:
            apps = db.query(Application).filter(Application.id.in_(app_ids)).all()
            app_names = {a.id: a.name for a in apps}
        
        projects_list = [
            {
                "id": p.id,
                "name": p.name,
                "pillar": p.pillar or "build",
                "mode": getattr(p, "mode", None),
                "source_plan_id": p.source_plan_id,
                "source_application_id": p.source_application_id,
                "target_application_id": p.source_application_id,
                "source_application_name": app_names.get(p.source_application_id)
                if p.source_application_id
                else None,
                "target_application_name": app_names.get(p.source_application_id)
                if p.source_application_id
                else None,
                "current_step": p.current_step or "idea",
                "created_at": p.created_at.isoformat() if p.created_at else "",
                "updated_at": p.updated_at.isoformat() if p.updated_at else ""
            }
            for p in projects
        ]
        
        logger.info(f"Returning {len(projects_list)} projects")
        return {
            "projects": projects_list
        }
    except Exception as e:
        logger.error(f"Error listing projects: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{project_id}")
async def get_project(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get project details including conversation history"""
    try:
        project = db.query(Project).filter(
            Project.id == project_id,
            Project.tenant_id == user.tenant_id
        ).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Parse conversation_history if it's a JSON string
        conversation_history = project.conversation_history
        if isinstance(conversation_history, str):
            try:
                conversation_history = json.loads(conversation_history)
            except:
                conversation_history = []
        elif conversation_history is None:
            conversation_history = []

        from app.services.build.build_context_service import BuildContextService
        linked_repos = BuildContextService(db).get_linked_repositories(project_id, user.tenant_id)

        source_application = None
        if project.source_application_id:
            from app.core.database import Application

            app = (
                db.query(Application)
                .filter(
                    Application.id == project.source_application_id,
                    Application.tenant_id == user.tenant_id,
                )
                .first()
            )
            if app:
                source_application = {"id": app.id, "name": app.name}
        
        return {
            "id": project.id,
            "name": project.name,
            "pillar": project.pillar or "build",
            "mode": getattr(project, "mode", None),
            "source_plan_id": project.source_plan_id,
            "source_application_id": project.source_application_id,
            "target_application_id": project.source_application_id,
            "source_application": source_application,
            "target_application": source_application,
            "source_application_name": source_application["name"] if source_application else None,
            "target_application_name": source_application["name"] if source_application else None,
            "description": project.description,
            "business_value": project.business_value,
            "domain": project.domain,
            "priority": project.priority,
            "target_audience": project.target_audience,
            "default_execution_mode": getattr(project, 'default_execution_mode', 'copilot'),
            "conversation_history": conversation_history,
            "vision": project.vision,
            "features": project.features,
            "architecture": project.architecture,
            "stories": project.stories,
            "code_implementation": project.code_implementation,
            "tests": project.tests,
            "current_step": project.current_step,
            "step_status": project.step_status,
            "feature_generation_status": project.feature_generation_status,
            "linked_repositories": linked_repos,
            "created_at": project.created_at.isoformat() if project.created_at else "",
            "updated_at": project.updated_at.isoformat() if project.updated_at else ""
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting project: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{project_id}/context")
async def get_project_context(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return linked repositories and wiki summaries for a Build project."""
    from app.services.build.build_context_service import BuildContextService

    try:
        return BuildContextService(db).get_project_context_payload(project_id, user.tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/wizard/idea")
async def process_idea(
    request: IdeaRequest,
    api_key: bool = Security(verify_api_key),
):
    """Process an idea into a vision and candidate features (standalone, no project required)"""
    try:
        state = {"idea": request.idea}
        result = await idea_agent.process(state)

        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])

        return {
            "vision": result.get("vision", ""),
            "features": result.get("candidate_features", []),
            "clarifying_questions": result.get("clarifying_questions", []),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing idea: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/wizard/idea-chat")
async def idea_chat(
    request: IdeaChatRequest,
    api_key: bool = Security(verify_api_key),
    db: Session = Depends(get_db)
):
    """Chat with Idea Agent to refine the idea (wizard step 1) - auto-saves to database"""
    try:
        # Get project
        project = db.query(Project).filter(Project.id == request.project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        if not project.tenant_id:
            raise HTTPException(status_code=400, detail="Project has no tenant context")

        from app.services.build.build_context_service import BuildContextService
        import re

        ctx_service = BuildContextService(db)
        repo_context = await ctx_service.build_query_context(
            project.id,
            project.tenant_id,
            request.message,
        )
        context_block = repo_context.get("context_block") or ""
        sources = repo_context.get("sources") or []

        context_addon = ""
        if context_block:
            context_addon = (
                "\n\nLINKED REPOSITORY CONTEXT:\n"
                "The project is connected to existing codebases. Use this context when relevant.\n"
                "Cite evidence with backticks: `path/to/file.ext:42` or `wiki/slug`.\n"
                "Reference existing services, EJBs, APIs, and components by their real names.\n"
                f"---\n{context_block}\n---"
            )

        # Parse conversation_history from database if it's a JSON string
        conversation_history = request.conversation_history
        if not conversation_history:
            db_history = project.conversation_history
            if isinstance(db_history, str):
                try:
                    conversation_history = json.loads(db_history)
                except:
                    conversation_history = []
            elif db_history is None:
                conversation_history = []
            else:
                conversation_history = db_history
        
        # Build messages for chat
        messages = [
            {"role": "system", "content": IdeaAgent.SYSTEM_PROMPT + context_addon}
        ]
        
        # Add conversation history
        for msg in conversation_history:
            role = msg.get("role", "user")
            messages.append({"role": role, "content": msg.get("content", "")})
        
        # Add current message
        messages.append({"role": "user", "content": request.message})
        
        # Use chat method for conversational response
        from app.services.llm_routing import get_other_llm_client

        llm = get_other_llm_client(db, project.tenant_id)
        response_text = await llm.chat(messages)
        
        # Check if LLM response indicates readiness to proceed
        # Look for keywords that suggest the idea is refined and ready
        response_lower = response_text.lower()
        ready_indicators = [
            'ready to proceed',
            'ready for the next step',
            'ready to move forward',
            'ready to generate',
            'sufficient information',
            'enough information',
            'can proceed',
            'move to requirements',
            'continue to requirements',
            'proceed to features'
        ]
        
        # Also check conversation length as fallback
        user_messages = [msg.get("content", "").lower() for msg in messages if msg.get("role") == "user"]
        assistant_messages = [msg.get("content", "").lower() for msg in messages if msg.get("role") == "assistant"]
        
        questions_answered = 0
        if len(user_messages) > 1:
            qa_pairs = min(len(assistant_messages), len(user_messages) - 1)
            questions_answered = qa_pairs
        
        # Check if response indicates readiness OR if we have enough conversation
        has_ready_indicator = any(indicator in response_lower for indicator in ready_indicators)
        has_enough_conversation = len(messages) >= 7 or questions_answered >= 3
        
        ready_for_next = has_ready_indicator or has_enough_conversation
        
        # Save conversation to database
        updated_conversation = conversation_history + [
            {"role": "user", "content": request.message},
            {"role": "assistant", "content": response_text}
        ]
        # SQLite JSON column - store as JSON string
        project.conversation_history = json.dumps(updated_conversation) if updated_conversation else json.dumps([])
        
        # Update step_status if ready for next step
        if ready_for_next and project.current_step == "idea":
            project.step_status = "ReadyForNext"
        
        project.updated_at = datetime.now()
        db.commit()

        citation_pattern = re.compile(r"`([^`\n]+?)(?::(\d+)(?:-(\d+))?)?`")
        citations: List[str] = []
        for match in citation_pattern.finditer(response_text):
            path = match.group(1)
            line = match.group(2)
            cite = f"{path}:{line}" if line else path
            if cite not in citations:
                citations.append(cite)
        
        return IdeaChatResponse(
            response=response_text,
            questions_answered=min(questions_answered, 3),
            ready_for_next=ready_for_next,
            sources=sources if sources else None,
            citations=citations if citations else None,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in idea chat: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/projects/{project_id}/step")
async def update_project_step(
    project_id: str,
    step: str = Query(..., description="The step to update to"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update project's current step"""
    try:
        project = db.query(Project).filter(
            Project.id == project_id,
            Project.tenant_id == user.tenant_id
        ).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        valid_steps = ['idea', 'features', 'architecture', 'stories', 'developer', 'testing']
        if step not in valid_steps:
            raise HTTPException(status_code=400, detail=f"Invalid step. Must be one of: {', '.join(valid_steps)}")
        
        # When moving from idea to features, mark idea step as completed
        if project.current_step == "idea" and step == "features":
            project.step_status = "Completed"
        elif step == "idea":
            # If going back to idea step, reset status
            project.step_status = None
        else:
            # For other step transitions, reset status (will be set when that step is ready)
            project.step_status = None
        
        project.current_step = step
        project.updated_at = datetime.now()
        db.commit()
        db.refresh(project)
        
        return {
            "id": project.id,
            "current_step": project.current_step,
            "updated_at": project.updated_at.isoformat() if project.updated_at else ""
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating project step: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/projects/{project_id}/features")
async def update_project_features(
    project_id: str,
    features: list,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update project features"""
    try:
        project = db.query(Project).filter(
            Project.id == project_id,
            Project.tenant_id == user.tenant_id
        ).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Validate features structure
        if not isinstance(features, list):
            raise HTTPException(status_code=400, detail="Features must be a list")
        
        # Save features to database
        project.features = features
        project.updated_at = datetime.now()
        db.commit()
        db.refresh(project)
        
        return {
            "id": project.id,
            "features": project.features,
            "updated_at": project.updated_at.isoformat() if project.updated_at else ""
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating project features: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{project_id}/stories")
async def get_project_stories(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all stories for a project"""
    try:
        project = db.query(Project).filter(
            Project.id == project_id,
            Project.tenant_id == user.tenant_id
        ).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        stories = project.stories or []
        
        return {
            "project_id": project.id,
            "stories": stories,
            "count": len(stories)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting project stories: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/projects/{project_id}/stories")
async def update_project_stories(
    project_id: str,
    stories: list,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update project stories"""
    try:
        project = db.query(Project).filter(
            Project.id == project_id,
            Project.tenant_id == user.tenant_id
        ).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Validate stories structure
        if not isinstance(stories, list):
            raise HTTPException(status_code=400, detail="Stories must be a list")
        
        # Validate each story has required fields
        for story in stories:
            if not isinstance(story, dict):
                raise HTTPException(status_code=400, detail="Each story must be an object")
            required_fields = ['title', 'description', 'persona', 'goal']
            for field in required_fields:
                if field not in story:
                    raise HTTPException(status_code=400, detail=f"Story missing required field: {field}")
        
        # Save stories to database
        project.stories = stories
        project.updated_at = datetime.now()
        db.commit()
        db.refresh(project)
        
        return {
            "id": project.id,
            "stories": project.stories,
            "count": len(project.stories),
            "updated_at": project.updated_at.isoformat() if project.updated_at else ""
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating project stories: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/projects/{project_id}/stories/{story_id}")
async def delete_story(
    project_id: str,
    story_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a specific story from a project"""
    try:
        project = db.query(Project).filter(
            Project.id == project_id,
            Project.tenant_id == user.tenant_id
        ).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        stories = project.stories or []
        
        # Find and remove the story
        story_found = False
        updated_stories = []
        for story in stories:
            if story.get('id') != story_id:
                updated_stories.append(story)
            else:
                story_found = True
        
        if not story_found:
            raise HTTPException(status_code=404, detail="Story not found")
        
        # Update project
        project.stories = updated_stories
        project.updated_at = datetime.now()
        db.commit()
        
        return {
            "message": "Story deleted successfully",
            "story_id": story_id,
            "remaining_count": len(updated_stories)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting story: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/projects/{project_id}/stories/{story_id}/approve")
async def approve_story(
    project_id: str,
    story_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Approve a specific story"""
    try:
        project = db.query(Project).filter(
            Project.id == project_id,
            Project.tenant_id == user.tenant_id
        ).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        stories = project.stories or []
        
        # Find and approve the story
        story_found = False
        for story in stories:
            if story.get('id') == story_id:
                story['status'] = 'approved'
                story_found = True
                break
        
        if not story_found:
            raise HTTPException(status_code=404, detail="Story not found")
        
        # Update project
        project.stories = stories
        project.updated_at = datetime.now()
        db.commit()
        
        return {
            "message": "Story approved successfully",
            "story_id": story_id,
            "status": "approved"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error approving story: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{project_id}/architecture")
async def get_project_architecture(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get architecture for a project"""
    try:
        project = db.query(Project).filter(
            Project.id == project_id,
            Project.tenant_id == user.tenant_id
        ).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        architecture = project.architecture or {}
        
        return {
            "project_id": project.id,
            "architecture": architecture
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting project architecture: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/projects/{project_id}/architecture")
async def update_project_architecture(
    project_id: str,
    architecture: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update project architecture"""
    try:
        project = db.query(Project).filter(
            Project.id == project_id,
            Project.tenant_id == user.tenant_id
        ).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Validate architecture structure
        if not isinstance(architecture, dict):
            raise HTTPException(status_code=400, detail="Architecture must be an object")
        
        # Validate react_flow_diagrams if present
        if "react_flow_diagrams" in architecture:
            rfd = architecture["react_flow_diagrams"]
            if not isinstance(rfd, dict):
                raise HTTPException(status_code=400, detail="react_flow_diagrams must be an object")
            for diagram_type, diagram_data in rfd.items():
                if diagram_type not in ("context", "container", "component"):
                    raise HTTPException(status_code=400, detail=f"Invalid diagram type: {diagram_type}")
                if not isinstance(diagram_data, dict):
                    raise HTTPException(status_code=400, detail=f"Diagram '{diagram_type}' must be an object with nodes and edges")
                for node in diagram_data.get("nodes", []):
                    errors = []
                    if not isinstance(node.get("id"), str):
                        errors.append("node.id must be a string")
                    if not isinstance(node.get("type"), str):
                        errors.append("node.type must be a string")
                    if not isinstance(node.get("data", {}).get("label"), str):
                        errors.append("node.data.label must be a string")
                    pos = node.get("position", {})
                    if not isinstance(pos.get("x"), (int, float)) or not isinstance(pos.get("y"), (int, float)):
                        errors.append("node.position must have numeric x and y")
                    if errors:
                        raise HTTPException(status_code=400, detail=f"Invalid node '{node.get('id', '?')}': {'; '.join(errors)}")
                for edge in diagram_data.get("edges", []):
                    errors = []
                    if not isinstance(edge.get("id"), str):
                        errors.append("edge.id must be a string")
                    if not isinstance(edge.get("source"), str):
                        errors.append("edge.source must be a string")
                    if not isinstance(edge.get("target"), str):
                        errors.append("edge.target must be a string")
                    if errors:
                        raise HTTPException(status_code=400, detail=f"Invalid edge '{edge.get('id', '?')}': {'; '.join(errors)}")
        
        # Save architecture to database
        project.architecture = architecture
        project.updated_at = datetime.now()
        db.commit()
        db.refresh(project)
        
        return {
            "id": project.id,
            "architecture": project.architecture,
            "updated_at": project.updated_at.isoformat() if project.updated_at else ""
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating project architecture: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/wizard/generate-code")
async def generate_code(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Start code generation using task queue (wizard step 5)"""
    try:
        from app.services.task_service import TaskService, TaskType
        
        # Get project (filter by tenant)
        project = db.query(Project).filter(
            Project.id == project_id,
            Project.tenant_id == user.tenant_id
        ).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Ensure project has architecture and stories
        if not project.architecture:
            raise HTTPException(status_code=400, detail="Project must have architecture before generating code")
        if not project.stories or len(project.stories) == 0:
            raise HTTPException(status_code=400, detail="Project must have stories before generating code")
        
        # Prepare input data
        input_data = {
            "architecture": project.architecture,
            "stories": project.stories
        }
        
        # Include GitHub repo URL if configured
        if project.github_repo_url:
            input_data["github_repo_url"] = project.github_repo_url
        
        # Create task
        task_service = TaskService(db)
        task = task_service.create_task(
            project_id=project.id,
            task_type=TaskType.GENERATE_CODE,
            input_data=input_data,
            user_id=user.id
        )
        
        # Update project status
        project.current_step = "developer"
        db.commit()
        
        logger.info(f"Created code generation task {task.id} for project {project.id}")
        
        return {
            "status": "started",
            "task_id": task.id,
            "message": "Code generation started. Poll task status to check progress."
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting code generation: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/wizard/code-status/{project_id}")
async def get_code_status(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Poll for code generation status"""
    try:
        from app.services.task_service import TaskService, TaskType, TaskStatus
        
        project = db.query(Project).filter(
            Project.id == project_id,
            Project.tenant_id == user.tenant_id
        ).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Get the most recent code generation task for this project
        task_service = TaskService(db)
        tasks = task_service.get_project_tasks(
            project_id=project.id,
            task_type=TaskType.GENERATE_CODE
        )
        
        if not tasks:
            return {
                "status": "pending",
                "message": "No code generation task found"
            }
        
        # Get the most recent task
        task = tasks[0]
        
        # Map task status to response
        status_map = {
            TaskStatus.PENDING: "pending",
            TaskStatus.RUNNING: "started",
            TaskStatus.COMPLETED: "completed",
            TaskStatus.FAILED: "failed",
            TaskStatus.CANCELLED: "failed"
        }
        
        status = status_map.get(task.status, "pending")
        
        if task.status == TaskStatus.COMPLETED:
            # Get task result
            result = task_service.get_task_result(task.id)
            if result and "code_implementation" in result:
                code_data = result["code_implementation"]
                project.code_implementation = code_data
                db.commit()
                
                return {
                    "status": "completed",
                    "code_implementation": code_data,
                    "task_id": task.id
                }
        elif task.status == TaskStatus.FAILED:
            db.commit()
            return {
                "status": "failed",
                "error": task.error,
                "task_id": task.id
            }
        
        db.commit()
        
        return {
            "status": status,
            "progress": task.progress,
            "task_id": task.id,
            "message": "Code generation in progress. Please poll again." if status == "started" else None
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking code status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{project_id}/code")
async def get_project_code(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get generated code for a project"""
    try:
        project = db.query(Project).filter(
            Project.id == project_id,
            Project.tenant_id == user.tenant_id
        ).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        code_implementation = project.code_implementation or {}
        
        return {
            "project_id": project.id,
            "code_implementation": code_implementation
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting project code: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/projects/{project_id}/code/download")
async def download_project_code(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Generate and download code as a zip file"""
    try:
        from fastapi.responses import StreamingResponse
        import io
        import zipfile
        
        project = db.query(Project).filter(
            Project.id == project_id,
            Project.tenant_id == user.tenant_id
        ).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        if not project.code_implementation:
            raise HTTPException(status_code=404, detail="No code generated for this project")
        
        code_impl = project.code_implementation
        
        # Create zip file in memory
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # Add README if available
            if code_impl.get('documentation', {}).get('readme'):
                zip_file.writestr('README.md', code_impl['documentation']['readme'])
            
            # Add setup instructions
            if code_impl.get('documentation', {}).get('setup_instructions'):
                zip_file.writestr('SETUP.md', code_impl['documentation']['setup_instructions'])
            
            # Add API documentation
            if code_impl.get('documentation', {}).get('api_documentation'):
                zip_file.writestr('API.md', code_impl['documentation']['api_documentation'])
            
            # Add architecture notes
            if code_impl.get('documentation', {}).get('architecture_notes'):
                zip_file.writestr('ARCHITECTURE.md', code_impl['documentation']['architecture_notes'])
            
            # Add all generated files
            for file_info in code_impl.get('files', []):
                file_path = file_info.get('path', '')
                file_content = file_info.get('content', '')
                if file_path and file_content:
                    zip_file.writestr(file_path, file_content)
            
            # Add configuration files
            for config_info in code_impl.get('configuration', []):
                config_path = config_info.get('path', '')
                config_content = config_info.get('content', '')
                if config_path and config_content:
                    zip_file.writestr(config_path, config_content)
        
        # Prepare the zip file for download
        zip_buffer.seek(0)
        
        # Generate filename
        safe_project_name = project.name.replace(' ', '_').replace('/', '_')
        filename = f"{safe_project_name}_code.zip"
        
        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading project code: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/projects/{project_id}/github-repo")
async def update_github_repo(
    project_id: str,
    github_repo_url: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update GitHub repository URL for a project and graduate into Intelligence inventory."""
    try:
        project = db.query(Project).filter(
            Project.id == project_id,
            Project.tenant_id == user.tenant_id
        ).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Validate GitHub URL format
        if github_repo_url and not (
            github_repo_url.startswith('https://github.com/') or 
            github_repo_url.startswith('git@github.com:')
        ):
            raise HTTPException(
                status_code=400, 
                detail="Invalid GitHub URL. Must start with https://github.com/ or git@github.com:"
            )
        
        project.github_repo_url = github_repo_url
        db.commit()

        graduation = None
        if github_repo_url:
            from app.services.build.project_repo_graduation_service import (
                graduate_project_github_repo,
            )

            try:
                # Register + attach now; indexing waits until code is pushed
                graduation = graduate_project_github_repo(
                    db,
                    project,
                    github_repo_url=github_repo_url,
                    created_by=user.id,
                    start_index=False,
                )
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
        
        logger.info(f"Updated GitHub repo URL for project {project.id}: {github_repo_url}")
        
        return {
            "success": True,
            "message": "GitHub repository URL updated successfully",
            "github_repo_url": (graduation or {}).get("github_repo_url") or github_repo_url,
            "graduation": graduation,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating GitHub repo URL: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/projects/{project_id}/push-to-github")
async def push_to_github(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Manually trigger push of generated code to GitHub and graduate into Intelligence."""
    try:
        from app.services.git_service import get_git_service
        
        project = db.query(Project).filter(
            Project.id == project_id,
            Project.tenant_id == user.tenant_id
        ).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        if not project.github_repo_url:
            raise HTTPException(
                status_code=400, 
                detail="GitHub repository URL not configured for this project"
            )
        
        if not project.code_implementation:
            raise HTTPException(
                status_code=400, 
                detail="No code generated for this project"
            )
        
        # Push to GitHub
        git_service = get_git_service()
        result = git_service.push_code_to_github(
            repo_url=project.github_repo_url,
            code_implementation=project.code_implementation,
            project_name=project.name,
            branch_name="savi/code_scaffolded"
        )
        
        if result.get('success'):
            logger.info(f"Successfully pushed code to GitHub for project {project.id}")
            graduation = None
            try:
                from app.services.build.project_repo_graduation_service import (
                    graduate_project_github_repo,
                )

                graduation = graduate_project_github_repo(
                    db,
                    project,
                    created_by=user.id,
                    start_index=True,
                )
            except Exception as grad_err:
                logger.warning(
                    "Push succeeded but graduation/index failed for project %s: %s",
                    project.id,
                    grad_err,
                )
            result = {**result, "graduation": graduation}
            return result
        else:
            logger.error(f"Failed to push code to GitHub: {result.get('error')}")
            raise HTTPException(status_code=500, detail=result.get('error'))
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error pushing to GitHub: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/wizard/generate-tests")
async def generate_tests(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Start test generation using task queue (wizard step 6)"""
    try:
        from app.services.task_service import TaskService, TaskType
        
        # Get project (filter by tenant)
        project = db.query(Project).filter(
            Project.id == project_id,
            Project.tenant_id == user.tenant_id
        ).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Ensure project has code implementation
        if not project.code_implementation:
            raise HTTPException(status_code=400, detail="Project must have code implementation before generating tests")
        
        # Prepare input data
        input_data = {
            "stories": project.stories or [],
            "code_implementation": project.code_implementation,
            "architecture": project.architecture or {}
        }
        
        # Add GitHub configuration if available
        if project.github_repo_url:
            input_data['github_repo_url'] = project.github_repo_url
            # Tests will use timestamp-based branch name (generated in task worker)
            # Branch format: savi/tests-YYYYMMDD-HHMMSS
        
        # Create task
        task_service = TaskService(db)
        task = task_service.create_task(
            project_id=project.id,
            task_type=TaskType.GENERATE_TESTS,
            input_data=input_data,
            user_id=user.id
        )
        
        # Update project status
        project.current_step = "testing"
        db.commit()
        
        logger.info(f"Created test generation task {task.id} for project {project.id}")
        
        return {
            "status": "started",
            "task_id": task.id,
            "message": "Test generation started. Poll task status to check progress."
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting test generation: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/wizard/tests-status/{project_id}")
async def get_tests_status(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get test generation task status"""
    try:
        from app.services.task_service import TaskService, TaskType
        
        # Verify project access
        project = db.query(Project).filter(
            Project.id == project_id,
            Project.tenant_id == user.tenant_id
        ).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Get most recent test generation task
        task_service = TaskService(db)
        tasks = task_service.get_project_tasks(project_id, task_type=TaskType.GENERATE_TESTS)
        
        if not tasks:
            return {"status": "not_started"}
        
        # Get most recent task
        latest_task = tasks[0]
        
        return {
            "status": latest_task.status,
            "progress": latest_task.progress,
            "error": latest_task.error,
            "task_id": latest_task.id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting tests status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{project_id}/tests")
async def get_project_tests(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get generated tests for a project"""
    try:
        project = db.query(Project).filter(
            Project.id == project_id,
            Project.tenant_id == user.tenant_id
        ).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        if not project.tests:
            raise HTTPException(status_code=404, detail="No tests generated for this project")
        
        return project.tests
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting project tests: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/projects/{project_id}/tests/download")
async def download_project_tests(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Generate and download tests as a zip file"""
    try:
        from fastapi.responses import StreamingResponse
        import io
        import zipfile
        
        project = db.query(Project).filter(
            Project.id == project_id,
            Project.tenant_id == user.tenant_id
        ).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        if not project.tests:
            raise HTTPException(status_code=404, detail="No tests generated for this project")
        
        tests = project.tests
        
        # Create zip file in memory
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # Add unit tests
            for test_info in tests.get('unit_tests', []):
                test_path = test_info.get('path', '')
                test_content = test_info.get('content', '')
                if test_path and test_content:
                    zip_file.writestr(test_path, test_content)
            
            # Add integration tests
            for test_info in tests.get('integration_tests', []):
                test_path = test_info.get('path', '')
                test_content = test_info.get('content', '')
                if test_path and test_content:
                    zip_file.writestr(test_path, test_content)
            
            # Add test data fixtures
            for fixture_info in tests.get('test_data', {}).get('fixtures', []):
                fixture_path = fixture_info.get('path', '')
                fixture_content = fixture_info.get('content', '')
                if fixture_path and fixture_content:
                    zip_file.writestr(fixture_path, fixture_content)
            
            # Add test data factories
            for factory_info in tests.get('test_data', {}).get('factories', []):
                factory_path = factory_info.get('path', '')
                factory_content = factory_info.get('content', '')
                if factory_path and factory_content:
                    zip_file.writestr(factory_path, factory_content)
            
            # Add test configuration
            for config_info in tests.get('test_configuration', []):
                config_path = config_info.get('path', '')
                config_content = config_info.get('content', '')
                if config_path and config_content:
                    zip_file.writestr(config_path, config_content)
            
            # Add test utilities
            for util_info in tests.get('test_utilities', []):
                util_path = util_info.get('path', '')
                util_content = util_info.get('content', '')
                if util_path and util_content:
                    zip_file.writestr(util_path, util_content)
            
            # Add README with test commands
            if tests.get('test_commands'):
                readme_content = f"""# Test Suite

## Running Tests

```bash
# Run all tests
{tests['test_commands'].get('run_all', 'pytest')}

# Run unit tests only
{tests['test_commands'].get('run_unit', 'pytest tests/unit')}

# Run integration tests only
{tests['test_commands'].get('run_integration', 'pytest tests/integration')}

# Run with coverage
{tests['test_commands'].get('coverage', 'pytest --cov=src --cov-report=html')}
```

## Coverage Target

Target: {tests.get('coverage_target', 80)}%

## Test Structure

- `tests/unit/` - Unit tests
- `tests/integration/` - Integration tests
- `tests/fixtures/` - Test data fixtures
- `tests/factories/` - Data factories
- `tests/utils/` - Test utilities
"""
                zip_file.writestr('README.md', readme_content)
        
        # Prepare the zip file for download
        zip_buffer.seek(0)
        
        # Generate filename
        safe_project_name = project.name.replace(' ', '_').replace('/', '_')
        filename = f"{safe_project_name}_tests.zip"
        
        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading project tests: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/applications")
async def get_applications(
    api_key: bool = Security(verify_api_key),
    db: Session = Depends(get_db)
):
    """Get all business applications"""
    try:
        applications = db.query(BusinessApplication).all()
        return {
            "applications": [
                {
                    "id": app.id,
                    "name": app.name,
                    "type": app.type,
                    "status": app.status,
                    "created_at": app.created_at.isoformat() if app.created_at else None,
                    "updated_at": app.updated_at.isoformat() if app.updated_at else None
                }
                for app in applications
            ]
        }
    except Exception as e:
        logger.error(f"Error fetching applications: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/applications")
async def create_application(
    name: str,
    type: str,
    api_key: bool = Security(verify_api_key),
    db: Session = Depends(get_db)
):
    """Create a new business application"""
    try:
        app = BusinessApplication(
            id=str(uuid.uuid4()),
            name=name,
            type=type,
            status="draft"
        )
        db.add(app)
        db.commit()
        db.refresh(app)
        
        return {
            "id": app.id,
            "name": app.name,
            "type": app.type,
            "status": app.status,
            "created_at": app.created_at.isoformat() if app.created_at else None
        }
    except Exception as e:
        logger.error(f"Error creating application: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# v2 Workflow Run API Endpoints (Req 4.1, 5.1, 5.3, 5.7, 14.3, 19.1, 19.3, 19.4)
# ============================================================================


@router.post("/workflow/run")
async def run_workflow_v2(
    request: EnhancedGoldenPathRunRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start a v2 workflow run with execution_mode support (Req 4.1, 5.1, 14.3, 19.1).

    Creates a WorkflowRun record, logs an audit event, and returns a run_id
    immediately. The actual orchestration is kicked off asynchronously.
    """
    run_id = str(uuid.uuid4())
    now = datetime.utcnow()

    workflow_run = WorkflowRun(
        id=run_id,
        tenant_id=user.tenant_id,
        project_id=request.options.get("project_id"),
        status="pending",
        current_stage="policy_resolution",
        execution_mode=request.execution_mode.value,
        approval_required=request.execution_mode == ExecutionMode.COPILOT,
        initiated_by=user.id,
        state_snapshot={
            "idea": request.idea,
            "execution_mode": request.execution_mode.value,
        },
        created_at=now,
        updated_at=now,
    )
    db.add(workflow_run)
    db.commit()

    # Audit trail (Req 20.3)
    log_audit_event(
        db=db,
        tenant_id=user.tenant_id,
        user_id=user.id,
        action_type=WORKFLOW_STARTED,
        resource_type="workflow_run",
        resource_id=run_id,
        details={
            "execution_mode": request.execution_mode.value,
            "idea": request.idea,
        },
    )

    return {
        "run_id": run_id,
        "status": "pending",
        "execution_mode": request.execution_mode.value,
        "message": "Workflow run created. Use GET /workflow/runs/{run_id} to poll status.",
    }


@router.get("/workflow/runs/{run_id}")
async def get_workflow_run_v2(
    run_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get run status, timeline, and current stage (Req 19.3).

    Returns the WorkflowRun metadata plus a timeline built from
    StageExecution records.
    """
    workflow_run = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
    if not workflow_run:
        raise HTTPException(status_code=404, detail="Workflow run not found")

    verify_tenant_access(workflow_run, user.tenant_id)

    # Build timeline from StageExecution records
    stages = (
        db.query(StageExecution)
        .filter(StageExecution.workflow_run_id == run_id)
        .order_by(StageExecution.created_at)
        .all()
    )

    # Fetch pending approval for this run (if any)
    pending_approval = (
        db.query(Approval)
        .filter(
            Approval.workflow_run_id == run_id,
            Approval.status == "pending",
        )
        .first()
    )

    timeline = []
    for se in stages:
        entry: dict = {
            "stage_name": se.stage_name,
            "status": se.status,
            "started_at": se.started_at.isoformat() if se.started_at else None,
            "completed_at": se.completed_at.isoformat() if se.completed_at else None,
            "output_summary": se.output_summary,
            "validation_result": se.validation_result,
            "error": se.error,
        }
        # Attach pending approval info to the stage that is awaiting approval
        if (
            se.status == "awaiting_approval"
            and pending_approval
            and pending_approval.step_name == se.stage_name
        ):
            entry["pending_approval"] = {
                "approval_id": pending_approval.id,
                "stage_name": pending_approval.step_name,
            }
        timeline.append(entry)

    return {
        "run_id": workflow_run.id,
        "status": workflow_run.status,
        "current_stage": workflow_run.current_stage,
        "execution_mode": workflow_run.execution_mode,
        "approval_required": workflow_run.approval_required,
        "deployment_url": workflow_run.deployment_url,
        "error": workflow_run.error,
        "timeline": timeline,
        "created_at": workflow_run.created_at.isoformat() if workflow_run.created_at else None,
        "updated_at": workflow_run.updated_at.isoformat() if workflow_run.updated_at else None,
    }


@router.post("/workflow/runs/{run_id}/approve")
async def approve_workflow_stage(
    run_id: str,
    decision: ApprovalDecision,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Submit an approval decision for the current stage (Req 5.3, 9.1, 9.2)."""
    workflow_run = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
    if not workflow_run:
        raise HTTPException(status_code=404, detail="Workflow run not found")

    verify_tenant_access(workflow_run, user.tenant_id)

    if workflow_run.execution_mode != "copilot":
        raise HTTPException(
            status_code=400,
            detail="Approval is only available in Copilot mode",
        )

    # Look up the pending approval record
    approval = (
        db.query(Approval)
        .filter(
            Approval.id == decision.approval_id,
            Approval.workflow_run_id == run_id,
            Approval.status == "pending",
        )
        .first()
    )
    if not approval:
        raise HTTPException(status_code=404, detail="Pending approval not found")

    verify_tenant_access(approval, user.tenant_id)

    # Record the decision
    approval.decision = decision.decision
    approval.approved_by = user.id
    approval.approved_at = datetime.utcnow()
    approval.comments = decision.comments
    approval.status = decision.decision  # "approved" or "rejected"
    if decision.edited_output:
        approval.edited_output = decision.edited_output
    if decision.decision == "rejected" and decision.comments:
        approval.feedback = decision.comments

    db.commit()

    # Audit trail (Req 20.2)
    audit_action = APPROVAL_APPROVED if decision.decision == "approved" else APPROVAL_REJECTED
    log_audit_event(
        db=db,
        tenant_id=user.tenant_id,
        user_id=user.id,
        action_type=audit_action,
        resource_type="approval",
        resource_id=approval.id,
        details={
            "workflow_run_id": run_id,
            "stage": approval.step_name,
            "decision": decision.decision,
            "comments": decision.comments,
        },
    )

    return {
        "approval_id": approval.id,
        "decision": decision.decision,
        "stage": approval.step_name,
        "message": f"Stage {approval.step_name} {decision.decision}.",
    }


@router.post("/workflow/runs/{run_id}/switch-mode")
async def switch_execution_mode(
    run_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Switch from Copilot to Autopilot mid-run (Req 5.7)."""
    workflow_run = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
    if not workflow_run:
        raise HTTPException(status_code=404, detail="Workflow run not found")

    verify_tenant_access(workflow_run, user.tenant_id)

    if workflow_run.execution_mode != "copilot":
        raise HTTPException(
            status_code=400,
            detail="Can only switch from Copilot to Autopilot",
        )

    if workflow_run.status in ("completed", "failed", "cancelled"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot switch mode on a {workflow_run.status} run",
        )

    workflow_run.execution_mode = "autopilot"
    workflow_run.approval_required = False
    workflow_run.updated_at = datetime.utcnow()
    db.commit()

    log_audit_event(
        db=db,
        tenant_id=user.tenant_id,
        user_id=user.id,
        action_type="execution_mode_switched",
        resource_type="workflow_run",
        resource_id=run_id,
        details={"from": "copilot", "to": "autopilot"},
    )

    return {
        "run_id": run_id,
        "execution_mode": "autopilot",
        "message": "Switched to Autopilot. Remaining stages will proceed without approval.",
    }


@router.post("/workflow/runs/{run_id}/cancel")
async def cancel_workflow_run(
    run_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Cancel a running workflow (Req 19.4)."""
    workflow_run = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
    if not workflow_run:
        raise HTTPException(status_code=404, detail="Workflow run not found")

    verify_tenant_access(workflow_run, user.tenant_id)

    if workflow_run.status in ("completed", "failed", "cancelled"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel a {workflow_run.status} run",
        )

    cancelled = WorkflowOrchestrator.cancel_workflow(run_id)
    if not cancelled:
        raise HTTPException(status_code=500, detail="Failed to cancel workflow run")

    log_audit_event(
        db=db,
        tenant_id=user.tenant_id,
        user_id=user.id,
        action_type="workflow_cancelled",
        resource_type="workflow_run",
        resource_id=run_id,
        details={"cancelled_at_stage": workflow_run.current_stage},
    )

    return {
        "run_id": run_id,
        "status": "cancelled",
        "message": "Workflow run cancelled. It will stop after the current stage completes.",
    }


@router.get("/workflow/runs/{run_id}/logs")
async def stream_workflow_logs(
    run_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Stream execution logs via SSE (Req 16.1, 16.2).

    Returns a text/event-stream response. Each event is a JSON-encoded
    ExecutionLog entry. The stream polls for new log entries every 2 seconds
    and terminates when the workflow run reaches a terminal status.
    """
    workflow_run = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
    if not workflow_run:
        raise HTTPException(status_code=404, detail="Workflow run not found")

    verify_tenant_access(workflow_run, user.tenant_id)

    async def _event_generator():
        """Yield SSE events for new execution log entries."""
        last_seen_id: Optional[str] = None
        terminal_statuses = {"completed", "failed", "cancelled"}

        while True:
            # Open a fresh session for each poll cycle
            poll_db = next(get_db())
            try:
                query = (
                    poll_db.query(ExecutionLog)
                    .filter(ExecutionLog.workflow_run_id == run_id)
                    .order_by(ExecutionLog.created_at)
                )
                if last_seen_id:
                    # Fetch only logs created after the last one we sent
                    last_log = poll_db.query(ExecutionLog).filter(ExecutionLog.id == last_seen_id).first()
                    if last_log and last_log.created_at:
                        query = query.filter(ExecutionLog.created_at > last_log.created_at)

                logs = query.all()
                for log_entry in logs:
                    data = json.dumps({
                        "id": log_entry.id,
                        "stage_name": log_entry.stage_name,
                        "log_level": log_entry.log_level,
                        "message": log_entry.message,
                        "metadata": log_entry.metadata_,
                        "created_at": log_entry.created_at.isoformat() if log_entry.created_at else None,
                    })
                    yield f"data: {data}\n\n"
                    last_seen_id = log_entry.id

                # Check if the run has finished
                run = poll_db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
                if run and run.status in terminal_statuses:
                    yield f"data: {json.dumps({'event': 'done', 'status': run.status})}\n\n"
                    return
            finally:
                poll_db.close()

            await asyncio.sleep(2)

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
