"""Base agent class"""
from abc import ABC, abstractmethod
from typing import Dict, Any
from app.core.llm_client import LLMClient, get_llm_client


class BaseAgent(ABC):
    """Base class for all agents"""
    
    def __init__(self, llm_client: LLMClient = None):
        self.llm_client = llm_client or get_llm_client()
    
    @abstractmethod
    async def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Process the current state and return updated state"""
        pass

