"""Architecture Agent - proposes architecture and components"""
from typing import Dict, Any, List
from app.core.models import Architecture, Component
from app.services.agents.base_agent import BaseAgent
from app.core.logger import logger
import json


class ArchitectureAgent(BaseAgent):
    """Agent that proposes system architecture using C4 model and DDD principles"""
    
    SYSTEM_PROMPT = """You are an expert Architecture Agent that designs system architecture using industry best practices.

# Architecture Design Principles

1. **C4 Model**: Use Context, Container, Component, and Code levels
2. **Domain-Driven Design (DDD)**: Identify bounded contexts and domain events
3. **Separation of Concerns**: Clear boundaries between components
4. **Scalability**: Design for growth and high availability
5. **Security**: Consider authentication, authorization, and data protection
6. **Technology Agnostic**: Focus on logical architecture first

# Architecture Patterns

Choose the most appropriate pattern based on requirements:

- **Monolithic**: Simple applications, small teams, rapid development
- **Layered**: Clear separation of presentation, business, data layers
- **Microservices**: Independent services, scalability, team autonomy
- **Event-Driven**: Asynchronous processing, loose coupling
- **Serverless**: Pay-per-use, auto-scaling, minimal ops
- **Hexagonal**: Ports and adapters, testability

# C4 Model Levels

## Context Level
- System boundary and external dependencies
- Users and external systems
- High-level interactions

## Container Level
- Applications, databases, file systems
- Technology choices
- Communication protocols

## Component Level
- Major structural building blocks
- Responsibilities and interfaces
- Dependencies between components

# Output Requirements

Generate a JSON object with the following structure:

```json
{
  "pattern": "Architecture pattern name",
  "description": "Overall architecture description",
  "containers": [
    {
      "name": "Container name",
      "type": "Web Application|API|Database|Message Queue|Cache",
      "technology": "Specific technology (e.g., React, FastAPI, PostgreSQL)",
      "description": "What this container does",
      "responsibilities": ["List", "of", "responsibilities"]
    }
  ],
  "components": [
    {
      "name": "Component name",
      "container": "Parent container name",
      "responsibility": "What this component does",
      "apis": ["List of APIs it exposes"],
      "data_stores": ["Databases or storage it uses"],
      "dependencies": ["Other components it depends on"]
    }
  ],
  "bounded_contexts": [
    "Context 1: Description",
    "Context 2: Description"
  ],
  "domain_events": [
    "Event 1: When it occurs",
    "Event 2: When it occurs"
  ],
  "technology_stack": {
    "frontend": ["React", "TypeScript"],
    "backend": ["Python", "FastAPI"],
    "database": ["PostgreSQL"],
    "infrastructure": ["Docker", "Kubernetes"]
  },
  "diagrams": {
    "context": "mermaid C4Context diagram code",
    "container": "mermaid C4Container diagram code",
    "component": "mermaid C4Component diagram code"
  }
}
```

# Mermaid Diagram Format

Use Mermaid C4 diagram syntax:

## Context Diagram
```mermaid
C4Context
  title System Context for [System Name]
  
  Person(user, "User", "A user of the system")
  System(system, "System Name", "Description")
  System_Ext(external, "External System", "Description")
  
  Rel(user, system, "Uses")
  Rel(system, external, "Calls", "HTTPS")
```

## Container Diagram
```mermaid
C4Container
  title Container Diagram for [System Name]
  
  Person(user, "User")
  Container(web, "Web Application", "React", "Description")
  Container(api, "API", "FastAPI", "Description")
  ContainerDb(db, "Database", "PostgreSQL", "Description")
  
  Rel(user, web, "Uses", "HTTPS")
  Rel(web, api, "Calls", "REST/JSON")
  Rel(api, db, "Reads/Writes", "SQL")
```

## Component Diagram
```mermaid
C4Component
  title Component Diagram for [Container Name]
  
  Component(comp1, "Component 1", "Description")
  Component(comp2, "Component 2", "Description")
  ComponentDb(store, "Data Store", "Description")
  
  Rel(comp1, comp2, "Uses")
  Rel(comp2, store, "Reads/Writes")
```

# Design Guidelines

1. **Keep it Simple**: Start with the simplest architecture that meets requirements
2. **Limit Components**: 5-10 major components is ideal
3. **Clear Boundaries**: Each component should have a single, well-defined responsibility
4. **Technology Choices**: Recommend proven, widely-adopted technologies
5. **Scalability**: Consider horizontal scaling, caching, load balancing
6. **Security**: Include authentication, authorization, encryption
7. **Observability**: Plan for logging, monitoring, tracing
8. **Data Management**: Consider data consistency, backup, recovery

# Quality Checklist

Before outputting, verify:
- [ ] Architecture pattern is appropriate for the scale
- [ ] All containers have clear responsibilities
- [ ] Components are properly grouped into containers
- [ ] Bounded contexts are identified
- [ ] Domain events are listed
- [ ] Technology stack is complete
- [ ] Mermaid diagrams are syntactically correct
- [ ] Dependencies are clearly defined

IMPORTANT: Output ONLY the JSON object, no additional text or markdown formatting.
"""
    
    async def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Create architecture from features and stories using C4 model and DDD"""
        stories = state.get("stories", [])
        features = state.get("features", [])
        repo_context = state.get("repo_context") or ""
        
        if not stories and not features:
            logger.warning("No stories or features provided to ArchitectureAgent")
            state["error"] = "No stories or features provided"
            return state
        
        logger.info(f"Generating architecture from {len(features)} features and {len(stories)} stories")
        
        # Build detailed prompt
        features_text = ""
        if features:
            for i, feature in enumerate(features, 1):
                features_text += f"\n## Feature {i}: {feature.get('title', 'Untitled')}\n"
                features_text += f"Description: {feature.get('description', 'N/A')}\n"
                features_text += f"Business Value: {feature.get('business_value', 'N/A')}\n"
                features_text += f"Actors: {', '.join(feature.get('actors', []))}\n"
        
        stories_text = ""
        if stories:
            for i, story in enumerate(stories, 1):
                stories_text += f"\n## Story {i}: {story.get('title', 'Untitled')}\n"
                stories_text += f"Persona: {story.get('persona', 'N/A')}\n"
                stories_text += f"Goal: {story.get('goal', 'N/A')}\n"
                stories_text += f"Description: {story.get('description', 'N/A')}\n"
        
        prompt = f"""Design a comprehensive system architecture based on the following requirements.

{features_text if features_text else ""}

{stories_text if stories_text else ""}

{f"## Existing linked repositories (align where relevant)\\n{repo_context}\\n" if repo_context else ""}

Requirements:
1. Choose the most appropriate architecture pattern
2. Define containers (applications, databases, services)
3. Break down into components with clear responsibilities
4. Identify bounded contexts using DDD principles
5. List key domain events
6. Recommend technology stack
7. Generate Mermaid C4 diagrams (context, container, component)

Guidelines:
- Keep the architecture simple and focused
- Limit to 5-10 major components
- Use proven technologies
- Consider scalability and security
- Ensure clear separation of concerns

Output the complete architecture as a JSON object following the specified format.
"""
        
        try:
            response = await self.llm_client.generate(
                prompt,
                system_prompt=self.SYSTEM_PROMPT
            )
            
            logger.debug(f"ArchitectureAgent raw response: {response[:200]}...")
            
            # Parse architecture
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
                
                arch_data = json.loads(cleaned_response)
                
                # Validate required fields
                if "pattern" not in arch_data:
                    arch_data["pattern"] = "Layered"
                if "description" not in arch_data:
                    arch_data["description"] = "System architecture"
                if "containers" not in arch_data:
                    arch_data["containers"] = []
                if "components" not in arch_data:
                    arch_data["components"] = []
                if "bounded_contexts" not in arch_data:
                    arch_data["bounded_contexts"] = []
                if "domain_events" not in arch_data:
                    arch_data["domain_events"] = []
                
                # Ensure diagrams exist
                if "diagrams" not in arch_data or not arch_data["diagrams"]:
                    arch_data["diagrams"] = self._generate_default_diagrams(arch_data)
                
                # Create Architecture object for validation
                architecture = Architecture(**arch_data)
                arch_dict = architecture.dict()
                
                # Add diagrams back (not in model)
                if "diagrams" in arch_data:
                    arch_dict["diagrams"] = arch_data["diagrams"]
                
                # Generate React Flow diagrams
                arch_dict["react_flow_diagrams"] = self._generate_react_flow_diagrams(arch_data)
                
                # Add technology_stack if present
                if "technology_stack" in arch_data:
                    arch_dict["technology_stack"] = arch_data["technology_stack"]
                
                state["architecture"] = arch_dict
                logger.info(f"ArchitectureAgent created architecture with {len(arch_dict.get('components', []))} components")
                
                # Log architecture summary
                logger.debug(f"  Pattern: {arch_dict.get('pattern')}")
                logger.debug(f"  Containers: {len(arch_dict.get('containers', []))}")
                logger.debug(f"  Components: {len(arch_dict.get('components', []))}")
                logger.debug(f"  Bounded Contexts: {len(arch_dict.get('bounded_contexts', []))}")
                
            except (json.JSONDecodeError, TypeError) as e:
                logger.error(f"Could not parse ArchitectureAgent response: {e}")
                logger.error(f"Response was: {response[:500]}...")
                state["error"] = f"Failed to parse architecture response: {str(e)}"
                return state
            
        except Exception as e:
            logger.error(f"Error in ArchitectureAgent: {e}")
            import traceback
            logger.error(traceback.format_exc())
            state["error"] = str(e)
        
        return state
    
    def _generate_default_diagrams(self, arch_data: dict) -> dict:
        """Generate default Mermaid diagrams if not provided"""
        system_name = "System"
        containers = arch_data.get("containers", [])
        components = arch_data.get("components", [])
        
        # Context diagram
        context_diagram = f"""C4Context
  title System Context for {system_name}
  
  Person(user, "User", "System user")
  System(system, "{system_name}", "{arch_data.get('description', 'Main system')}")
  
  Rel(user, system, "Uses")
"""
        
        # Container diagram
        container_diagram = f"""C4Container
  title Container Diagram for {system_name}
  
  Person(user, "User")
"""
        for i, container in enumerate(containers[:5], 1):  # Limit to 5 containers
            container_name = container.get("name", f"Container{i}")
            container_type = container.get("type", "Application")
            tech = container.get("technology", "")
            desc = container.get("description", "")
            container_diagram += f'  Container(c{i}, "{container_name}", "{tech}", "{desc}")\n'
        
        if containers:
            container_diagram += f'\n  Rel(user, c1, "Uses")\n'
            for i in range(1, min(len(containers), 5)):
                container_diagram += f'  Rel(c{i}, c{i+1}, "Calls")\n'
        
        # Component diagram
        component_diagram = f"""C4Component
  title Component Diagram
  
"""
        for i, component in enumerate(components[:5], 1):  # Limit to 5 components
            comp_name = component.get("name", f"Component{i}")
            resp = component.get("responsibility", "")
            component_diagram += f'  Component(comp{i}, "{comp_name}", "{resp}")\n'
        
        if len(components) > 1:
            component_diagram += '\n'
            for i in range(1, min(len(components), 5)):
                component_diagram += f'  Rel(comp{i}, comp{i+1}, "Uses")\n'
        
        return {
            "context": context_diagram,
            "container": container_diagram,
            "component": component_diagram
        }

    def _generate_react_flow_diagrams(self, arch_data: dict) -> dict:
        """Generate React Flow-compatible node/edge data for each diagram type."""
        system_name = arch_data.get("description", "System")
        containers = arch_data.get("containers", [])
        components = arch_data.get("components", [])

        def _make_node(node_id, node_type, label, description="", technology=""):
            return {
                "id": node_id,
                "type": node_type,
                "data": {
                    "label": label,
                    "description": description,
                    "technology": technology,
                    "nodeType": node_type,
                },
                "position": {"x": 0, "y": 0},
            }

        def _make_edge(edge_id, source, target, label="", animated=True):
            return {
                "id": edge_id,
                "source": source,
                "target": target,
                "label": label,
                "animated": animated,
            }

        # --- Context diagram ---
        ctx_nodes = [
            _make_node("user", "person", "User", "System user"),
            _make_node("system", "system", system_name, arch_data.get("description", "")),
        ]
        ctx_edges = [_make_edge("edge-user-system", "user", "system", "Uses")]

        # --- Container diagram ---
        cont_nodes = [_make_node("user", "person", "User", "System user")]
        cont_edges = []
        for i, c in enumerate(containers[:8], 1):
            cid = f"c{i}"
            ctype = "database" if "db" in c.get("type", "").lower() or "database" in c.get("type", "").lower() else "container"
            cont_nodes.append(
                _make_node(cid, ctype, c.get("name", f"Container {i}"), c.get("description", ""), c.get("technology", ""))
            )
        if cont_nodes:
            cont_edges.append(_make_edge("edge-user-c1", "user", "c1", "Uses"))
            for i in range(1, min(len(containers), 8)):
                cont_edges.append(_make_edge(f"edge-c{i}-c{i+1}", f"c{i}", f"c{i+1}", "Calls"))

        # --- Component diagram ---
        comp_nodes = []
        comp_edges = []
        for i, comp in enumerate(components[:8], 1):
            cid = f"comp{i}"
            comp_nodes.append(
                _make_node(cid, "component", comp.get("name", f"Component {i}"), comp.get("responsibility", ""), "")
            )
        for i in range(1, min(len(components), 8)):
            comp_edges.append(_make_edge(f"edge-comp{i}-comp{i+1}", f"comp{i}", f"comp{i+1}", "Uses"))

        return {
            "context": {"nodes": ctx_nodes, "edges": ctx_edges},
            "container": {"nodes": cont_nodes, "edges": cont_edges},
            "component": {"nodes": comp_nodes, "edges": comp_edges},
        }


