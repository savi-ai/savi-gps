"""Story Agent - generates INVEST-compliant user stories"""
from typing import Dict, Any, List
from app.core.models import Story
from app.services.agents.base_agent import BaseAgent
from app.core.logger import logger
import json


class StoryAgent(BaseAgent):
    """Agent that generates INVEST-compliant user stories"""
    
    SYSTEM_PROMPT = """You are an expert Story Agent that creates INVEST-compliant user stories from features.

# INVEST Criteria (CRITICAL)

Every story MUST satisfy ALL INVEST criteria:

1. **Independent**: Story can be developed and delivered independently of other stories
2. **Negotiable**: Details can be discussed and refined with stakeholders
3. **Valuable**: Delivers clear, measurable value to end users or business
4. **Estimable**: Team can estimate effort required (if not, story is too vague)
5. **Small**: Can be completed within a single sprint (1-2 weeks)
6. **Testable**: Has clear acceptance criteria that can be verified

# Story Format

Each story MUST follow this structure:

```
As a [persona]
I want [goal]
So that [benefit/value]
```

# Output Requirements

For each feature, generate 1-3 user stories. Each story must include:

- **title**: Clear, concise story title (max 60 characters)
- **description**: Full user story in the format above
- **persona**: Specific user role (e.g., "Customer", "Admin", "Guest User")
- **goal**: What the user wants to accomplish
- **gherkin_acceptance_criteria**: Acceptance criteria in Gherkin format (Given-When-Then)
- **nfrs**: List of non-functional requirements (performance, security, usability, etc.)

# Gherkin Format

Acceptance criteria MUST use proper Gherkin syntax:

```gherkin
Scenario: [Scenario name]
  Given [precondition]
  When [action]
  Then [expected result]
  And [additional result]
```

Include multiple scenarios if needed to cover edge cases.

# Non-Functional Requirements

Consider and include relevant NFRs:
- **Performance**: Response time, throughput, scalability
- **Security**: Authentication, authorization, data protection
- **Usability**: Accessibility, user experience, error handling
- **Reliability**: Uptime, error recovery, data integrity
- **Maintainability**: Code quality, documentation, testability

# Story Splitting Guidelines

If a feature is too large, split it into smaller stories:
- Split by user persona
- Split by CRUD operations (Create, Read, Update, Delete)
- Split by happy path vs. edge cases
- Split by UI vs. API vs. data layer

# Quality Checklist

Before outputting, verify each story:
- [ ] Follows "As a... I want... So that..." format
- [ ] Is independent and can be delivered alone
- [ ] Provides clear value to users
- [ ] Can be estimated by development team
- [ ] Is small enough for one sprint
- [ ] Has testable acceptance criteria in Gherkin format
- [ ] Includes relevant NFRs

# Output Format

Return a JSON array of stories. Example:

```json
[
  {
    "title": "User Registration",
    "description": "As a new visitor\\nI want to create an account\\nSo that I can access personalized features",
    "persona": "New Visitor",
    "goal": "Create an account to access personalized features",
    "gherkin_acceptance_criteria": "Scenario: Successful registration\\n  Given I am on the registration page\\n  When I enter valid email and password\\n  And I click the 'Sign Up' button\\n  Then I should see a confirmation message\\n  And I should receive a verification email",
    "nfrs": [
      "Password must be hashed using bcrypt",
      "Email verification required within 24 hours",
      "Registration form must be accessible (WCAG 2.1 AA)",
      "Response time < 2 seconds"
    ]
  }
]
```

IMPORTANT: Output ONLY the JSON array, no additional text or markdown formatting.
"""
    
    async def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Generate INVEST-compliant stories from features"""
        features = state.get("features", [])
        
        if not features:
            logger.warning("No features provided to StoryAgent")
            state["error"] = "No features provided"
            return state
        
        logger.info(f"Generating stories for {len(features)} features")
        
        # Build detailed prompt with features
        features_text = ""
        for i, feature in enumerate(features, 1):
            features_text += f"\n## Feature {i}: {feature.get('title', 'Untitled')}\n"
            features_text += f"Description: {feature.get('description', 'N/A')}\n"
            features_text += f"Business Value: {feature.get('business_value', 'N/A')}\n"
            features_text += f"Actors: {', '.join(feature.get('actors', []))}\n"
            
            # Include acceptance criteria if available
            if feature.get('acceptance_criteria'):
                features_text += f"Acceptance Criteria:\n"
                for criterion in feature.get('acceptance_criteria', []):
                    features_text += f"  - {criterion}\n"
        
        prompt = f"""Generate INVEST-compliant user stories for the following features.

Create 1-3 stories per feature, ensuring each story is:
- Independent and deliverable on its own
- Small enough to complete in one sprint
- Valuable to end users
- Testable with clear acceptance criteria

{features_text}

Remember:
1. Use proper "As a... I want... So that..." format
2. Include Gherkin acceptance criteria (Given-When-Then)
3. Add relevant non-functional requirements
4. Keep stories small and focused
5. Output ONLY the JSON array, no markdown formatting

Output the stories as a JSON array."""
        
        try:
            response = await self.llm_client.generate(
                prompt,
                system_prompt=self.SYSTEM_PROMPT
            )
            
            logger.debug(f"StoryAgent raw response: {response[:200]}...")
            
            # Parse stories from response
            stories = []
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
                    for s in parsed:
                        if isinstance(s, dict):
                            # Validate required fields
                            if not all(key in s for key in ['title', 'description', 'persona', 'goal']):
                                logger.warning(f"Story missing required fields: {s.get('title', 'Unknown')}")
                                continue
                            
                            # Ensure gherkin_acceptance_criteria exists
                            if 'gherkin_acceptance_criteria' not in s:
                                s['gherkin_acceptance_criteria'] = "Scenario: To be defined\n  Given [precondition]\n  When [action]\n  Then [expected result]"
                            
                            # Ensure nfrs is a list
                            if 'nfrs' not in s:
                                s['nfrs'] = []
                            elif isinstance(s['nfrs'], str):
                                s['nfrs'] = [s['nfrs']]
                            
                            stories.append(Story(**s))
                        else:
                            logger.warning(f"Invalid story format: {type(s)}")
                            
                elif isinstance(parsed, dict):
                    if "stories" in parsed:
                        for s in parsed["stories"]:
                            if isinstance(s, dict):
                                # Same validation as above
                                if not all(key in s for key in ['title', 'description', 'persona', 'goal']):
                                    continue
                                if 'gherkin_acceptance_criteria' not in s:
                                    s['gherkin_acceptance_criteria'] = "Scenario: To be defined\n  Given [precondition]\n  When [action]\n  Then [expected result]"
                                if 'nfrs' not in s:
                                    s['nfrs'] = []
                                elif isinstance(s['nfrs'], str):
                                    s['nfrs'] = [s['nfrs']]
                                stories.append(Story(**s))
                    else:
                        logger.warning(f"Unexpected response format: {parsed.keys()}")
                        
            except (json.JSONDecodeError, TypeError) as e:
                logger.error(f"Could not parse StoryAgent response as JSON: {e}")
                logger.error(f"Response was: {response[:500]}...")
                state["error"] = f"Failed to parse story response: {str(e)}"
                return state
            
            if not stories:
                logger.warning("No valid stories generated")
                state["error"] = "No valid stories could be generated"
                return state
            
            # Convert stories to dicts
            state["stories"] = [s.dict() for s in stories]
            logger.info(f"StoryAgent successfully created {len(stories)} stories")
            
            # Log story titles for debugging
            for story in stories:
                logger.debug(f"  - {story.title}")
            
        except Exception as e:
            logger.error(f"Error in StoryAgent: {e}")
            import traceback
            logger.error(traceback.format_exc())
            state["error"] = str(e)
        
        return state


    
    @staticmethod
    def validate_invest_compliance(story: Story) -> Dict[str, Any]:
        """
        Validate that a story meets INVEST criteria
        
        Returns:
            Dict with 'compliant' (bool) and 'issues' (list of strings)
        """
        issues = []
        
        # Independent: Check if story has dependencies mentioned
        description_lower = story.description.lower()
        if any(word in description_lower for word in ['depends on', 'requires', 'after', 'before']):
            issues.append("Story may not be independent - mentions dependencies")
        
        # Negotiable: Check if story is too prescriptive
        if any(word in description_lower for word in ['must use', 'exactly', 'specifically']):
            issues.append("Story may be too prescriptive - should be negotiable")
        
        # Valuable: Check if story explains value/benefit
        if 'so that' not in description_lower and 'in order to' not in description_lower:
            issues.append("Story should explain value/benefit (use 'So that...')")
        
        # Estimable: Check if story has enough detail
        if len(story.description) < 50:
            issues.append("Story may be too vague to estimate")
        
        if not story.gherkin_acceptance_criteria or len(story.gherkin_acceptance_criteria) < 20:
            issues.append("Story needs clear acceptance criteria to be estimable")
        
        # Small: Check if story seems too large
        word_count = len(story.description.split())
        if word_count > 100:
            issues.append("Story may be too large - consider splitting")
        
        # Count scenarios in acceptance criteria
        scenario_count = story.gherkin_acceptance_criteria.lower().count('scenario:')
        if scenario_count > 5:
            issues.append("Too many scenarios - story may be too large")
        
        # Testable: Check if acceptance criteria are present
        if not story.gherkin_acceptance_criteria:
            issues.append("Story must have testable acceptance criteria")
        elif 'given' not in story.gherkin_acceptance_criteria.lower():
            issues.append("Acceptance criteria should use Gherkin format (Given-When-Then)")
        
        return {
            'compliant': len(issues) == 0,
            'issues': issues,
            'criteria_checked': ['Independent', 'Negotiable', 'Valuable', 'Estimable', 'Small', 'Testable']
        }
    
    @staticmethod
    def validate_gherkin_format(gherkin_text: str) -> Dict[str, Any]:
        """
        Validate that acceptance criteria follow Gherkin format
        
        Returns:
            Dict with 'valid' (bool) and 'issues' (list of strings)
        """
        issues = []
        gherkin_lower = gherkin_text.lower()
        
        # Check for required keywords
        if 'scenario:' not in gherkin_lower:
            issues.append("Missing 'Scenario:' keyword")
        
        if 'given' not in gherkin_lower:
            issues.append("Missing 'Given' step (precondition)")
        
        if 'when' not in gherkin_lower:
            issues.append("Missing 'When' step (action)")
        
        if 'then' not in gherkin_lower:
            issues.append("Missing 'Then' step (expected result)")
        
        # Check for proper indentation (basic check)
        lines = gherkin_text.split('\n')
        for line in lines:
            stripped = line.strip().lower()
            if stripped.startswith(('given', 'when', 'then', 'and', 'but')):
                if not line.startswith('  '):
                    issues.append("Gherkin steps should be indented")
                    break
        
        return {
            'valid': len(issues) == 0,
            'issues': issues
        }
