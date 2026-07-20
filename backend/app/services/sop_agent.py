"""SOP Agent for validating artifacts against SOPs"""
from typing import List, Dict, Any, Optional
from app.core.models import (
    SOPValidationRequest, SOPValidationResponse, Violation,
    ArtifactType, SOP
)
from app.services.sop_service import sop_service
from app.core.llm_client import get_llm_client
from app.core.logger import logger


class SOPAgent:
    """Agent that validates artifacts against applicable SOPs"""
    
    def __init__(self):
        self.llm_client = get_llm_client()
    
    def _determine_applicable_sops(
        self,
        artifact_type: ArtifactType,
        context: Dict[str, Any]
    ) -> List[SOP]:
        """Determine which SOPs apply to the artifact"""
        # Filter by artifact type
        applicable = sop_service.filter_sops(applies_to=artifact_type)
        
        # Further filter by context (stack, environment, tags)
        stack = context.get("stack")
        environment = context.get("environment")
        tags = context.get("tags", [])
        
        if stack or environment or tags:
            filtered = []
            for sop in applicable:
                # Check if SOP tags match context tags
                if tags and any(tag in sop.tags for tag in tags):
                    filtered.append(sop)
                # Check if context matches SOP requirements
                elif not tags:  # If no specific tags, include all applicable
                    filtered.append(sop)
            applicable = filtered
        
        return applicable
    
    async def _check_pattern(self, sop: SOP, check: Dict[str, Any], content: str) -> Optional[Violation]:
        """Check pattern-based validation"""
        pattern = check.get("pattern", "")
        if not pattern:
            return None
        
        # Simple pattern matching (can be enhanced with regex)
        if pattern.lower() in content.lower():
            return None  # Pattern found, no violation
        
        return Violation(
            sop_id=sop.id,
            sop_title=sop.title,
            check_type="pattern",
            description=f"Required pattern '{pattern}' not found in artifact",
            remediation_hint=sop.remediation_hints.get("pattern", "Add the required pattern")
        )
    
    async def _check_questionnaire(
        self,
        sop: SOP,
        check: Dict[str, Any],
        content: str
    ) -> Optional[Violation]:
        """Check questionnaire-based validation using LLM"""
        questions = check.get("questions", [])
        if not questions:
            return None
        
        # Use LLM to answer questions about the artifact
        prompt = f"""Review the following artifact and answer these questions:

Artifact:
{content}

Questions:
{chr(10).join(f"- {q}" for q in questions)}

For each question, answer Yes or No, and provide a brief explanation.
"""
        
        try:
            response = await self.llm_client.generate(
                prompt,
                system_prompt="You are a quality assurance agent reviewing artifacts against standards."
            )
            
            # Check if all questions are answered positively
            # Simple heuristic: if response contains "no" or "missing", likely violation
            if "no" in response.lower() or "missing" in response.lower():
                return Violation(
                    sop_id=sop.id,
                    sop_title=sop.title,
                    check_type="questionnaire",
                    description=f"Questionnaire check failed: {response[:200]}",
                    remediation_hint=sop.remediation_hints.get("questionnaire", "Address the questions raised")
                )
        except Exception as e:
            logger.error(f"Error in questionnaire check: {e}")
            return None
        
        return None
    
    async def _check_metric(
        self,
        sop: SOP,
        check: Dict[str, Any],
        content: str
    ) -> Optional[Violation]:
        """Check metric-based validation"""
        metric_name = check.get("metric_name")
        threshold = check.get("threshold")
        
        if not metric_name or threshold is None:
            return None
        
        # Simple metric extraction (can be enhanced)
        # For now, use LLM to extract metric
        prompt = f"""Extract the metric '{metric_name}' from the following artifact:

Artifact:
{content}

Return only the numeric value of {metric_name}, or 'not found' if it cannot be determined.
"""
        
        try:
            response = await self.llm_client.generate(prompt)
            # Try to extract numeric value
            import re
            numbers = re.findall(r'\d+\.?\d*', response)
            if numbers:
                value = float(numbers[0])
                if value < threshold:
                    return Violation(
                        sop_id=sop.id,
                        sop_title=sop.title,
                        check_type="metric",
                        description=f"Metric {metric_name} ({value}) below threshold ({threshold})",
                        remediation_hint=sop.remediation_hints.get("metric", f"Increase {metric_name} to at least {threshold}")
                    )
        except Exception as e:
            logger.error(f"Error in metric check: {e}")
        
        return None
    
    async def validate(self, request: SOPValidationRequest) -> SOPValidationResponse:
        """Validate an artifact against applicable SOPs"""
        violations = []
        applicable_sops = self._determine_applicable_sops(
            request.artifact_type,
            request.context
        )
        
        for sop in applicable_sops:
            for check in sop.checks:
                violation = None
                
                if check.type == "pattern":
                    violation = await self._check_pattern(sop, check.dict(), request.artifact_content)
                elif check.type == "questionnaire":
                    violation = await self._check_questionnaire(sop, check.dict(), request.artifact_content)
                elif check.type == "metric":
                    violation = await self._check_metric(sop, check.dict(), request.artifact_content)
                
                if violation:
                    violations.append(violation)
        
        return SOPValidationResponse(
            valid=len(violations) == 0,
            violations=violations,
            applicable_sops=[sop.id for sop in applicable_sops]
        )


# Global instance
sop_agent = SOPAgent()

