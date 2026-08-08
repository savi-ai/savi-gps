"""Base agent class"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

from sqlalchemy.orm import Session

from app.core.llm_client import LLMClient, get_llm_client


class BaseAgent(ABC):
    """Base class for all agents"""

    def __init__(
        self,
        llm_client: LLMClient = None,
        *,
        db: Optional[Session] = None,
        tenant_id: Optional[str] = None,
        purpose: str = "other",
    ):
        if llm_client is not None:
            self.llm_client = llm_client
        elif db is not None and tenant_id:
            from app.services.llm_routing import (
                get_build_code_llm_client,
                get_other_llm_client,
            )

            if purpose == "code":
                self.llm_client = get_build_code_llm_client(db, tenant_id)
            else:
                self.llm_client = get_other_llm_client(db, tenant_id)
        else:
            self.llm_client = get_llm_client()

    @abstractmethod
    async def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Process the current state and return updated state"""
        pass
