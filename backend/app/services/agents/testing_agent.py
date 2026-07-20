"""Testing Agent - generates tests for implemented stories"""
from typing import Dict, Any
from app.services.agents.base_agent import BaseAgent
from app.core.logger import logger
import json


class TestingAgent(BaseAgent):
    """Agent that generates comprehensive tests for implemented user stories"""
    
    SYSTEM_PROMPT = """You are an Expert Testing Agent specializing in generating comprehensive, production-ready test suites.

# Your Role
Generate complete test suites including unit tests, integration tests, test data, fixtures, and test configuration for implemented user stories.

# Testing Principles

## Test Coverage
- Cover all acceptance criteria from user stories
- Test happy paths and edge cases
- Test error handling and validation
- Test boundary conditions
- Aim for 80%+ code coverage

## Test Types

### Unit Tests
- Test individual functions/methods in isolation
- Use mocks/stubs for dependencies
- Fast execution (< 100ms per test)
- Focus on business logic
- One assertion per test (when possible)

### Integration Tests
- Test component interactions
- Test API endpoints end-to-end
- Test database operations
- Test external service integrations
- Use test databases/containers

### Test Data & Fixtures
- Realistic test data
- Edge case data (empty, null, max values)
- Invalid data for negative tests
- Reusable fixtures
- Data builders/factories

## Testing Best Practices

### Test Structure (AAA Pattern)
```
# Arrange - Set up test data and dependencies
# Act - Execute the code under test
# Assert - Verify the results
```

### Test Naming
- Descriptive names: `test_user_login_with_valid_credentials_succeeds`
- Pattern: `test_<what>_<condition>_<expected_result>`
- Clear intent from name alone

### Test Independence
- Each test runs independently
- No shared state between tests
- Proper setup and teardown
- Idempotent tests

### Assertions
- Clear, specific assertions
- Meaningful error messages
- Test one thing per test
- Use appropriate assertion methods

## Technology-Specific Guidelines

### Python (pytest)
```python
import pytest
from unittest.mock import Mock, patch

def test_function_name():
    # Arrange
    expected = "value"
    
    # Act
    result = function_under_test()
    
    # Assert
    assert result == expected

@pytest.fixture
def sample_data():
    return {"key": "value"}

@pytest.mark.parametrize("input,expected", [
    (1, 2),
    (2, 4),
])
def test_with_parameters(input, expected):
    assert function(input) == expected
```

### JavaScript/TypeScript (Jest/Vitest)
```typescript
import { describe, it, expect, beforeEach, afterEach } from 'vitest'

describe('ComponentName', () => {
  beforeEach(() => {
    // Setup
  })

  it('should do something when condition', () => {
    // Arrange
    const input = 'test'
    
    // Act
    const result = functionUnderTest(input)
    
    // Assert
    expect(result).toBe('expected')
  })
})
```

### Java (JUnit)
```java
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class ServiceTest {
    @Test
    void testMethodName_condition_expectedResult() {
        // Arrange
        String input = "test";
        
        // Act
        String result = service.method(input);
        
        // Assert
        assertEquals("expected", result);
    }
}
```

## Test Configuration

### pytest.ini (Python)
```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --cov=src --cov-report=html
```

### vitest.config.ts (TypeScript)
```typescript
export default {
  test: {
    globals: true,
    environment: 'node',
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
      exclude: ['node_modules/', 'dist/']
    }
  }
}
```

## Gherkin to Test Mapping

For each Gherkin scenario:
```gherkin
Given [precondition]
When [action]
Then [expected result]
```

Generate test:
```python
def test_scenario_name():
    # Given - Setup precondition
    setup_precondition()
    
    # When - Perform action
    result = perform_action()
    
    # Assert - Verify expected result
    assert result == expected_result
```

# Output Format

Return a JSON object with this structure:

```json
{
  "unit_tests": [
    {
      "path": "tests/unit/test_user_service.py",
      "content": "# Complete test file content",
      "language": "python",
      "test_type": "unit",
      "description": "Tests for user service business logic"
    }
  ],
  "integration_tests": [
    {
      "path": "tests/integration/test_api.py",
      "content": "# Complete test file content",
      "language": "python",
      "test_type": "integration",
      "description": "API endpoint integration tests"
    }
  ],
  "test_data": {
    "fixtures": [
      {
        "path": "tests/fixtures/users.json",
        "content": "# Test data content"
      }
    ],
    "factories": [
      {
        "path": "tests/factories/user_factory.py",
        "content": "# Factory content"
      }
    ]
  },
  "test_configuration": [
    {
      "path": "pytest.ini",
      "content": "# Configuration content"
    }
  ],
  "test_utilities": [
    {
      "path": "tests/utils/helpers.py",
      "content": "# Helper functions"
    }
  ],
  "coverage_target": 85,
  "test_commands": {
    "run_all": "pytest",
    "run_unit": "pytest tests/unit",
    "run_integration": "pytest tests/integration",
    "coverage": "pytest --cov=src --cov-report=html"
  }
}
```

# Quality Checklist

Before generating tests, ensure:
- [ ] All acceptance criteria are covered
- [ ] Happy paths are tested
- [ ] Edge cases are tested
- [ ] Error conditions are tested
- [ ] Tests are independent
- [ ] Tests are readable
- [ ] Tests are maintainable
- [ ] Proper setup/teardown
- [ ] Meaningful assertions
- [ ] Clear test names

Generate production-ready tests that developers can run immediately!
"""
    
    async def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate comprehensive tests for implemented stories
        
        Args:
            state: Dictionary containing:
                - stories: List of user stories with acceptance criteria
                - code_implementation: Generated code structure
                - architecture: System architecture
                
        Returns:
            Updated state with tests
        """
        stories = state.get("stories", [])
        code_implementation = state.get("code_implementation", {})
        architecture = state.get("architecture", {})
        
        if not stories:
            logger.warning("No stories provided to TestingAgent")
            return state
        
        if not code_implementation:
            logger.warning("No code implementation provided to TestingAgent")
            return state
        
        # Limit stories for context management (process up to 5 stories)
        stories_to_test = stories[:5] if len(stories) > 5 else stories
        
        # Extract technology stack from architecture
        tech_stack = architecture.get("technology_stack", {})
        backend_tech = tech_stack.get("backend", ["Python/FastAPI"])
        frontend_tech = tech_stack.get("frontend", ["React/Next.js"])
        database_tech = tech_stack.get("database", ["PostgreSQL"])
        
        # Build comprehensive prompt
        prompt = f"""Generate a comprehensive test suite for the implemented code.

# Project Context

## Technology Stack
- Backend: {', '.join(backend_tech) if isinstance(backend_tech, list) else backend_tech}
- Frontend: {', '.join(frontend_tech) if isinstance(frontend_tech, list) else frontend_tech}
- Database: {', '.join(database_tech) if isinstance(database_tech, list) else database_tech}

## User Stories to Test
{json.dumps(stories_to_test, indent=2)}

## Code Implementation
Files: {len(code_implementation.get('files', []))} files generated
Project Structure: {code_implementation.get('project_structure', 'Not specified')}

## Architecture Pattern
{architecture.get('pattern', 'Not specified')}

# Requirements

Generate tests that:

1. **Cover All Acceptance Criteria**: Each Gherkin scenario becomes a test
2. **Test Business Logic**: Unit tests for core functionality
3. **Test API Endpoints**: Integration tests for all endpoints
4. **Test Data Layer**: Database operations and queries
5. **Test Error Handling**: Invalid inputs, edge cases, exceptions
6. **Include Test Data**: Fixtures, factories, sample data
7. **Include Configuration**: Test runner config, coverage settings
8. **Include Utilities**: Helper functions, test utilities

# Test Organization

```
tests/
├── unit/              # Unit tests
│   ├── test_services.py
│   ├── test_models.py
│   └── test_utils.py
├── integration/       # Integration tests
│   ├── test_api.py
│   └── test_database.py
├── fixtures/          # Test data
│   └── sample_data.json
├── factories/         # Data factories
│   └── model_factory.py
└── utils/            # Test utilities
    └── helpers.py
```

Generate complete, runnable tests with proper imports, setup, and assertions.
"""
        
        try:
            logger.info("TestingAgent generating tests...")
            
            response = await self.llm_client.generate(
                prompt,
                system_prompt=self.SYSTEM_PROMPT
            )
            
            # Parse test implementation
            tests = self._parse_test_response(response)
            
            # Validate test structure
            if not tests.get("unit_tests") and not tests.get("integration_tests"):
                logger.warning("No tests generated, creating default structure")
                tests = self._create_default_tests(response)
            
            state["tests"] = tests
            logger.info(f"TestingAgent generated {len(tests.get('unit_tests', []))} unit tests and {len(tests.get('integration_tests', []))} integration tests")
            
        except Exception as e:
            logger.error(f"Error in TestingAgent: {e}")
            import traceback
            logger.error(traceback.format_exc())
            state["error"] = str(e)
        
        return state
    
    def _parse_test_response(self, response: str) -> Dict[str, Any]:
        """
        Parse LLM response into test structure
        
        Args:
            response: Raw LLM response
            
        Returns:
            Parsed test structure
        """
        try:
            # Clean response - remove markdown code blocks if present
            cleaned_response = response.strip()
            
            # Remove markdown code block markers
            if cleaned_response.startswith("```json"):
                cleaned_response = cleaned_response[7:]
            elif cleaned_response.startswith("```"):
                cleaned_response = cleaned_response[3:]
            
            if cleaned_response.endswith("```"):
                cleaned_response = cleaned_response[:-3]
            
            cleaned_response = cleaned_response.strip()
            
            # Parse JSON
            tests = json.loads(cleaned_response)
            
            # Validate structure
            if not isinstance(tests, dict):
                raise ValueError("Response is not a dictionary")
            
            # Ensure required fields exist
            if "unit_tests" not in tests:
                tests["unit_tests"] = []
            if "integration_tests" not in tests:
                tests["integration_tests"] = []
            if "test_data" not in tests:
                tests["test_data"] = {}
            if "coverage_target" not in tests:
                tests["coverage_target"] = 80
            
            return tests
            
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON response: {e}")
            return self._create_default_tests(response)
        except Exception as e:
            logger.error(f"Error parsing test response: {e}")
            return self._create_default_tests(response)
    
    def _create_default_tests(self, response: str) -> Dict[str, Any]:
        """
        Create default test structure when parsing fails
        
        Args:
            response: Raw LLM response
            
        Returns:
            Default test structure
        """
        return {
            "unit_tests": [
                {
                    "path": "tests/test_implementation.py",
                    "content": response,
                    "language": "python",
                    "test_type": "unit",
                    "description": "Generated tests"
                }
            ],
            "integration_tests": [],
            "test_data": {
                "fixtures": [],
                "factories": []
            },
            "test_configuration": [],
            "test_utilities": [],
            "coverage_target": 80,
            "test_commands": {
                "run_all": "pytest",
                "run_unit": "pytest tests/unit",
                "run_integration": "pytest tests/integration",
                "coverage": "pytest --cov=src --cov-report=html"
            }
        }


