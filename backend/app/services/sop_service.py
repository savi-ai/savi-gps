"""SOP Management Service"""
import yaml
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from app.core.config import settings
from app.core.models import SOP, SOPCategory, ArtifactType
from app.core.logger import logger


class SOPService:
    """Service for managing and loading SOPs"""
    
    def __init__(self):
        self.sops: Dict[str, SOP] = {}
        self.sop_directory = Path(settings.SOP_DIRECTORY)
        self.schema_path = Path(settings.SOP_SCHEMA_PATH)
        self._load_sops()
    
    def _load_sops(self):
        """Load SOPs from YAML files in the configured directory"""
        if not self.sop_directory.exists():
            logger.warning(f"SOP directory does not exist: {self.sop_directory}. Creating it.")
            self.sop_directory.mkdir(parents=True, exist_ok=True)
            return
        
        for sop_file in self.sop_directory.glob("*.yaml"):
            try:
                with open(sop_file, 'r') as f:
                    sop_data = yaml.safe_load(f)
                    sop = SOP(**sop_data)
                    self.sops[sop.id] = sop
                    logger.info(f"Loaded SOP: {sop.id} - {sop.title}")
            except Exception as e:
                logger.error(f"Error loading SOP from {sop_file}: {e}")
    
    def get_all_sops(self) -> List[SOP]:
        """Get all SOPs"""
        return list(self.sops.values())
    
    def get_sop(self, sop_id: str) -> Optional[SOP]:
        """Get SOP by ID"""
        return self.sops.get(sop_id)
    
    def filter_sops(
        self,
        category: Optional[SOPCategory] = None,
        applies_to: Optional[ArtifactType] = None,
        tags: Optional[List[str]] = None
    ) -> List[SOP]:
        """Filter SOPs by category, applies_to, or tags"""
        filtered = list(self.sops.values())
        
        if category:
            filtered = [sop for sop in filtered if sop.category == category]
        
        if applies_to:
            filtered = [sop for sop in filtered if applies_to in sop.applies_to]
        
        if tags:
            filtered = [
                sop for sop in filtered
                if any(tag in sop.tags for tag in tags)
            ]
        
        return filtered
    
    def reload_sops(self):
        """Reload SOPs from directory"""
        self.sops.clear()
        self._load_sops()


# Global instance
sop_service = SOPService()

