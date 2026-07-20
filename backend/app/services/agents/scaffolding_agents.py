"""Scaffolding Agents - generate code and infrastructure"""
from typing import Dict, Any
from app.services.agents.base_agent import BaseAgent
from app.services.sop_agent import sop_agent
from app.core.models import ArtifactType, SOPValidationRequest
from app.core.logger import logger
import json


class BackendScaffoldingAgent(BaseAgent):
    """Agent that generates backend scaffolding"""
    
    SYSTEM_PROMPT = """You are a Backend Scaffolding Agent that generates Spring Boot project structure.

Generate:
- Directory structure
- Initial files (pom.xml, application.yml, main class)
- Logging configuration
- Security configuration
- Test skeletons (JUnit, Karate)

Output as JSON with file structure and content.
"""
    
    async def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Generate backend scaffolding"""
        stack_selections = state.get("stack_selections", [])
        components = state.get("architecture", {}).get("components", [])
        
        # Filter for backend components
        backend_components = [
            c for c in components
            if any(sel["component_name"] == c.get("name") and "Spring Boot" in sel.get("implementation_stack", "")
                   for sel in stack_selections)
        ]
        
        if not backend_components:
            logger.info("No backend components to scaffold")
            return state
        
        prompt = f"""Generate Spring Boot scaffolding for:

Components: {json.dumps(backend_components, indent=2)}
Stack Selections: {json.dumps(stack_selections, indent=2)}

Create a complete project structure with all necessary files.
"""
        
        try:
            response = await self.llm_client.generate(
                prompt,
                system_prompt=self.SYSTEM_PROMPT
            )
            
            scaffolding = {}
            try:
                scaffolding = json.loads(response)
            except json.JSONDecodeError:
                scaffolding = {"structure": response, "files": {}}
            
            # Validate against SOPs
            validation_request = SOPValidationRequest(
                artifact_type=ArtifactType.ARCHITECTURE,
                context={"stack": "Java/Spring Boot"},
                artifact_content=json.dumps(scaffolding)
            )
            validation_result = await sop_agent.validate(validation_request)
            
            if not validation_result.valid:
                scaffolding["sop_violations"] = [v.dict() for v in validation_result.violations]
            
            state.setdefault("scaffolding", {})["backend"] = scaffolding
            logger.info("BackendScaffoldingAgent generated scaffolding")
            
        except Exception as e:
            logger.error(f"Error in BackendScaffoldingAgent: {e}")
            state["error"] = str(e)
        
        return state


class FrontendScaffoldingAgent(BaseAgent):
    """Agent that generates frontend scaffolding"""
    
    SYSTEM_PROMPT = """You are a Frontend Scaffolding Agent that generates Next.js/React or Nuxt/Vue project structure.

Generate:
- Directory structure
- Pages/components
- Configuration files
- Test skeletons

Output as JSON with file structure and content.
"""
    
    async def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Generate frontend scaffolding"""
        stack_selections = state.get("stack_selections", [])
        components = state.get("architecture", {}).get("components", [])
        
        # Filter for frontend components
        frontend_components = [
            c for c in components
            if any(sel["component_name"] == c.get("name") and 
                   ("React" in sel.get("implementation_stack", "") or "Vue" in sel.get("implementation_stack", ""))
                   for sel in stack_selections)
        ]
        
        if not frontend_components:
            logger.info("No frontend components to scaffold")
            return state
        
        prompt = f"""Generate frontend scaffolding for:

Components: {json.dumps(frontend_components, indent=2)}
Stack Selections: {json.dumps(stack_selections, indent=2)}

Create a complete project structure.
"""
        
        try:
            response = await self.llm_client.generate(
                prompt,
                system_prompt=self.SYSTEM_PROMPT
            )
            
            scaffolding = {}
            try:
                scaffolding = json.loads(response)
            except json.JSONDecodeError:
                scaffolding = {"structure": response, "files": {}}
            
            state.setdefault("scaffolding", {})["frontend"] = scaffolding
            logger.info("FrontendScaffoldingAgent generated scaffolding")
            
        except Exception as e:
            logger.error(f"Error in FrontendScaffoldingAgent: {e}")
            state["error"] = str(e)
        
        return state


class InfraScaffoldingAgent(BaseAgent):
    """Agent that generates infrastructure and pipeline scaffolding"""
    
    SYSTEM_PROMPT = """You are an Infrastructure Scaffolding Agent that generates Terraform/CDK modules and Harness pipelines.

Generate:
- Terraform/CDK modules for AWS infrastructure
- Harness pipeline YAML with:
  - Unit tests
  - Coverage checks
  - Security scans
  - Promotion gates

Output as JSON with infrastructure code and pipeline definitions.
"""
    
    async def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Generate infrastructure scaffolding"""
        stack_selections = state.get("stack_selections", [])
        architecture = state.get("architecture", {})
        
        prompt = f"""Generate infrastructure and CI/CD pipelines for:

Architecture: {json.dumps(architecture, indent=2)}
Stack Selections: {json.dumps(stack_selections, indent=2)}

Create Terraform modules and Harness pipeline definitions.
"""
        
        try:
            response = await self.llm_client.generate(
                prompt,
                system_prompt=self.SYSTEM_PROMPT
            )
            
            scaffolding = {}
            try:
                scaffolding = json.loads(response)
            except json.JSONDecodeError:
                scaffolding = {"terraform": response, "harness": {}}
            
            # Validate against SOPs
            validation_request = SOPValidationRequest(
                artifact_type=ArtifactType.PIPELINE,
                context={"environment": "production"},
                artifact_content=json.dumps(scaffolding)
            )
            validation_result = await sop_agent.validate(validation_request)
            
            if not validation_result.valid:
                scaffolding["sop_violations"] = [v.dict() for v in validation_result.violations]
            
            state.setdefault("scaffolding", {})["infra"] = scaffolding
            logger.info("InfraScaffoldingAgent generated scaffolding")
            
        except Exception as e:
            logger.error(f"Error in InfraScaffoldingAgent: {e}")
            state["error"] = str(e)
        
        return state

