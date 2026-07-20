"""Authentication and authorization utilities"""
from datetime import datetime, timedelta
from typing import Optional, List
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Security
from fastapi.security import OAuth2PasswordBearer, APIKeyHeader
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.database import get_db, User, Role, UserRole
from app.core.logger import logger
import uuid

# API Key header for backward compatibility
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Password hashing context
# Configure bcrypt with proper settings to handle password length limits
# Disable version detection to avoid initialization errors
try:
    pwd_context = CryptContext(
        schemes=["bcrypt"],
        bcrypt__rounds=12,
        deprecated="auto"
    )
    # Force initialization by hashing a test password
    _ = pwd_context.hash("test")
except Exception as e:
    # If initialization fails, create a simpler context
    logger.warning(f"Bcrypt initialization warning (non-fatal): {e}")
    pwd_context = CryptContext(
        schemes=["bcrypt"],
        bcrypt__rounds=12,
        deprecated="auto"
    )

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_PREFIX}/auth/login")

# Role definitions
ROLES = {
    "product_manager": "Product Manager",
    "architect": "Architect", 
    "developer": "Developer",
    "qa": "QA",
    "admin": "Admin"
}

# Role-based permissions
ROLE_PERMISSIONS = {
    "product_manager": {
        "can_create_project": True,
        "can_use_idea_agent": True,
        "can_use_product_manager_agent": True,
        "can_use_story_agent": True,
        "can_use_architecture_agent": False,
        "can_use_developer_agent": False,
        "can_use_testing_agent": False,
        "can_use_intelligence": True,
        "can_view_portfolio": True,
        "can_modify_others": False,
        "can_view_all": True
    },
    "architect": {
        "can_create_project": False,
        "can_use_idea_agent": True,
        "can_use_product_manager_agent": False,
        "can_use_story_agent": False,
        "can_use_architecture_agent": True,
        "can_use_developer_agent": False,
        "can_use_testing_agent": False,
        "can_use_intelligence": True,
        "can_approve_wiki": True,
        "can_view_portfolio": True,
        "can_manage_modernize": True,
        "can_modify_others": False,
        "can_view_all": True
    },
    "developer": {
        "can_create_project": False,
        "can_use_idea_agent": False,
        "can_use_product_manager_agent": False,
        "can_use_story_agent": False,
        "can_use_architecture_agent": False,
        "can_use_developer_agent": True,
        "can_use_testing_agent": True,
        "can_use_intelligence": True,
        "can_modify_others": False,
        "can_view_all": True
    },
    "qa": {
        "can_create_project": False,
        "can_use_idea_agent": False,
        "can_use_product_manager_agent": False,
        "can_use_story_agent": False,
        "can_use_architecture_agent": False,
        "can_use_developer_agent": False,
        "can_use_testing_agent": True,
        "can_modify_others": False,
        "can_view_all": True
    },
    "admin": {
        "can_create_project": True,
        "can_use_idea_agent": True,
        "can_use_product_manager_agent": True,
        "can_use_story_agent": True,
        "can_use_architecture_agent": True,
        "can_use_developer_agent": True,
        "can_use_testing_agent": True,
        "can_use_intelligence": True,
        "can_approve_wiki": True,
        "can_manage_fleet": True,
        "can_manage_tenant_config": True,
        "can_view_portfolio": True,
        "can_manage_modernize": True,
        "can_modify_others": True,
        "can_view_all": True,
        "can_manage_policies": True,
        "can_manage_building_blocks": True,
        "can_manage_users": True
    }
}


def verify_password(plain_password: str, stored_password: str) -> bool:
    """Verify a password against stored hash"""
    if not stored_password:
        return False
    
    # If stored_password looks like a bcrypt hash (starts with $2b$ or $2a$), verify it
    if stored_password.startswith("$2b$") or stored_password.startswith("$2a$"):
        try:
            from passlib.context import CryptContext
            pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
            return pwd_context.verify(plain_password, stored_password)
        except Exception as e:
            logger.warning(f"Passlib verification failed, trying direct bcrypt: {e}")
            try:
                import bcrypt
                return bcrypt.checkpw(plain_password.encode('utf-8'), stored_password.encode('utf-8'))
            except Exception as bcrypt_error:
                logger.error(f"Bcrypt verification failed: {bcrypt_error}")
                return False
    
    # Fallback to plain text comparison for backwards compatibility (temporary)
    # This allows existing plain text passwords to still work
    return plain_password == stored_password


def get_password_hash(password: str) -> str:
    """Hash a password - bcrypt has a 72-byte limit"""
    # Ensure password is within bcrypt's 72-byte limit
    # Convert to bytes first to check actual byte length
    password_bytes = password.encode('utf-8')
    
    if len(password_bytes) > 72:
        # Truncate to exactly 72 bytes
        password_bytes = password_bytes[:72]
        # Decode back to string, handling any incomplete UTF-8 sequences
        try:
            password = password_bytes.decode('utf-8')
        except UnicodeDecodeError:
            # If truncation broke a UTF-8 sequence, remove the last byte and try again
            password_bytes = password_bytes[:71]
            password = password_bytes.decode('utf-8', errors='ignore')
        logger.warning("Password truncated to 72 bytes due to bcrypt limitation")
    
    # Double-check the byte length before hashing - ensure it's exactly 72 bytes or less
    final_bytes = password.encode('utf-8')
    if len(final_bytes) > 72:
        # Force truncation to exactly 72 bytes
        final_bytes = final_bytes[:72]
        password = final_bytes.decode('utf-8', errors='ignore')
        # One more check to be absolutely sure
        verify_bytes = password.encode('utf-8')
        if len(verify_bytes) > 72:
            password = verify_bytes[:72].decode('utf-8', errors='ignore')
    
    # Final verification before hashing
    final_check_bytes = password.encode('utf-8')
    if len(final_check_bytes) > 72:
        # Emergency: take exactly 72 bytes
        password = final_check_bytes[:72].decode('utf-8', errors='ignore')
    
    # Final byte length check before hashing
    final_byte_check = password.encode('utf-8')
    if len(final_byte_check) > 72:
        password = final_byte_check[:72].decode('utf-8', errors='ignore')
    
    # Try passlib first, fallback to direct bcrypt if it fails
    try:
        return pwd_context.hash(password)
    except (ValueError, TypeError, AttributeError) as e:
        # If passlib fails (e.g., due to version detection issues), use direct bcrypt
        actual_len = len(password.encode('utf-8'))
        error_str = str(e).lower()
        
        # Check if it's actually a length error
        if actual_len > 72:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Password is too long ({actual_len} bytes). Maximum is 72 bytes."
            )
        
        # If password is valid length, use direct bcrypt as fallback
        if actual_len <= 72:
            try:
                import bcrypt
                # Generate salt and hash directly
                salt = bcrypt.gensalt(rounds=12)
                hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
                return hashed.decode('utf-8')
            except ImportError:
                logger.error("Bcrypt module not available")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Password hashing service unavailable"
                )
            except Exception as bcrypt_error:
                logger.error(f"Direct bcrypt error: {bcrypt_error}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Error processing password. Please try again."
                )
        
        # Re-raise if we can't handle it
        raise
    except Exception as e:
        logger.error(f"Password hashing error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error hashing password"
        )


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """Decode and verify a JWT token"""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        return None


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    """Get the current authenticated user from JWT token"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception
    
    user_id: str = payload.get("sub")
    tenant_id: str = payload.get("tenant_id")
    
    if user_id is None:
        raise credentials_exception
    
    # Filter by tenant_id if present in token (for multi-tenant support)
    query = db.query(User).filter(User.id == user_id)
    if tenant_id:
        query = query.filter(User.tenant_id == tenant_id)
    
    user = query.first()
    if user is None:
        raise credentials_exception
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive"
        )
    
    return user


async def get_user_roles(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> List[str]:
    """Get list of role names for the current user"""
    user_roles = db.query(UserRole).join(Role).filter(UserRole.user_id == user.id).all()
    role_names = [db.query(Role).filter(Role.id == ur.role_id).first().name for ur in user_roles]
    return role_names


def has_permission(user: User, permission: str, db: Session) -> bool:
    """Check if user has a specific permission based on their roles"""
    user_roles = db.query(UserRole).join(Role).filter(UserRole.user_id == user.id).all()
    
    for user_role in user_roles:
        role = db.query(Role).filter(Role.id == user_role.role_id).first()
        if role and role.name in ROLE_PERMISSIONS:
            permissions = ROLE_PERMISSIONS[role.name]
            if permissions.get(permission, False):
                return True
    return False


def get_user_permissions(user: User, db: Session) -> List[str]:
    """Return merged permission keys granted to the user across all roles."""
    granted: set[str] = set()
    user_roles = db.query(UserRole).join(Role).filter(UserRole.user_id == user.id).all()
    for user_role in user_roles:
        role = db.query(Role).filter(Role.id == user_role.role_id).first()
        if role and role.name in ROLE_PERMISSIONS:
            for key, allowed in ROLE_PERMISSIONS[role.name].items():
                if allowed:
                    granted.add(key)
    return sorted(granted)


def require_permission(permission: str):
    """Dependency to require a specific permission"""
    async def permission_checker(
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
    ) -> User:
        if not has_permission(user, permission, db):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {permission}"
            )
        return user
    return permission_checker


def require_role(role_name: str):
    """Dependency to require a specific role"""
    async def role_checker(
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db)
    ) -> User:
        user_roles = db.query(UserRole).join(Role).filter(
            UserRole.user_id == user.id,
            Role.name == role_name
        ).first()
        
        if not user_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role required: {role_name}"
            )
        return user
    return role_checker


def create_default_roles(db: Session):
    """Create default roles if they don't exist"""
    for role_key, role_name in ROLES.items():
        existing_role = db.query(Role).filter(Role.name == role_key).first()
        if not existing_role:
            role = Role(
                id=str(uuid.uuid4()),
                name=role_key,
                description=f"{role_name} role for GPS"
            )
            db.add(role)
    db.commit()


# Backward compatibility: API Key authentication (for legacy endpoints)
async def verify_api_key(api_key: str = Security(api_key_header)) -> bool:
    """Verify API key for protected endpoints (backward compatibility)"""
    if not settings.API_KEY:
        # If no API key is configured, allow access in development
        if settings.ENVIRONMENT == "development":
            return True
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key not configured"
        )
    
    if api_key != settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )
    
    return True
