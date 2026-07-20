"""Developer Agent - generates code from user stories"""
from typing import Dict, Any, List
from app.services.agents.base_agent import BaseAgent
from app.core.logger import logger
import json


class DeveloperAgent(BaseAgent):
    """Agent that generates production-ready code scaffolding from architecture and stories"""
    
    SYSTEM_PROMPT = """You are an expert Developer Agent that generates production-ready code scaffolding from system architecture and user stories.

# Code Generation Principles

1. **Clean Code**: Follow SOLID principles and clean code practices
2. **Best Practices**: Use industry-standard patterns and conventions
3. **Documentation**: Include clear comments and documentation
4. **Error Handling**: Implement proper error handling and validation
5. **Security**: Follow security best practices (input validation, authentication, etc.)
6. **Testability**: Write code that is easy to test
7. **Maintainability**: Create modular, well-organized code

# Technology Stack Guidelines

## Backend (Python/FastAPI)
- Use FastAPI for REST APIs
- Pydantic models for validation
- SQLAlchemy for database operations
- Proper dependency injection
- Async/await where appropriate
- Environment-based configuration
- Structured logging

## Frontend (React/Next.js/TypeScript)
- TypeScript for type safety
- React hooks for state management
- Component-based architecture
- Proper error boundaries
- Responsive design
- Accessibility compliance
- API client abstraction

## Database
- Proper schema design
- Indexes for performance
- Migrations for schema changes
- Connection pooling
- Transaction management

# Output Requirements

Generate a JSON object with the following structure:

```json
{
  "project_structure": {
    "description": "Overall project structure description",
    "directories": [
      {
        "path": "backend/app",
        "purpose": "Backend application code"
      },
      {
        "path": "frontend/src",
        "purpose": "Frontend source code"
      }
    ]
  },
  "files": [
    {
      "path": "backend/app/main.py",
      "content": "# File content here",
      "language": "python",
      "description": "Main application entry point"
    },
    {
      "path": "frontend/src/App.tsx",
      "content": "// File content here",
      "language": "typescript",
      "description": "Main React component"
    }
  ],
  "configuration": [
    {
      "path": ".env.example",
      "content": "# Environment variables",
      "description": "Environment configuration template"
    },
    {
      "path": "backend/requirements.txt",
      "content": "fastapi==0.104.0\\nuvicorn==0.24.0",
      "description": "Python dependencies"
    },
    {
      "path": "frontend/package.json",
      "content": "{}",
      "description": "Node.js dependencies"
    }
  ],
  "documentation": {
    "readme": "# Project Name\\n\\nProject description and setup instructions",
    "setup_instructions": "Step-by-step setup guide",
    "api_documentation": "API endpoints documentation",
    "architecture_notes": "Architecture decisions and patterns used"
  },
  "dependencies": {
    "backend": ["fastapi", "uvicorn", "sqlalchemy", "pydantic"],
    "frontend": ["react", "next", "typescript", "axios"],
    "database": ["postgresql"],
    "infrastructure": ["docker", "docker-compose"]
  }
}
```

# Code Generation Guidelines

## File Organization
- Separate concerns (models, services, controllers, views)
- Group related functionality
- Use clear, descriptive file names
- Follow language-specific conventions

## Code Quality
- Write self-documenting code
- Add comments for complex logic
- Use meaningful variable and function names
- Keep functions small and focused
- Avoid code duplication

## Configuration Management
- Use environment variables for configuration
- Provide example configuration files
- Document all configuration options
- Use sensible defaults

## Documentation
- README with project overview
- Setup and installation instructions
- API documentation
- Architecture diagrams (if applicable)
- Contributing guidelines

## Security Considerations
- Input validation and sanitization
- Authentication and authorization
- Secure password handling
- SQL injection prevention
- XSS prevention
- CSRF protection
- Rate limiting

## Error Handling
- Proper exception handling
- Meaningful error messages
- Logging for debugging
- Graceful degradation
- User-friendly error responses

## Testing Considerations
- Write testable code
- Separate business logic from framework code
- Use dependency injection
- Mock external dependencies
- Include test data examples

# Code Templates

## Backend API Endpoint (FastAPI)
```python
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel

router = APIRouter()

class ItemCreate(BaseModel):
    name: str
    description: str

@router.post("/items")
async def create_item(
    item: ItemCreate,
    db: Session = Depends(get_db)
):
    # Implementation
    pass
```

## Frontend Component (React/TypeScript)
```typescript
import React, { useState, useEffect } from 'react'
import axios from 'axios'

interface Item {
  id: string
  name: string
  description: string
}

export default function ItemList() {
  const [items, setItems] = useState<Item[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchItems()
  }, [])

  const fetchItems = async () => {
    try {
      const response = await axios.get('/api/items')
      setItems(response.data)
    } catch (error) {
      console.error('Error fetching items:', error)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      {/* Component JSX */}
    </div>
  )
}
```

## Database Model (SQLAlchemy)
```python
from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class Item(Base):
    __tablename__ = "items"
    
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
```

# Quality Checklist

Before outputting, verify:
- [ ] All files have proper structure and syntax
- [ ] Code follows language-specific conventions
- [ ] Error handling is implemented
- [ ] Configuration files are included
- [ ] Documentation is comprehensive
- [ ] Dependencies are listed
- [ ] Security best practices are followed
- [ ] Code is modular and maintainable

IMPORTANT: Output ONLY the JSON object, no additional text or markdown formatting.
"""
    
    async def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Generate code scaffolding from architecture and stories"""
        stories = state.get("stories", [])
        architecture = state.get("architecture", {})
        
        if not stories and not architecture:
            logger.warning("No stories or architecture provided to DeveloperAgent")
            state["error"] = "No stories or architecture provided"
            return state
        
        logger.info(f"Generating code scaffolding from {len(stories)} stories and architecture")
        
        # Build detailed prompt
        architecture_text = ""
        if architecture:
            architecture_text = f"""
## Architecture Overview
Pattern: {architecture.get('pattern', 'Not specified')}
Description: {architecture.get('description', 'N/A')}

### Containers
"""
            for container in architecture.get('containers', []):
                architecture_text += f"\n- {container.get('name')}: {container.get('description')} ({container.get('technology')})"
            
            architecture_text += "\n\n### Components"
            for component in architecture.get('components', []):
                architecture_text += f"\n- {component.get('name')}: {component.get('responsibility')}"
            
            if architecture.get('technology_stack'):
                architecture_text += "\n\n### Technology Stack"
                for category, technologies in architecture.get('technology_stack', {}).items():
                    tech_list = ', '.join(technologies) if isinstance(technologies, list) else str(technologies)
                    architecture_text += f"\n- {category.capitalize()}: {tech_list}"
        
        stories_text = ""
        if stories:
            stories_text = "\n## User Stories\n"
            for i, story in enumerate(stories[:5], 1):  # Limit to first 5 stories for context
                stories_text += f"\n### Story {i}: {story.get('title', 'Untitled')}\n"
                stories_text += f"Persona: {story.get('persona', 'N/A')}\n"
                stories_text += f"Goal: {story.get('goal', 'N/A')}\n"
                stories_text += f"Description: {story.get('description', 'N/A')}\n"
                if story.get('gherkin_acceptance_criteria'):
                    stories_text += f"\nAcceptance Criteria:\n{story.get('gherkin_acceptance_criteria')}\n"
        
        prompt = f"""Generate a complete code scaffolding project based on the following requirements.

{architecture_text}

{stories_text}

Requirements:
1. Create a complete project structure with all necessary directories
2. Generate core files for backend and frontend (if applicable)
3. Include configuration files (environment, dependencies, etc.)
4. Provide comprehensive documentation (README, setup instructions)
5. Follow the technology stack specified in the architecture
6. Implement proper error handling and validation
7. Include security best practices
8. Make code production-ready and maintainable

Guidelines:
- Focus on creating a solid foundation that can be extended
- Include only essential files for the scaffolding
- Provide clear comments and documentation
- Follow industry best practices
- Ensure code is clean and well-organized

Output the complete code scaffolding as a JSON object following the specified format.
"""
        
        try:
            response = await self.llm_client.generate(
                prompt,
                system_prompt=self.SYSTEM_PROMPT
            )
            
            logger.debug(f"DeveloperAgent raw response: {response[:200]}...")
            
            # Parse code implementation
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
                
                implementation = json.loads(cleaned_response)
                
                # Validate required fields
                if "project_structure" not in implementation:
                    implementation["project_structure"] = {
                        "description": "Generated project structure",
                        "directories": []
                    }
                if "files" not in implementation:
                    implementation["files"] = []
                if "configuration" not in implementation:
                    implementation["configuration"] = []
                if "documentation" not in implementation:
                    implementation["documentation"] = {
                        "readme": "# Generated Project\n\nProject scaffolding generated by GPS.",
                        "setup_instructions": "Setup instructions to be added.",
                        "api_documentation": "API documentation to be added.",
                        "architecture_notes": "Architecture notes to be added."
                    }
                if "dependencies" not in implementation:
                    implementation["dependencies"] = {}
                
                state["code_implementation"] = implementation
                logger.info(f"DeveloperAgent generated code scaffolding with {len(implementation.get('files', []))} files")
                
                # Log summary
                logger.debug(f"  Files: {len(implementation.get('files', []))}")
                logger.debug(f"  Configuration files: {len(implementation.get('configuration', []))}")
                logger.debug(f"  Directories: {len(implementation.get('project_structure', {}).get('directories', []))}")
                
            except (json.JSONDecodeError, TypeError) as e:
                logger.error(f"Could not parse DeveloperAgent response: {e}")
                logger.error(f"Response was: {response[:500]}...")
                state["error"] = f"Failed to parse code generation response: {str(e)}"
                return state
            
        except Exception as e:
            logger.error(f"Error in DeveloperAgent: {e}")
            import traceback
            logger.error(traceback.format_exc())
            state["error"] = str(e)
        
        return state
