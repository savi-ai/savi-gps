"""Story Review Agent - reviews stories and calls SOP Agent"""
from typing import Dict, Any
from app.services.agents.base_agent import BaseAgent
from app.services.sop_agent import sop_agent
from app.core.models import ArtifactType, SOPValidationRequest
from app.core.logger import logger
import json


class StoryReviewAgent(BaseAgent):
    """Agent that reviews stories for quality and SOP compliance"""
    
    SYSTEM_PROMPT = """You are a Story Review Agent that ensures stories meet quality standards.

Your responsibilities:
1. Check for duplicate stories
2. Ensure clarity and completeness
3. Verify coverage of acceptance criteria
4. Identify missing NFRs

Output your review as JSON with:
- approved_stories: List of approved story indices
- needs_changes: List of stories that need changes with reasons
- quality_issues: List of quality issues found
"""
    
    async def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Review stories and validate against SOPs"""
        stories = state.get("stories", [])
        
        if not stories:
            logger.warning("No stories provided to StoryReviewAgent")
            return state
        
        # Basic quality review using LLM
        prompt = f"""Review the following user stories for quality:

Stories: {json.dumps(stories, indent=2)}

Check for:
1. Duplicates
2. Clarity
3. Completeness
4. Coverage
"""
        
        try:
            review_response = await self.llm_client.generate(
                prompt,
                system_prompt=self.SYSTEM_PROMPT
            )
            
            # Parse review
            review_result = {}
            try:
                review_result = json.loads(review_response)
            except json.JSONDecodeError:
                logger.warning("StoryReviewAgent review response not in JSON format")
            
            # Validate each story against SOPs
            for idx, story in enumerate(stories):
                validation_request = SOPValidationRequest(
                    artifact_type=ArtifactType.STORY,
                    context={"stack": state.get("stack"), "environment": state.get("environment")},
                    artifact_content=json.dumps(story)
                )
                
                validation_result = await sop_agent.validate(validation_request)
                
                # Update story status based on validation
                if validation_result.valid and idx in review_result.get("approved_stories", []):
                    stories[idx]["status"] = "approved"
                else:
                    stories[idx]["status"] = "needs_changes"
                    if validation_result.violations:
                        stories[idx]["sop_violations"] = [v.dict() for v in validation_result.violations]
                
                # Inject NFRs from SOP violations
                if validation_result.violations:
                    nfrs = stories[idx].get("nfrs", [])
                    for violation in validation_result.violations:
                        if violation.remediation_hint:
                            nfrs.append(f"SOP {violation.sop_id}: {violation.remediation_hint}")
                    stories[idx]["nfrs"] = nfrs
            
            state["stories"] = stories
            state["story_review"] = review_result
            logger.info(f"StoryReviewAgent reviewed {len(stories)} stories")
            
        except Exception as e:
            logger.error(f"Error in StoryReviewAgent: {e}")
            state["error"] = str(e)
        
        return state

