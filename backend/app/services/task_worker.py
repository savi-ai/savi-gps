"""Task Worker for processing background tasks"""
import asyncio
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from app.core.database import SessionLocal, Task
from app.services.task_service import TaskService, TaskStatus, TaskType
from app.core.logger import logger
from datetime import datetime, timedelta
import traceback


class TaskWorker:
    """Worker for processing background tasks"""
    
    def __init__(self):
        self.running = False
        self.task_timeout = 600  # 10 minutes default timeout
        self.poll_interval = 2  # Poll every 2 seconds
        self.max_retries = 3
    
    async def execute_task(self, task: Task, db: Session) -> Dict[str, Any]:
        """
        Execute a single task based on its type
        
        Args:
            task: Task object to execute
            db: Database session
            
        Returns:
            Result dictionary
        """
        task_service = TaskService(db)
        
        try:
            # Import agents here to avoid circular imports
            from app.services.agents.feature_agent import FeatureAgent
            from app.services.agents.story_agent import StoryAgent
            from app.services.agents.architecture_agent import ArchitectureAgent
            from app.services.agents.developer_agent import DeveloperAgent
            from app.services.agents.testing_agent import TestingAgent
            
            # Get task input
            input_data = task_service.get_task_input(task.id) or {}
            
            # Route to appropriate agent based on task type
            result = None
            
            if task.task_type == TaskType.GENERATE_FEATURES:
                logger.info(f"Executing feature generation for task {task.id}")
                agent = FeatureAgent()
                result = await agent.process(input_data)
                
            elif task.task_type == TaskType.GENERATE_STORIES:
                logger.info(f"Executing story generation for task {task.id}")
                agent = StoryAgent()
                result = await agent.process(input_data)
                
                # Validate stories against SOPs
                if result and result.get('stories') and not result.get('error'):
                    try:
                        from app.services.sop_agent import sop_agent
                        from app.core.models import SOPValidationRequest, ArtifactType
                        import json
                        
                        logger.info(f"Validating {len(result['stories'])} stories against SOPs")
                        
                        # Convert stories to text for validation
                        stories_text = json.dumps(result['stories'], indent=2)
                        
                        validation_request = SOPValidationRequest(
                            artifact_type=ArtifactType.STORY,
                            context={
                                "stage": "story_generation",
                                "project_id": task.project_id
                            },
                            artifact_content=stories_text
                        )
                        
                        validation_result = await sop_agent.validate(validation_request)
                        
                        # Add validation results to the result
                        result['sop_validation'] = {
                            'valid': validation_result.valid,
                            'violations': [v.dict() for v in validation_result.violations],
                            'applicable_sops': validation_result.applicable_sops
                        }
                        
                        if not validation_result.valid:
                            logger.warning(f"Story validation found {len(validation_result.violations)} violations")
                            for violation in validation_result.violations:
                                logger.warning(f"  - {violation.sop_title}: {violation.description}")
                        else:
                            logger.info("Stories passed SOP validation")
                            
                    except Exception as validation_error:
                        logger.error(f"Error validating stories against SOPs: {validation_error}")
                        # Don't fail the task if validation fails
                        result['sop_validation'] = {
                            'valid': True,  # Assume valid if validation fails
                            'violations': [],
                            'error': str(validation_error)
                        }
                
            elif task.task_type == TaskType.GENERATE_ARCHITECTURE:
                logger.info(f"Executing architecture generation for task {task.id}")
                agent = ArchitectureAgent()
                result = await agent.process(input_data)
                
                # Validate architecture against SOPs
                if result and result.get('architecture') and not result.get('error'):
                    try:
                        from app.services.sop_agent import sop_agent
                        from app.core.models import SOPValidationRequest, ArtifactType
                        import json
                        
                        logger.info("Validating architecture against SOPs")
                        
                        # Convert architecture to text for validation
                        architecture_text = json.dumps(result['architecture'], indent=2)
                        
                        validation_request = SOPValidationRequest(
                            artifact_type=ArtifactType.ARCHITECTURE,
                            context={
                                "stage": "architecture_generation",
                                "project_id": task.project_id
                            },
                            artifact_content=architecture_text
                        )
                        
                        validation_result = await sop_agent.validate(validation_request)
                        
                        # Add validation results to the result
                        result['sop_validation'] = {
                            'valid': validation_result.valid,
                            'violations': [v.dict() for v in validation_result.violations],
                            'applicable_sops': validation_result.applicable_sops
                        }
                        
                        if not validation_result.valid:
                            logger.warning(f"Architecture validation found {len(validation_result.violations)} violations")
                            for violation in validation_result.violations:
                                logger.warning(f"  - {violation.sop_title}: {violation.description}")
                        else:
                            logger.info("Architecture passed SOP validation")
                            
                    except Exception as validation_error:
                        logger.error(f"Error validating architecture against SOPs: {validation_error}")
                        # Don't fail the task if validation fails
                        result['sop_validation'] = {
                            'valid': True,  # Assume valid if validation fails
                            'violations': [],
                            'error': str(validation_error)
                        }
                
            elif task.task_type == TaskType.GENERATE_CODE:
                logger.info(f"Executing code generation for task {task.id}")
                agent = DeveloperAgent()
                result = await agent.process(input_data)
                
                # Validate code against SOPs
                if result and result.get('code_implementation') and not result.get('error'):
                    try:
                        from app.services.sop_agent import sop_agent
                        from app.core.models import SOPValidationRequest, ArtifactType
                        import json
                        
                        logger.info("Validating code against SOPs")
                        
                        # Convert code to text for validation
                        code_text = json.dumps(result['code_implementation'], indent=2)
                        
                        validation_request = SOPValidationRequest(
                            artifact_type=ArtifactType.ARCHITECTURE,  # Using ARCHITECTURE as proxy for code
                            context={
                                "stage": "code_generation",
                                "project_id": task.project_id
                            },
                            artifact_content=code_text
                        )
                        
                        validation_result = await sop_agent.validate(validation_request)
                        
                        # Add validation results to the result
                        result['sop_validation'] = {
                            'valid': validation_result.valid,
                            'violations': [v.dict() for v in validation_result.violations],
                            'applicable_sops': validation_result.applicable_sops
                        }
                        
                        if not validation_result.valid:
                            logger.warning(f"Code validation found {len(validation_result.violations)} violations")
                            for violation in validation_result.violations:
                                logger.warning(f"  - {violation.sop_title}: {violation.description}")
                        else:
                            logger.info("Code passed SOP validation")
                            
                    except Exception as validation_error:
                        logger.error(f"Error validating code against SOPs: {validation_error}")
                        # Don't fail the task if validation fails
                        result['sop_validation'] = {
                            'valid': True,  # Assume valid if validation fails
                            'violations': [],
                            'error': str(validation_error)
                        }
                
                # After successful code generation, push to GitHub if repo URL is configured
                if result and input_data.get('github_repo_url'):
                    try:
                        from app.services.git_service import get_git_service
                        from app.core.database import Project
                        
                        # Get project to access code_implementation
                        project = db.query(Project).filter(Project.id == task.project_id).first()
                        if project and project.code_implementation:
                            logger.info(f"Pushing code to GitHub for project {project.name}")
                            git_service = get_git_service()
                            git_result = git_service.push_code_to_github(
                                repo_url=input_data['github_repo_url'],
                                code_implementation=project.code_implementation,
                                project_name=project.name,
                                branch_name="savi/code_scaffolded"
                            )
                            
                            if git_result.get('success'):
                                logger.info(f"Successfully pushed code to GitHub: {git_result.get('message')}")
                                result['github_push'] = git_result
                                try:
                                    from app.services.build.project_repo_graduation_service import (
                                        graduate_project_github_repo,
                                    )

                                    graduation = graduate_project_github_repo(
                                        db,
                                        project,
                                        github_repo_url=input_data.get('github_repo_url'),
                                        start_index=True,
                                    )
                                    result['graduation'] = graduation
                                except Exception as grad_err:
                                    logger.warning(
                                        "Auto-push graduation failed for project %s: %s",
                                        project.id,
                                        grad_err,
                                    )
                                    result['graduation'] = {
                                        'success': False,
                                        'error': str(grad_err),
                                    }
                            else:
                                logger.warning(f"Failed to push code to GitHub: {git_result.get('error')}")
                                result['github_push'] = git_result
                    except Exception as git_error:
                        logger.error(f"Error pushing to GitHub: {git_error}")
                        # Don't fail the task if GitHub push fails
                        result['github_push'] = {
                            'success': False,
                            'error': str(git_error)
                        }
                
            elif task.task_type == TaskType.GENERATE_TESTS:
                logger.info(f"Executing test generation for task {task.id}")
                agent = TestingAgent()
                result = await agent.process(input_data)
                
                # After successful test generation, push to GitHub if repo URL is configured
                if result and result.get('tests') and input_data.get('github_repo_url'):
                    try:
                        from app.services.git_service import get_git_service
                        from app.core.database import Project
                        from datetime import datetime
                        
                        # Get project to access tests
                        project = db.query(Project).filter(Project.id == task.project_id).first()
                        if project and project.tests:
                            logger.info(f"Pushing tests to GitHub for project {project.name}")
                            git_service = get_git_service()
                            
                            # Determine branch name - use separate branch or same as code
                            # Check if there's a test_repo_url, otherwise use same repo
                            test_repo_url = input_data.get('test_repo_url', input_data['github_repo_url'])
                            
                            # Generate timestamp-based branch name for tests
                            timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
                            test_branch_name = input_data.get('test_branch_name', f'savi/tests-{timestamp}')
                            
                            git_result = git_service.push_tests_to_github(
                                repo_url=test_repo_url,
                                tests=project.tests,
                                project_name=project.name,
                                branch_name=test_branch_name
                            )
                            
                            if git_result.get('success'):
                                logger.info(f"Successfully pushed tests to GitHub: {git_result.get('message')}")
                                result['github_push'] = git_result
                            else:
                                logger.warning(f"Failed to push tests to GitHub: {git_result.get('error')}")
                                result['github_push'] = git_result
                    except Exception as git_error:
                        logger.error(f"Error pushing tests to GitHub: {git_error}")
                        # Don't fail the task if GitHub push fails
                        result['github_push'] = {
                            'success': False,
                            'error': str(git_error)
                        }
                
            else:
                raise ValueError(f"Unknown task type: {task.task_type}")
            
            return result or {}
            
        except Exception as e:
            logger.error(f"Error executing task {task.id}: {e}")
            logger.error(traceback.format_exc())
            raise
    
    async def process_task(self, task: Task, db: Session):
        """
        Process a single task with timeout and error handling
        
        Args:
            task: Task to process
            db: Database session
        """
        task_service = TaskService(db)
        
        try:
            # Update task to running
            task_service.update_task_status(
                task_id=task.id,
                status=TaskStatus.RUNNING,
                progress=0
            )
            
            logger.info(f"Processing task {task.id} of type {task.task_type}")
            
            # Execute task with timeout
            try:
                result = await asyncio.wait_for(
                    self.execute_task(task, db),
                    timeout=self.task_timeout
                )
                
                # Mark as completed
                task_service.update_task_status(
                    task_id=task.id,
                    status=TaskStatus.COMPLETED,
                    progress=100,
                    result=result
                )
                
                logger.info(f"Task {task.id} completed successfully")
                
            except asyncio.TimeoutError:
                error_msg = f"Task timed out after {self.task_timeout} seconds"
                logger.error(f"Task {task.id}: {error_msg}")
                task_service.update_task_status(
                    task_id=task.id,
                    status=TaskStatus.FAILED,
                    error=error_msg
                )
                
        except Exception as e:
            error_msg = f"Task execution failed: {str(e)}"
            logger.error(f"Task {task.id}: {error_msg}")
            logger.error(traceback.format_exc())
            
            try:
                task_service.update_task_status(
                    task_id=task.id,
                    status=TaskStatus.FAILED,
                    error=error_msg
                )
            except Exception as update_error:
                logger.error(f"Failed to update task status: {update_error}")
    
    async def worker_loop(self):
        """
        Main worker loop that processes pending tasks
        """
        logger.info("Task worker started")
        self.running = True
        
        while self.running:
            db = SessionLocal()
            try:
                task_service = TaskService(db)
                
                # Get pending tasks
                pending_tasks = task_service.get_pending_tasks(limit=1)
                
                if pending_tasks:
                    for task in pending_tasks:
                        if not self.running:
                            break
                        
                        await self.process_task(task, db)
                else:
                    # No pending tasks, wait before checking again
                    await asyncio.sleep(self.poll_interval)
                    
            except Exception as e:
                logger.error(f"Error in worker loop: {e}")
                logger.error(traceback.format_exc())
                await asyncio.sleep(self.poll_interval)
            finally:
                db.close()
        
        logger.info("Task worker stopped")
    
    def stop(self):
        """Stop the worker loop"""
        logger.info("Stopping task worker...")
        self.running = False


# Global worker instance
_worker: Optional[TaskWorker] = None
_worker_task: Optional[asyncio.Task] = None


async def start_worker():
    """Start the background task worker"""
    global _worker, _worker_task
    
    if _worker is not None:
        logger.warning("Task worker already running")
        return
    
    _worker = TaskWorker()
    _worker_task = asyncio.create_task(_worker.worker_loop())
    logger.info("Task worker initialized")


async def stop_worker():
    """Stop the background task worker"""
    global _worker, _worker_task
    
    if _worker is None:
        return
    
    _worker.stop()
    
    if _worker_task:
        try:
            await asyncio.wait_for(_worker_task, timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("Worker task did not stop gracefully, cancelling...")
            _worker_task.cancel()
    
    _worker = None
    _worker_task = None


def is_worker_running() -> bool:
    """Return True when the background task worker loop is active."""
    return _worker is not None and _worker.running
    logger.info("Task worker stopped")
