"""Stack Selector Agent - maps components to implementation stacks"""
from typing import Dict, Any, List
from app.core.models import StackSelection
from app.services.agents.base_agent import BaseAgent
from app.core.logger import logger
import json


class StackSelectorAgent(BaseAgent):
    """Agent that selects implementation stacks and blueprints"""
    
    SYSTEM_PROMPT = """You are a Stack Selector Agent that maps components to implementation stacks.

For each component, select:
- Implementation stack: Java/Spring Boot, Next.js/React, Nuxt/Vue, Python/FastAPI, etc.
- Infrastructure patterns: Approved AWS services (e.g., ECS Fargate, Lambda, RDS)
- Template ID: Reference to a Golden Path template catalog

Output as JSON array of stack selections.
"""
    
    async def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Select stacks for components"""
        architecture = state.get("architecture", {})
        components = architecture.get("components", [])
        
        if not components:
            logger.warning("No components provided to StackSelectorAgent")
            return state
        
        prompt = f"""Select implementation stacks for the following components:

Components: {json.dumps(components, indent=2)}

Map each component to:
- Implementation stack (Java/Spring Boot, Next.js/React, etc.)
- Infrastructure patterns (AWS services)
- Template ID from Golden Path catalog
"""
        
        try:
            response = await self.llm_client.generate(
                prompt,
                system_prompt=self.SYSTEM_PROMPT
            )
            
            # Parse stack selections
            stack_selections = []
            try:
                parsed = json.loads(response)
                if isinstance(parsed, list):
                    for s in parsed:
                        stack_selections.append(StackSelection(**s))
                elif isinstance(parsed, dict) and "selections" in parsed:
                    for s in parsed["selections"]:
                        stack_selections.append(StackSelection(**s))
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning(f"Could not parse StackSelectorAgent response: {e}")
                # Create default selections
                for comp in components:
                    stack_selections.append(StackSelection(
                        component_name=comp.get("name", "Unknown"),
                        implementation_stack="Java/Spring Boot",
                        infra_patterns=["ECS Fargate", "RDS"],
                        template_id=None
                    ))
            
            state["stack_selections"] = [s.dict() for s in stack_selections]
            logger.info(f"StackSelectorAgent selected stacks for {len(stack_selections)} components")
            
        except Exception as e:
            logger.error(f"Error in StackSelectorAgent: {e}")
            state["error"] = str(e)
        
        return state

