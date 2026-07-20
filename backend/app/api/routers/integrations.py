"""External integration stubs (Jira / Confluence / Harness / GitHub create-repo).

These endpoints are **not** production connectors. When the feature flag is off they
return an explicit mock payload; when on they return HTTP 501 until implemented.
GitHub Intelligence import/index uses a separate router (`github_intelligence`).
"""
from fastapi import APIRouter, HTTPException, Security
from app.core.config import settings
from app.core.auth import verify_api_key
from app.core.logger import logger
from typing import Dict, Any, Optional

router = APIRouter(
    prefix="/integrations",
    tags=["Integrations (stubs)"],
)


@router.post("/jira/features")
async def create_jira_feature(
    feature: Dict[str, Any],
    api_key: bool = Security(verify_api_key)
):
    """Create feature in Jira (stubbed)"""
    if not settings.JIRA_ENABLED:
        logger.info("Jira integration disabled, returning mock response")
        return {
            "id": "MOCK-JIRA-001",
            "key": "FEAT-001",
            "status": "created",
            "message": "Jira integration is disabled (stubbed)"
        }
    
    # TODO: Implement actual Jira API call
    raise HTTPException(status_code=501, detail="Jira integration not yet implemented")


@router.post("/jira/stories")
async def create_jira_story(
    story: Dict[str, Any],
    api_key: bool = Security(verify_api_key)
):
    """Create story in Jira (stubbed)"""
    if not settings.JIRA_ENABLED:
        logger.info("Jira integration disabled, returning mock response")
        return {
            "id": "MOCK-JIRA-002",
            "key": "STORY-001",
            "status": "created",
            "message": "Jira integration is disabled (stubbed)"
        }
    
    # TODO: Implement actual Jira API call
    raise HTTPException(status_code=501, detail="Jira integration not yet implemented")


@router.post("/confluence/publish")
async def publish_to_confluence(
    document: Dict[str, Any],
    api_key: bool = Security(verify_api_key)
):
    """Publish document to Confluence (stubbed)"""
    if not settings.CONFLUENCE_ENABLED:
        logger.info("Confluence integration disabled, returning mock response")
        return {
            "id": "MOCK-CONF-001",
            "url": "https://confluence.example.com/space/MOCK-CONF-001",
            "status": "published",
            "message": "Confluence integration is disabled (stubbed)"
        }
    
    # TODO: Implement actual Confluence API call
    raise HTTPException(status_code=501, detail="Confluence integration not yet implemented")


@router.post("/github/create-repo")
async def create_github_repo(
    repo_config: Dict[str, Any],
    api_key: bool = Security(verify_api_key)
):
    """Create GitHub repository from template (stubbed)"""
    if not settings.GITHUB_ENABLED:
        logger.info("GitHub integration disabled, returning mock response")
        return {
            "id": "MOCK-GH-001",
            "name": repo_config.get("name", "mock-repo"),
            "url": "https://github.com/org/mock-repo",
            "status": "created",
            "message": "GitHub integration is disabled (stubbed)"
        }
    
    # TODO: Implement actual GitHub API call
    raise HTTPException(status_code=501, detail="GitHub integration not yet implemented")


@router.post("/harness/create-pipeline")
async def create_harness_pipeline(
    pipeline_config: Dict[str, Any],
    api_key: bool = Security(verify_api_key)
):
    """Create Harness pipeline (stubbed)"""
    if not settings.HARNESS_ENABLED:
        logger.info("Harness integration disabled, returning mock response")
        return {
            "id": "MOCK-HARNESS-001",
            "name": pipeline_config.get("name", "mock-pipeline"),
            "status": "created",
            "message": "Harness integration is disabled (stubbed)"
        }
    
    # TODO: Implement actual Harness API call
    raise HTTPException(status_code=501, detail="Harness integration not yet implemented")

