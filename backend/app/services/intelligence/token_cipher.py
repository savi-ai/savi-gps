"""Encrypt/decrypt GitHub PATs at rest using Fernet derived from app SECRET_KEY."""
import base64
import hashlib
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings
from app.core.logger import logger


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_token(token: str) -> str:
    return _fernet().encrypt(token.encode("utf-8")).decode("utf-8")


def decrypt_token(token_encrypted: str) -> Optional[str]:
    try:
        return _fernet().decrypt(token_encrypted.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        logger.error("Failed to decrypt GitHub token — invalid cipher or SECRET_KEY changed")
        return None
