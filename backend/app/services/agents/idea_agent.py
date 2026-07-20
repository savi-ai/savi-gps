"""Idea Agent - processes high-level ideas into vision and features"""
from typing import Dict, Any
from app.services.agents.base_agent import BaseAgent
from app.core.logger import logger


class IdeaAgent(BaseAgent):
    """Agent that processes ideas into vision and candidate features"""
    
    SYSTEM_PROMPT = """You are a friendly and helpful Idea Agent that helps users refine their ideas through conversation.

Your role is to:
1. Have a natural, conversational dialogue with the user
2. Ask clarifying questions to better understand their idea
3. Be helpful and engaging, not robotic

IMPORTANT: When the user first describes their idea, you MUST:
- Acknowledge their idea warmly (1-2 sentences)
- Try to ask probing questions to better understand the idea and form a vision and summary of the idea.
- Aske clarifying questions on the idea that will be required for generating features as next step

Keep responses conversational and natural - do NOT output JSON or structured data in chat.
Just have a friendly conversation to gather information.

Some ideas of what questions can be asked (one at a time):
1. "Is this application external-facing (for customers/users) or internal-facing (for employees/internal use)?"
2. "Are there any specific non-functional requirements (NFRs) we should consider, such as security, scalability, or performance needs?"


After asking each question, wait for the user's response before asking the next one.
Keep your responses short (2-3 sentences max), friendly, and conversational.
"""
    
    PROCESS_SYSTEM_PROMPT = """You are an Idea Agent that transforms raw ideas into structured vision statements and feature lists.

Given an idea, you MUST respond with a valid JSON object containing:
- "vision": A clear, concise vision statement (1-3 sentences)
- "features": An array of feature objects, each with "title" and "description" fields
- "clarifying_questions": An array of questions that could help refine the idea further

Example response format:
{
  "vision": "A platform that enables...",
  "features": [
    {"title": "User Authentication", "description": "Allow users to sign up and log in securely"},
    {"title": "Dashboard", "description": "Central hub showing key metrics and actions"}
  ],
  "clarifying_questions": ["Who is the target audience?"]
}

Respond ONLY with the JSON object, no markdown or extra text."""

    async def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Process idea into vision and features"""
        idea = state.get("idea", "")
        if not idea:
            logger.warning("No idea provided to IdeaAgent")
            return state
        
        prompt = f"""Process the following idea and generate a vision statement with candidate features.

Idea: {idea}

Respond with a JSON object containing "vision", "features", and "clarifying_questions".
"""
        
        try:
            response = await self.llm_client.generate(
                prompt,
                system_prompt=self.PROCESS_SYSTEM_PROMPT
            )

            # Try to parse JSON response
            import json
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
                state["vision"] = parsed.get("vision", "")
                # Handle both "features" and "candidate_features" keys
                state["candidate_features"] = parsed.get("features", parsed.get("candidate_features", []))
                state["clarifying_questions"] = parsed.get("clarifying_questions", [])
            except json.JSONDecodeError as e:
                # If not JSON, extract vision and features from text
                logger.warning(f"IdeaAgent response not in JSON format: {e}")
                state["vision"] = response[:500]  # First 500 chars as vision
                state["candidate_features"] = []  # Will be populated by FeatureAgent
            
            logger.info(f"IdeaAgent processed idea, generated vision: {state.get('vision', '')[:100]}...")
            
        except Exception as e:
            logger.error(f"Error in IdeaAgent: {e}")
            state["error"] = str(e)
        
        return state

