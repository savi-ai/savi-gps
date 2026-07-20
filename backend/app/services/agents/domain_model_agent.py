"""Domain Modeling Agent - derives domain model from stories"""
from typing import Dict, Any
from app.services.agents.base_agent import BaseAgent
from app.core.logger import logger
import json


class DomainModelAgent(BaseAgent):
    """Agent that creates domain models from stories"""
    
    SYSTEM_PROMPT = """You are a Domain Modeling Agent that derives bounded contexts, entities, and domain events from user stories.

Using Domain-Driven Design principles, identify:
- Bounded contexts: Distinct areas of the domain
- Entities: Core domain objects with identity
- Domain events: Important events that occur in the domain

Output as JSON with:
- bounded_contexts: List of bounded context names and descriptions
- entities: List of entities with attributes
- domain_events: List of domain events
"""
    
    async def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Create domain model from stories"""
        stories = state.get("stories", [])
        
        if not stories:
            logger.warning("No stories provided to DomainModelAgent")
            return state
        
        prompt = f"""Create a domain model from the following user stories:

Stories: {json.dumps(stories, indent=2)}

Identify bounded contexts, entities, and domain events using DDD principles.
"""
        
        try:
            response = await self.llm_client.generate(
                prompt,
                system_prompt=self.SYSTEM_PROMPT
            )
            
            # Parse domain model
            domain_model = {}
            try:
                domain_model = json.loads(response)
            except json.JSONDecodeError:
                logger.warning("DomainModelAgent response not in JSON format")
                domain_model = {
                    "bounded_contexts": [],
                    "entities": [],
                    "domain_events": []
                }
            
            state["domain_model"] = domain_model
            logger.info("DomainModelAgent created domain model")
            
        except Exception as e:
            logger.error(f"Error in DomainModelAgent: {e}")
            state["error"] = str(e)
        
        return state

