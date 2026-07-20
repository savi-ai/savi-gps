"""Manage tenant GitHub credentials (encrypted PAT storage)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy.orm import Session

from app.core.database import GitHubCredential
from app.core.logger import logger
from app.services.intelligence.github_client import GitHubClient, GitHubApiError
from app.services.intelligence.token_cipher import decrypt_token, encrypt_token


class GitHubCredentialService:
    def __init__(self, db: Session):
        self.db = db

    def list_credentials(self, tenant_id: str) -> List[GitHubCredential]:
        return (
            self.db.query(GitHubCredential)
            .filter(
                GitHubCredential.tenant_id == tenant_id,
                GitHubCredential.is_active == True,
            )
            .order_by(GitHubCredential.created_at.desc())
            .all()
        )

    def get_credential(self, tenant_id: str, credential_id: str) -> Optional[GitHubCredential]:
        return (
            self.db.query(GitHubCredential)
            .filter(
                GitHubCredential.id == credential_id,
                GitHubCredential.tenant_id == tenant_id,
                GitHubCredential.is_active == True,
            )
            .first()
        )

    def get_token(self, credential: GitHubCredential) -> Optional[str]:
        return decrypt_token(credential.token_encrypted)

    async def validate_and_store(
        self,
        tenant_id: str,
        token: str,
        label: str,
        created_by: Optional[str],
    ) -> GitHubCredential:
        client = GitHubClient(token)
        try:
            info = await client.validate_token()
        except GitHubApiError as e:
            raise ValueError(e.message) from e

        cred = GitHubCredential(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            label=label or f"GitHub ({info.get('login')})",
            token_encrypted=encrypt_token(token),
            github_login=info.get("login"),
            github_name=info.get("name"),
            scopes=info.get("scopes") or [],
            last_validated_at=datetime.now(),
            created_by=created_by,
        )
        self.db.add(cred)
        self.db.commit()
        self.db.refresh(cred)
        logger.info(f"Stored GitHub credential {cred.id} for tenant {tenant_id}")
        return cred

    async def revalidate(self, credential: GitHubCredential) -> GitHubCredential:
        token = self.get_token(credential)
        if not token:
            raise ValueError("Stored credential could not be decrypted")
        client = GitHubClient(token)
        info = await client.validate_token()
        credential.github_login = info.get("login")
        credential.github_name = info.get("name")
        credential.scopes = info.get("scopes") or []
        credential.last_validated_at = datetime.now()
        self.db.commit()
        self.db.refresh(credential)
        return credential

    def deactivate(self, tenant_id: str, credential_id: str) -> bool:
        cred = self.get_credential(tenant_id, credential_id)
        if not cred:
            return False
        cred.is_active = False
        self.db.commit()
        return True

    def to_dict(self, cred: GitHubCredential) -> Dict[str, Any]:
        return {
            "id": cred.id,
            "label": cred.label,
            "github_login": cred.github_login,
            "github_name": cred.github_name,
            "scopes": cred.scopes or [],
            "last_validated_at": cred.last_validated_at.isoformat() if cred.last_validated_at else None,
            "created_at": cred.created_at.isoformat() if cred.created_at else None,
        }

    async def client_for_credential(self, credential: GitHubCredential) -> GitHubClient:
        token = self.get_token(credential)
        if not token:
            raise ValueError("Stored credential could not be decrypted")
        return GitHubClient(token)
