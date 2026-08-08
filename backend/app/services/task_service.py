"""Task Service for managing background tasks"""
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from app.core.database import Task
from app.core.logger import logger
from datetime import datetime
import uuid
import json


class TaskStatus:
    """Task status constants"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskType:
    """Task type constants"""
    GENERATE_FEATURES = "generate_features"
    GENERATE_STORIES = "generate_stories"
    GENERATE_ARCHITECTURE = "generate_architecture"
    GENERATE_CODE = "generate_code"
    GENERATE_TESTS = "generate_tests"


class TaskService:
    """Service for managing background tasks"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create_task(
        self,
        project_id: str,
        task_type: str,
        input_data: Dict[str, Any],
        user_id: str
    ) -> Task:
        """
        Create a new background task
        
        Args:
            project_id: ID of the project
            task_type: Type of task (from TaskType constants)
            input_data: Input parameters for the task
            user_id: ID of the user creating the task
            
        Returns:
            Created Task object
        """
        try:
            task = Task(
                id=str(uuid.uuid4()),
                project_id=project_id,
                task_type=task_type,
                status=TaskStatus.PENDING,
                progress=0,
                input_data=json.dumps(input_data) if input_data else None,
                created_by=user_id,
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            
            self.db.add(task)
            self.db.commit()
            self.db.refresh(task)
            
            logger.info(f"Created task {task.id} of type {task_type} for project {project_id}")

            from app.services.savi_job_queue import arq_enabled, schedule_build_task

            if arq_enabled():
                schedule_build_task(task.id)

            return task
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error creating task: {e}")
            raise
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """
        Get task by ID
        
        Args:
            task_id: ID of the task
            
        Returns:
            Task object or None if not found
        """
        try:
            task = self.db.query(Task).filter(Task.id == task_id).first()
            return task
        except Exception as e:
            logger.error(f"Error getting task {task_id}: {e}")
            raise
    
    def update_task_status(
        self,
        task_id: str,
        status: str,
        progress: int = None,
        result: Dict[str, Any] = None,
        error: str = None
    ) -> Task:
        """
        Update task status and progress
        
        Args:
            task_id: ID of the task
            status: New status (from TaskStatus constants)
            progress: Progress percentage (0-100)
            result: Task result data
            error: Error message if failed
            
        Returns:
            Updated Task object
        """
        try:
            task = self.get_task(task_id)
            if not task:
                raise ValueError(f"Task {task_id} not found")
            
            task.status = status
            task.updated_at = datetime.now()
            
            if progress is not None:
                task.progress = max(0, min(100, progress))  # Clamp to 0-100
            
            if result is not None:
                task.result = json.dumps(result)
            
            if error is not None:
                task.error = error
            
            # Set timestamps based on status
            if status == TaskStatus.RUNNING and not task.started_at:
                task.started_at = datetime.now()
            
            if status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
                task.completed_at = datetime.now()
                if status == TaskStatus.COMPLETED:
                    task.progress = 100
            
            self.db.commit()
            self.db.refresh(task)
            
            logger.info(f"Updated task {task_id} to status {status} (progress: {task.progress}%)")
            return task
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error updating task {task_id}: {e}")
            raise
    
    def get_project_tasks(
        self,
        project_id: str,
        task_type: str = None,
        status: str = None
    ) -> List[Task]:
        """
        Get all tasks for a project
        
        Args:
            project_id: ID of the project
            task_type: Optional filter by task type
            status: Optional filter by status
            
        Returns:
            List of Task objects
        """
        try:
            query = self.db.query(Task).filter(Task.project_id == project_id)
            
            if task_type:
                query = query.filter(Task.task_type == task_type)
            
            if status:
                query = query.filter(Task.status == status)
            
            tasks = query.order_by(Task.created_at.desc()).all()
            return tasks
            
        except Exception as e:
            logger.error(f"Error getting tasks for project {project_id}: {e}")
            raise
    
    def get_pending_tasks(self, limit: int = 10) -> List[Task]:
        """
        Get pending tasks for processing
        
        Args:
            limit: Maximum number of tasks to return
            
        Returns:
            List of pending Task objects
        """
        try:
            tasks = (
                self.db.query(Task)
                .filter(Task.status == TaskStatus.PENDING)
                .order_by(Task.created_at.asc())
                .limit(limit)
                .all()
            )
            return tasks
        except Exception as e:
            logger.error(f"Error getting pending tasks: {e}")
            raise
    
    def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a running or pending task
        
        Args:
            task_id: ID of the task
            
        Returns:
            True if cancelled, False if task cannot be cancelled
        """
        try:
            task = self.get_task(task_id)
            if not task:
                raise ValueError(f"Task {task_id} not found")
            
            # Can only cancel pending or running tasks
            if task.status not in [TaskStatus.PENDING, TaskStatus.RUNNING]:
                logger.warning(f"Cannot cancel task {task_id} with status {task.status}")
                return False
            
            task.status = TaskStatus.CANCELLED
            task.completed_at = datetime.now()
            task.updated_at = datetime.now()
            
            self.db.commit()
            
            logger.info(f"Cancelled task {task_id}")
            return True
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error cancelling task {task_id}: {e}")
            raise
    
    def cleanup_old_tasks(self, days: int = 30) -> int:
        """
        Clean up completed tasks older than specified days
        
        Args:
            days: Number of days to keep completed tasks
            
        Returns:
            Number of tasks deleted
        """
        try:
            from datetime import timedelta
            cutoff_date = datetime.now() - timedelta(days=days)
            
            deleted = (
                self.db.query(Task)
                .filter(
                    Task.status.in_([TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]),
                    Task.completed_at < cutoff_date
                )
                .delete(synchronize_session=False)
            )
            
            self.db.commit()
            
            if deleted > 0:
                logger.info(f"Cleaned up {deleted} old tasks")
            
            return deleted
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error cleaning up old tasks: {e}")
            raise
    
    def get_task_result(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Get task result as dictionary
        
        Args:
            task_id: ID of the task
            
        Returns:
            Task result dictionary or None
        """
        try:
            task = self.get_task(task_id)
            if not task or not task.result:
                return None
            
            return json.loads(task.result)
            
        except Exception as e:
            logger.error(f"Error getting task result for {task_id}: {e}")
            return None
    
    def get_task_input(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Get task input data as dictionary
        
        Args:
            task_id: ID of the task
            
        Returns:
            Task input dictionary or None
        """
        try:
            task = self.get_task(task_id)
            if not task or not task.input_data:
                return None
            
            return json.loads(task.input_data)
            
        except Exception as e:
            logger.error(f"Error getting task input for {task_id}: {e}")
            return None
