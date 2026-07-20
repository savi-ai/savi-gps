"""Authentication router"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.exceptions import RequestValidationError
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr, ValidationError
from typing import Optional, List
from app.core.database import get_db, User, Role, UserRole, Tenant
from app.core.auth import (
    verify_password,
    get_password_hash,
    create_access_token,
    get_current_user,
    get_user_roles,
    get_user_permissions,
    create_default_roles,
    ROLES
)
from app.core.config import settings
from app.core.logger import logger
import uuid

router = APIRouter(prefix="/auth", tags=["authentication"])


class UserRegister(BaseModel):
    """User registration model"""
    username: str
    email: EmailStr
    password: str
    full_name: Optional[str] = None
    role: str  # product_manager, architect, developer, qa
    tenant_id: Optional[str] = None


class UserResponse(BaseModel):
    """User response model"""
    id: str
    username: str
    email: str
    full_name: Optional[str]
    is_active: bool
    roles: List[str]
    tenant_id: Optional[str] = None
    permissions: List[str] = []


async def _build_user_response(user: User, db: Session) -> UserResponse:
    roles = await get_user_roles(user, db)
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        roles=roles,
        tenant_id=getattr(user, "tenant_id", None),
        permissions=get_user_permissions(user, db),
    )


class TokenResponse(BaseModel):
    """Token response model"""
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class LoginRequest(BaseModel):
    """Login request model"""
    username: str
    password: str
    tenant_id: Optional[str] = None


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserRegister,
    db: Session = Depends(get_db)
):
    """Register a new user"""
    logger.info(f"Registration attempt for username: {user_data.username}, email: {user_data.email}, role: {user_data.role}")
    
    # Basic password validation (plain text storage for now - hashing to be implemented later)
    logger.info(f"Password length: {len(user_data.password) if user_data.password else 0}")
    if not user_data.password or len(user_data.password) < 3:
        logger.warning(f"Password validation failed: length={len(user_data.password) if user_data.password else 0}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 3 characters long."
        )
    
    if len(user_data.password) > 200:
        logger.warning(f"Password too long: length={len(user_data.password)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password is too long. Maximum length is 200 characters."
        )
    
    # Validate role
    logger.info(f"Validating role: {user_data.role}, available roles: {list(ROLES.keys())}")
    if user_data.role not in ROLES:
        logger.warning(f"Invalid role: {user_data.role}, valid roles: {list(ROLES.keys())}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role '{user_data.role}'. Must be one of: {', '.join(ROLES.keys())}"
        )

    # Resolve tenant for registration
    tenant: Optional[Tenant] = None
    if user_data.tenant_id:
        tenant = db.query(Tenant).filter(
            Tenant.id == user_data.tenant_id,
            Tenant.is_active == True,
        ).first()
        if not tenant:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tenant not found or inactive",
            )
    else:
        tenant = db.query(Tenant).filter(Tenant.is_active == True).order_by(Tenant.name).first()
        if not tenant:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No active tenant available for registration",
            )
    
    # Check if username exists
    logger.info(f"Checking if username exists: {user_data.username}")
    existing_user = db.query(User).filter(User.username == user_data.username).first()
    if existing_user:
        logger.warning(f"Username already exists: {user_data.username}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )
    
    # Check if email exists in this tenant
    logger.info(f"Checking if email exists: {user_data.email} in tenant {tenant.id}")
    existing_email = db.query(User).filter(
        User.email == user_data.email,
        User.tenant_id == tenant.id
    ).first()
    if existing_email:
        logger.warning(f"Email already exists: {user_data.email} in tenant {tenant.id}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered in this tenant"
        )
    
    # Create default roles if they don't exist
    logger.info("Creating default roles if needed")
    create_default_roles(db)
    
    # Create user
    logger.info("Creating user record")
    user_id = str(uuid.uuid4())
    password_hash = get_password_hash(user_data.password)
    logger.info(f"Password hash generated, length: {len(password_hash)}")
    
    user = User(
        id=user_id,
        tenant_id=tenant.id,
        username=user_data.username,
        email=user_data.email,
        password_hash=password_hash,
        full_name=user_data.full_name,
        is_active=True
    )
    db.add(user)
    db.flush()
    logger.info(f"User created with ID: {user_id}")
    
    # Assign role
    logger.info(f"Looking up role: {user_data.role}")
    role = db.query(Role).filter(Role.name == user_data.role).first()
    if not role:
        logger.error(f"Role {user_data.role} not found in database")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Role {user_data.role} not found. Available roles: {[r.name for r in db.query(Role).all()]}"
        )
    
    logger.info(f"Role found: {role.id}, assigning to user")
    user_role = UserRole(
        id=str(uuid.uuid4()),
        user_id=user_id,
        role_id=role.id
    )
    db.add(user_role)
    db.commit()
    db.refresh(user)
    logger.info(f"User registration successful: {user_id}")
    
    return await _build_user_response(user, db)


@router.post("/login", response_model=TokenResponse)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """Login and get access token"""
    from sqlalchemy import inspect
    
    # Check if tenant_id column exists
    inspector = inspect(db.bind)
    user_columns = [col['name'] for col in inspector.get_columns('users')]
    has_tenant_id = 'tenant_id' in user_columns
    
    # Query user (handle missing tenant_id column)
    try:
        user = db.query(User).filter(User.username == form_data.username).first()
    except Exception as e:
        # If query fails due to missing column, use raw SQL
        if 'tenant_id' in str(e):
            from sqlalchemy import text
            result = db.execute(text("SELECT * FROM users WHERE username = :username"), {"username": form_data.username})
            row = result.fetchone()
            if row:
                # Create a minimal user object
                user = User()
                user.id = row[0]
                user.username = row[1] if len(row) > 1 else form_data.username
                user.email = row[2] if len(row) > 2 else ""
                user.password_hash = row[3] if len(row) > 3 else ""
                user.full_name = row[4] if len(row) > 4 else None
                user.is_active = row[5] if len(row) > 5 else True
                if has_tenant_id and len(row) > 6:
                    user.tenant_id = row[6]
            else:
                user = None
        else:
            raise
    
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive"
        )
    
    # Create access token with tenant_id if available
    token_data = {"sub": user.id}
    if has_tenant_id and hasattr(user, 'tenant_id') and user.tenant_id:
        token_data["tenant_id"] = user.tenant_id
    access_token = create_access_token(data=token_data)
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=await _build_user_response(user, db),
    )


@router.post("/login-json", response_model=TokenResponse)
async def login_json(
    login_data: LoginRequest,
    db: Session = Depends(get_db)
):
    """Login with JSON body (alternative to OAuth2 form)"""
    from sqlalchemy import inspect, text
    
    # Check if tenant_id column exists
    try:
        inspector = inspect(db.bind)
        user_columns = [col['name'] for col in inspector.get_columns('users')]
        has_tenant_id = 'tenant_id' in user_columns
    except Exception:
        # If inspection fails, assume no tenant_id
        has_tenant_id = False
    
    # Try to query user - handle missing tenant_id column gracefully
    # Always use raw SQL first to avoid SQLAlchemy trying to query tenant_id if it doesn't exist
    user = None
    try:
        # First, try with raw SQL to avoid SQLAlchemy model issues
        if not has_tenant_id:
            # Column doesn't exist, use raw SQL without tenant_id
            result = db.execute(text("SELECT id, username, email, password_hash, full_name, is_active FROM users WHERE username = :username"), 
                              {"username": login_data.username})
            row = result.fetchone()
            if row:
                user = User()
                user.id = row[0]
                user.username = row[1]
                user.email = row[2]
                user.password_hash = row[3]
                user.full_name = row[4] if len(row) > 4 else None
                user.is_active = row[5] if len(row) > 5 else True
        else:
            # Column exists, try ORM query first
            try:
                query = db.query(User).filter(User.username == login_data.username)
                if login_data.tenant_id:
                    query = query.filter(User.tenant_id == login_data.tenant_id)
                user = query.first()
            except Exception as orm_error:
                # If ORM fails, fallback to raw SQL
                logger.warning(f"ORM query failed, using raw SQL: {orm_error}")
                result = db.execute(text("SELECT id, username, email, password_hash, full_name, is_active, tenant_id FROM users WHERE username = :username"), 
                                  {"username": login_data.username})
                row = result.fetchone()
                if row:
                    user = User()
                    user.id = row[0]
                    user.username = row[1]
                    user.email = row[2]
                    user.password_hash = row[3]
                    user.full_name = row[4] if len(row) > 4 else None
                    user.is_active = row[5] if len(row) > 5 else True
                    if len(row) > 6:
                        user.tenant_id = row[6]
    except Exception as e:
        logger.error(f"Error querying user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error. Please contact administrator."
        )
    
    if not user or not verify_password(login_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive"
        )
    
    # Create access token with tenant_id if available
    token_data = {"sub": user.id}
    if has_tenant_id and hasattr(user, 'tenant_id') and user.tenant_id:
        token_data["tenant_id"] = user.tenant_id
    access_token = create_access_token(data=token_data)
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=await _build_user_response(user, db),
    )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get current user information"""
    return await _build_user_response(user, db)


@router.get("/roles", response_model=List[str])
async def get_available_roles():
    """Get list of available roles"""
    return list(ROLES.keys())


def _tenant_response(tenant: Tenant, db: Session) -> dict:
    from app.services.tenant_config_service import TenantConfigService
    service = TenantConfigService(db)
    config = service.get_or_create(tenant.id)
    return {
        "id": tenant.id,
        "name": tenant.name,
        "description": tenant.description,
        "capabilities": config.capabilities,
        "onboarding_path": config.onboarding_path,
    }


@router.get("/tenants")
async def list_tenants(
    db: Session = Depends(get_db)
):
    """List all active tenants"""
    try:
        tenants = db.query(Tenant).filter(Tenant.is_active == True).all()
        return [_tenant_response(t, db) for t in tenants]
    except Exception as e:
        logger.error(f"Error listing tenants: {e}", exc_info=True)
        # Return empty list instead of error to prevent UI issues
        return []


@router.get("/tenants/{tenant_id}")
async def get_tenant_by_id(
    tenant_id: str,
    db: Session = Depends(get_db)
):
    """Get a specific tenant by ID"""
    try:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tenant not found"
            )
        result = _tenant_response(tenant, db)
        result["is_active"] = tenant.is_active
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching tenant {tenant_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error fetching tenant"
        )


@router.post("/tenants")
async def create_tenant(
    name: str,
    description: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Create a new tenant"""
    # Check if tenant name already exists
    existing = db.query(Tenant).filter(Tenant.name == name).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant with this name already exists"
        )
    
    tenant = Tenant(
        id=str(uuid.uuid4()),
        name=name,
        description=description,
        is_active=True
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    
    return {
        "id": tenant.id,
        "name": tenant.name,
        "description": tenant.description
    }
