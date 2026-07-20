"""Feature Agent - creates normalized Feature objects"""
from typing import Dict, Any, List
from app.core.models import Feature
from app.services.agents.base_agent import BaseAgent
from app.core.logger import logger
import json


class FeatureAgent(BaseAgent):
    """Agent that creates normalized Feature objects"""
    
    SYSTEM_PROMPT = """You are a Feature Agent that creates well-structured feature definitions.

For each feature, provide:
- title: Clear, concise feature title
- description: Detailed description
- business_value: Why this feature matters
- actors: List of user personas/actors
- high_level_flow: Step-by-step flow
- acceptance_criteria: List of acceptance criteria

Output as JSON array of features.
"""
    
    async def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Create normalized features"""
        idea = state.get("idea", "")
        candidate_features = state.get("candidate_features", [])
        vision = state.get("vision", "")
        
        # If candidate_features exist and are well-formed, use them directly
        if candidate_features and isinstance(candidate_features, list) and len(candidate_features) > 0:
            # Check if they're already in the right format
            if all(isinstance(cf, dict) and ("title" in cf or "name" in cf) for cf in candidate_features):
                logger.info(f"Using {len(candidate_features)} candidate_features directly")
                features = []
                for cf in candidate_features:
                    try:
                        # Convert candidate feature to Feature model
                        feature_dict = {
                            "title": cf.get("title") or cf.get("name", "Untitled Feature"),
                            "description": cf.get("description", ""),
                            "business_value": cf.get("business_value", "To be determined"),
                            "actors": cf.get("actors", []),
                            "high_level_flow": cf.get("high_level_flow", "To be determined"),
                            "acceptance_criteria": cf.get("acceptance_criteria", [])
                        }
                        features.append(Feature(**feature_dict))
                    except Exception as e:
                        logger.warning(f"Error converting candidate feature: {e}")
                        # Create a basic feature from candidate
                        features.append(Feature(
                            title=cf.get("title") or cf.get("name", "Untitled Feature"),
                            description=cf.get("description", ""),
                            business_value="To be determined",
                            actors=[],
                            high_level_flow="To be determined",
                            acceptance_criteria=[]
                        ))
                
                state["features"] = [f.dict() for f in features]
                logger.info(f"FeatureAgent created {len(features)} features from candidate_features")
                return state
        
        if not candidate_features and not idea:
            logger.warning("No features or idea provided to FeatureAgent")
            return state
        
        prompt = f"""Create normalized feature definitions.

Vision: {vision}

Candidate Features: {json.dumps(candidate_features) if candidate_features else 'None - derive from idea'}

Original Idea: {idea}

For each feature, create a structured definition with title, description, business value, actors, high-level flow, and acceptance criteria.
"""
        
        try:
            response = await self.llm_client.generate(
                prompt,
                system_prompt=self.SYSTEM_PROMPT
            )
            
            # Parse features from response
            features = []
            try:
                # Clean response - remove markdown code blocks if present
                cleaned_response = response.strip()
                if cleaned_response.startswith("```json"):
                    cleaned_response = cleaned_response[7:]
                if cleaned_response.startswith("```"):
                    cleaned_response = cleaned_response[3:]
                if cleaned_response.endswith("```"):
                    cleaned_response = cleaned_response[:-3]
                cleaned_response = cleaned_response.strip()
                
                parsed = json.loads(cleaned_response)
                if isinstance(parsed, list):
                    for f in parsed:
                        if isinstance(f, dict):
                            features.append(Feature(**f))
                        else:
                            logger.warning(f"Invalid feature format: {f}")
                elif isinstance(parsed, dict):
                    if "features" in parsed:
                        for f in parsed["features"]:
                            if isinstance(f, dict):
                                features.append(Feature(**f))
                    elif "title" in parsed or "description" in parsed:
                        # Single feature object
                        features.append(Feature(**parsed))
                    else:
                        logger.warning(f"Unexpected response format: {parsed.keys()}")
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning(f"Could not parse FeatureAgent response as JSON: {e}")
                logger.warning(f"Response was: {response[:200]}...")
                # Try to extract features from text
                # Create a single feature from the response
                features = [Feature(
                    title="Generated Feature",
                    description=response[:500],
                    business_value="To be determined",
                    actors=[],
                    high_level_flow="To be determined",
                    acceptance_criteria=[]
                )]
            
            # Ensure all features are properly converted to dicts
            state["features"] = []
            for f in features:
                if isinstance(f, Feature):
                    state["features"].append(f.dict())
                elif isinstance(f, dict):
                    state["features"].append(f)
                else:
                    logger.warning(f"Unexpected feature type: {type(f)}")
            logger.info(f"FeatureAgent created {len(features)} features")
            
        except Exception as e:
            logger.error(f"Error in FeatureAgent: {e}")
            state["error"] = str(e)
        
        return state

