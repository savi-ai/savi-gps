"""Storage service - local filesystem implementation that mimics S3 structure"""
import os
import json
import yaml
from pathlib import Path
from typing import Optional, BinaryIO, Dict, Any
from datetime import datetime
import uuid
from app.core.config import settings
from app.core.logger import logger


class StorageService:
    """Storage service that mimics S3 folder structure using local filesystem"""
    
    def __init__(self, base_path: Optional[str] = None):
        """
        Initialize storage service
        
        Args:
            base_path: Base directory for storage (defaults to ./storage in project root)
        """
        if base_path:
            self.base_path = Path(base_path)
        elif settings.STORAGE_BASE_PATH:
            self.base_path = Path(settings.STORAGE_BASE_PATH)
        else:
            # Default to ./storage in project root
            project_root = Path(__file__).parent.parent.parent
            self.base_path = project_root / "storage"
        
        self.base_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Storage service initialized at: {self.base_path} (type: {settings.STORAGE_TYPE})")
    
    def _get_tenant_path(self, tenant_id: str) -> Path:
        """Get base path for a tenant"""
        return self.base_path / "tenants" / tenant_id
    
    def _get_policy_path(self, tenant_id: str, policy_id: str, category: str, version: Optional[str] = None) -> Path:
        """
        Get path for a policy file
        
        Structure: tenants/{tenantId}/policy-bundles/baseline/{version}/policies/{category}/{policy_id}.yaml
        """
        tenant_path = self._get_tenant_path(tenant_id)
        if version:
            return tenant_path / "policy-bundles" / "baseline" / version / "policies" / category / f"{policy_id}.yaml"
        else:
            # For latest/draft versions, use a special "drafts" folder
            return tenant_path / "policy-bundles" / "drafts" / "policies" / category / f"{policy_id}.yaml"
    
    def _get_attachment_path(self, tenant_id: str, attachment_id: str, filename: str) -> Path:
        """
        Get path for an attachment file
        
        Structure: tenants/{tenantId}/policy-bundles/baseline/{version}/attachments/{filename}
        """
        tenant_path = self._get_tenant_path(tenant_id)
        # Store attachments in a common attachments folder
        return tenant_path / "attachments" / attachment_id / filename
    
    def _get_building_block_path(self, tenant_id: str, block_id: str, filename: Optional[str] = None) -> Path:
        """
        Get path for a building block file
        
        Structure: tenants/{tenantId}/policy-bundles/baseline/{version}/building-blocks/{block_id}/
        """
        tenant_path = self._get_tenant_path(tenant_id)
        if filename:
            return tenant_path / "building-blocks" / block_id / filename
        else:
            return tenant_path / "building-blocks" / block_id
    
    def _get_runtime_path(self, tenant_id: str) -> Path:
        """Get path for runtime files (active.json, cache, etc.)"""
        return self._get_tenant_path(tenant_id) / "runtime"
    
    def save_policy_content(
        self,
        tenant_id: str,
        policy_id: str,
        category: str,
        content: Dict[str, Any],
        version: Optional[str] = None,
        content_yaml: Optional[str] = None
    ) -> str:
        """
        Save policy content to storage
        
        Returns:
            Storage path/key (relative to base_path)
        """
        policy_path = self._get_policy_path(tenant_id, policy_id, category, version)
        policy_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Save as YAML if provided, otherwise save as JSON
        if content_yaml:
            with open(policy_path, 'w') as f:
                f.write(content_yaml)
        else:
            with open(policy_path, 'w') as f:
                yaml.dump(content, f, default_flow_style=False, sort_keys=False)
        
        # Return relative path for storage in database
        relative_path = policy_path.relative_to(self.base_path)
        logger.info(f"Saved policy content to: {relative_path}")
        return str(relative_path)
    
    def load_policy_content(
        self,
        tenant_id: str,
        policy_id: str,
        category: str,
        version: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Load policy content from storage"""
        policy_path = self._get_policy_path(tenant_id, policy_id, category, version)
        
        if not policy_path.exists():
            logger.warning(f"Policy file not found: {policy_path}")
            return None
        
        try:
            with open(policy_path, 'r') as f:
                content = yaml.safe_load(f)
                return content if content else {}
        except Exception as e:
            logger.error(f"Error loading policy content from {policy_path}: {e}")
            return None
    
    def load_policy_content_yaml(
        self,
        tenant_id: str,
        policy_id: str,
        category: str,
        version: Optional[str] = None
    ) -> Optional[str]:
        """Load policy content as raw YAML string"""
        policy_path = self._get_policy_path(tenant_id, policy_id, category, version)
        
        if not policy_path.exists():
            return None
        
        try:
            with open(policy_path, 'r') as f:
                return f.read()
        except Exception as e:
            logger.error(f"Error loading policy YAML from {policy_path}: {e}")
            return None
    
    def save_attachment(
        self,
        tenant_id: str,
        attachment_id: str,
        filename: str,
        file_content: bytes,
        content_type: Optional[str] = None
    ) -> str:
        """
        Save attachment file to storage
        
        Returns:
            Storage path/key (relative to base_path)
        """
        attachment_path = self._get_attachment_path(tenant_id, attachment_id, filename)
        attachment_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(attachment_path, 'wb') as f:
            f.write(file_content)
        
        relative_path = attachment_path.relative_to(self.base_path)
        logger.info(f"Saved attachment to: {relative_path}")
        return str(relative_path)
    
    def load_attachment(self, tenant_id: str, attachment_id: str, filename: str) -> Optional[bytes]:
        """Load attachment file from storage"""
        attachment_path = self._get_attachment_path(tenant_id, attachment_id, filename)
        
        if not attachment_path.exists():
            return None
        
        try:
            with open(attachment_path, 'rb') as f:
                return f.read()
        except Exception as e:
            logger.error(f"Error loading attachment from {attachment_path}: {e}")
            return None
    
    def delete_attachment(self, tenant_id: str, attachment_id: str, filename: str) -> bool:
        """Delete attachment file from storage"""
        attachment_path = self._get_attachment_path(tenant_id, attachment_id, filename)
        
        try:
            if attachment_path.exists():
                attachment_path.unlink()
                # Try to remove parent directory if empty
                try:
                    attachment_path.parent.rmdir()
                except OSError:
                    pass  # Directory not empty, that's fine
                return True
            return False
        except Exception as e:
            logger.error(f"Error deleting attachment from {attachment_path}: {e}")
            return False
    
    def save_building_block_file(
        self,
        tenant_id: str,
        block_id: str,
        filename: str,
        file_content: bytes
    ) -> str:
        """Save building block file to storage"""
        block_path = self._get_building_block_path(tenant_id, block_id, filename)
        block_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(block_path, 'wb') as f:
            f.write(file_content)
        
        relative_path = block_path.relative_to(self.base_path)
        logger.info(f"Saved building block file to: {relative_path}")
        return str(relative_path)
    
    def save_active_bundle_config(self, tenant_id: str, bundle_name: str, version: str, policy_ids: list) -> str:
        """
        Save active bundle configuration
        
        Structure: tenants/{tenantId}/runtime/active.json
        """
        runtime_path = self._get_runtime_path(tenant_id)
        runtime_path.mkdir(parents=True, exist_ok=True)
        
        config = {
            "bundle_name": bundle_name,
            "version": version,
            "policy_ids": policy_ids,
            "activated_at": datetime.now().isoformat()
        }
        
        active_file = runtime_path / "active.json"
        with open(active_file, 'w') as f:
            json.dump(config, f, indent=2)
        
        relative_path = active_file.relative_to(self.base_path)
        logger.info(f"Saved active bundle config to: {relative_path}")
        return str(relative_path)
    
    def load_active_bundle_config(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Load active bundle configuration"""
        runtime_path = self._get_runtime_path(tenant_id)
        active_file = runtime_path / "active.json"
        
        if not active_file.exists():
            return None
        
        try:
            with open(active_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading active bundle config from {active_file}: {e}")
            return None
    
    def get_storage_key(self, relative_path: str) -> str:
        """
        Convert relative path to storage key (S3-style)
        
        This makes it easy to migrate to S3 later - just use the same key structure
        """
        return relative_path.replace('\\', '/')  # Normalize path separators
    
    def delete_policy_content(
        self,
        tenant_id: str,
        policy_id: str,
        category: str,
        version: Optional[str] = None
    ) -> bool:
        """Delete policy content file"""
        policy_path = self._get_policy_path(tenant_id, policy_id, category, version)
        
        try:
            if policy_path.exists():
                policy_path.unlink()
                # Try to remove parent directories if empty
                try:
                    policy_path.parent.rmdir()  # category folder
                    policy_path.parent.parent.rmdir()  # policies folder
                except OSError:
                    pass  # Directories not empty, that's fine
                return True
            return False
        except Exception as e:
            logger.error(f"Error deleting policy content from {policy_path}: {e}")
            return False


# Global storage service instance
storage_service = StorageService()
