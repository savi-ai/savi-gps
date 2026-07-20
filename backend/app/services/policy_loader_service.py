"""Policy Loader Service - Loads default policies from markdown files"""
import re
import uuid
from pathlib import Path
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from app.core.database import Policy, PolicyVersion, PolicyCategory
from app.core.logger import logger
from datetime import datetime


class PolicyLoaderService:
    """Service for loading default policies from markdown files"""
    
    def __init__(self, db: Session):
        self.db = db
        self.default_policies_dir = Path(__file__).parent.parent.parent.parent / "docs" / "default_agentic_ai_policies"
    
    def parse_policy_markdown(self, file_path: Path) -> Dict[str, Any]:
        """
        Parse markdown policy file into structured data
        
        Args:
            file_path: Path to the markdown file
            
        Returns:
            Dictionary with policy metadata and content
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Extract title (first H1)
            title_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
            title = title_match.group(1).strip() if title_match else file_path.stem
            
            # Extract sections
            sections = {}
            current_section = None
            current_content = []
            
            for line in content.split('\n'):
                # Check for H2 headers (sections)
                h2_match = re.match(r'^##\s+(.+)$', line)
                if h2_match:
                    # Save previous section
                    if current_section:
                        sections[current_section] = '\n'.join(current_content).strip()
                    # Start new section
                    current_section = h2_match.group(1).strip()
                    current_content = []
                elif current_section:
                    current_content.append(line)
            
            # Save last section
            if current_section:
                sections[current_section] = '\n'.join(current_content).strip()
            
            # Determine category from filename
            category_map = {
                '01_idea_ideation_policy.md': 'ideation',
                '02_requirements_and_features_policy.md': 'requirements',
                '03_coding_standards_policy.md': 'coding',
                '04_architectural_standards_policy.md': 'architecture',
                '05_testing_and_pipeline_standards_policy.md': 'testing'
            }
            
            category = category_map.get(file_path.name, 'general')
            
            # Generate policy ID from filename
            policy_id = file_path.stem.upper().replace('_', '-')
            
            # Extract description from Purpose section
            description = sections.get('Purpose', sections.get('Objectives', ''))
            if not description:
                # Use first paragraph after title
                first_para = content.split('\n\n')[1] if len(content.split('\n\n')) > 1 else ''
                description = first_para.strip()
            
            # Determine applies_to based on category
            applies_to_map = {
                'ideation': ['idea'],
                'requirements': ['features'],
                'architecture': ['architecture'],
                'coding': ['backend', 'frontend', 'code'],
                'testing': ['tests', 'testing']
            }
            applies_to = applies_to_map.get(category, [])
            
            return {
                'policy_id': policy_id,
                'name': title,
                'description': description[:500] if description else '',  # Limit description length
                'category': category,
                'content': sections,
                'content_markdown': content,
                'applies_to': applies_to,
                'file_path': str(file_path)
            }
            
        except Exception as e:
            logger.error(f"Error parsing policy file {file_path}: {e}")
            raise
    
    def create_policy_categories(self) -> None:
        """Create default policy categories if they don't exist"""
        categories = [
            {
                'name': 'ideation',
                'display_name': 'Idea & Ideation',
                'description': 'Policies for idea generation and refinement'
            },
            {
                'name': 'requirements',
                'display_name': 'Requirements & Features',
                'description': 'Policies for requirements and feature generation'
            },
            {
                'name': 'stories',
                'display_name': 'User Stories',
                'description': 'Policies for user story creation'
            },
            {
                'name': 'architecture',
                'display_name': 'Architecture',
                'description': 'Policies for system architecture design'
            },
            {
                'name': 'coding',
                'display_name': 'Coding Standards',
                'description': 'Policies for code generation and quality'
            },
            {
                'name': 'testing',
                'display_name': 'Testing & QA',
                'description': 'Policies for testing and quality assurance'
            },
            {
                'name': 'security',
                'display_name': 'Security',
                'description': 'Security policies and standards'
            },
            {
                'name': 'infrastructure',
                'display_name': 'Infrastructure',
                'description': 'Infrastructure and deployment policies'
            }
        ]
        
        for cat_data in categories:
            # Check if category exists
            existing = self.db.query(PolicyCategory).filter(
                PolicyCategory.name == cat_data['name']
            ).first()
            
            if not existing:
                category = PolicyCategory(
                    id=str(uuid.uuid4()),
                    name=cat_data['name'],
                    display_name=cat_data['display_name'],
                    description=cat_data['description']
                )
                self.db.add(category)
                logger.info(f"Created policy category: {cat_data['name']}")
        
        self.db.commit()
    
    def load_default_policies(self, tenant_id: Optional[str] = None) -> List[Policy]:
        """
        Load default policies from markdown files
        
        Args:
            tenant_id: Optional tenant ID. If None, creates system-level policies
            
        Returns:
            List of created Policy objects
        """
        if not self.default_policies_dir.exists():
            logger.warning(f"Default policies directory does not exist: {self.default_policies_dir}")
            return []
        
        # First, ensure policy categories exist
        self.create_policy_categories()
        
        policies = []
        
        # Get all markdown files
        policy_files = sorted(self.default_policies_dir.glob("*.md"))
        
        for policy_file in policy_files:
            try:
                # Parse the markdown file
                policy_data = self.parse_policy_markdown(policy_file)
                
                # Check if policy already exists
                existing_policy = self.db.query(Policy).filter(
                    Policy.policy_id == policy_data['policy_id'],
                    Policy.tenant_id == tenant_id
                ).first()
                
                if existing_policy:
                    logger.info(f"Policy {policy_data['policy_id']} already exists, skipping")
                    policies.append(existing_policy)
                    continue
                
                # Create policy
                policy = Policy(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    policy_id=policy_data['policy_id'],
                    name=policy_data['name'],
                    description=policy_data['description'],
                    category=policy_data['category'],
                    status='active',  # Default policies are active
                    applies_to=policy_data['applies_to'],
                    stacks=[],
                    tags=['default', 'system']
                )
                
                self.db.add(policy)
                self.db.flush()  # Get the policy ID
                
                # Create initial version
                version = PolicyVersion(
                    id=str(uuid.uuid4()),
                    policy_id=policy.id,
                    version_number='1.0.0',
                    content=policy_data['content'],
                    content_yaml=policy_data['content_markdown'],
                    storage_key=policy_data['file_path'],
                    is_draft=False,
                    requires_approval=False,
                    approved_at=datetime.now()
                )
                
                self.db.add(version)
                self.db.flush()
                
                # Set active version
                policy.active_version_id = version.id
                
                policies.append(policy)
                logger.info(f"Loaded policy: {policy_data['policy_id']} - {policy_data['name']}")
                
            except Exception as e:
                logger.error(f"Error loading policy from {policy_file}: {e}")
                continue
        
        self.db.commit()
        logger.info(f"Loaded {len(policies)} default policies")
        
        return policies
    
    def reload_policies(self, tenant_id: Optional[str] = None) -> List[Policy]:
        """
        Reload all default policies (useful for updates)
        
        Args:
            tenant_id: Optional tenant ID
            
        Returns:
            List of Policy objects
        """
        # Delete existing default policies for this tenant
        self.db.query(Policy).filter(
            Policy.tenant_id == tenant_id,
            Policy.tags.contains(['default'])
        ).delete(synchronize_session=False)
        
        self.db.commit()
        
        # Load fresh policies
        return self.load_default_policies(tenant_id)
    
    def get_policy_by_category(self, category: str, tenant_id: Optional[str] = None) -> List[Policy]:
        """
        Get all policies for a specific category
        
        Args:
            category: Policy category name
            tenant_id: Optional tenant ID
            
        Returns:
            List of Policy objects
        """
        query = self.db.query(Policy).filter(
            Policy.category == category,
            Policy.status == 'active'
        )
        
        if tenant_id:
            query = query.filter(Policy.tenant_id == tenant_id)
        else:
            query = query.filter(Policy.tenant_id.is_(None))
        
        return query.all()
