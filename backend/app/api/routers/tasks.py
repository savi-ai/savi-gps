"""Task API endpoints"""
from fastapi import APIRouter, HTTPException, Depends, Security
from sqlalchemy.orm import Session
from typing import Optional, List
from pydantic import BaseModel
from app.core.database import get_db, User
from app.core.auth import get_current_user, require_permission
from app.services.task_service import TaskService, TaskStatus, TaskType
from app.core.logger import logger
from datetime import datetime

router = APIRouter(prefix="/tasks", tags=["Tasks"])


class TaskCreateRequest(BaseModel):
    """Request model for creating a task"""
    project_id: str
    task_type: str
    input_data: dict


class TaskResponse(BaseModel):
    """Response model for task"""
    id: str
    project_id: str
    task_type: str
    status: str
    progress: int
    result: Optional[dict] = None
    error: Optional[str] = None
    created_by: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


@router.post("", response_model=TaskResponse)
async def create_task(
    request: TaskCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new background task
    
    Requires: project:write permission
    """
    try:
        # Check permission
        require_permission(current_user, "project:write")
        
        # Validate task type
        valid_types = [
            TaskType.GENERATE_FEATURES,
            TaskType.GENERATE_STORIES,
            TaskType.GENERATE_ARCHITECTURE,
            TaskType.GENERATE_CODE,
            TaskType.GENERATE_TESTS
        ]
        if request.task_type not in valid_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid task type. Must be one of: {', '.join(valid_types)}"
            )
        
        # Create task
        task_service = TaskService(db)
        task = task_service.create_task(
            project_id=request.project_id,
            task_type=request.task_type,
            input_data=request.input_data,
            user_id=current_user.id
        )
        
        # Convert to response
        return TaskResponse(
            id=task.id,
            project_id=task.project_id,
            task_type=task.task_type,
            status=task.status,
            progress=task.progress,
            result=task_service.get_task_result(task.id),
            error=task.error,
            created_by=task.created_by,
            started_at=task.started_at,
            completed_at=task.completed_at,
            created_at=task.created_at,
            updated_at=task.updated_at
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get task status and result
    
    Requires: project:read permission
    """
    try:
        # Check permission
        require_permission(current_user, "project:read")
        
        # Get task
        task_service = TaskService(db)
        task = task_service.get_task(task_id)
        
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        # Convert to response
        return TaskResponse(
            id=task.id,
            project_id=task.project_id,
            task_type=task.task_type,
            status=task.status,
            progress=task.progress,
            result=task_service.get_task_result(task.id),
            error=task.error,
            created_by=task.created_by,
            started_at=task.started_at,
            completed_at=task.completed_at,
            created_at=task.created_at,
            updated_at=task.updated_at
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{project_id}/tasks", response_model=List[TaskResponse])
async def get_project_tasks(
    project_id: str,
    task_type: Optional[str] = None,
    status: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all tasks for a project
    
    Requires: project:read permission
    """
    try:
        # Check permission
        require_permission(current_user, "project:read")
        
        # Get tasks
        task_service = TaskService(db)
        tasks = task_service.get_project_tasks(
            project_id=project_id,
            task_type=task_type,
            status=status
        )
        
        # Convert to response
        return [
            TaskResponse(
                id=task.id,
                project_id=task.project_id,
                task_type=task.task_type,
                status=task.status,
                progress=task.progress,
                result=task_service.get_task_result(task.id),
                error=task.error,
                created_by=task.created_by,
                started_at=task.started_at,
                completed_at=task.completed_at,
                created_at=task.created_at,
                updated_at=task.updated_at
            )
            for task in tasks
        ]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting tasks for project {project_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{task_id}")
async def cancel_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Cancel a pending or running task
    
    Requires: project:write permission
    """
    try:
        # Check permission
        require_permission(current_user, "project:write")
        
        # Cancel task
        task_service = TaskService(db)
        cancelled = task_service.cancel_task(task_id)
        
        if not cancelled:
            raise HTTPException(
                status_code=400,
                detail="Task cannot be cancelled (already completed, failed, or cancelled)"
            )
        
        return {"message": "Task cancelled successfully", "task_id": task_id}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
