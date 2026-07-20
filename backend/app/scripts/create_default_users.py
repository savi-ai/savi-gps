"""Script to create default users for each persona"""
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.core.database import SessionLocal, User, Role, UserRole, Tenant
from app.core.auth import get_password_hash, create_default_roles
import uuid

# Default users configuration
DEFAULT_USERS = [
    {
        "username": "admin",
        "email": "admin@gps.example.com",
        "password": "admin123",
        "full_name": "Administrator",
        "role": "admin"
    },
    {
        "username": "product_manager",
        "email": "pm@gps.example.com",
        "password": "pm123",
        "full_name": "Product Manager",
        "role": "product_manager"
    },
    {
        "username": "architect",
        "email": "architect@gps.example.com",
        "password": "arch123",
        "full_name": "Architect",
        "role": "architect"
    },
    {
        "username": "developer",
        "email": "developer@gps.example.com",
        "password": "dev123",
        "full_name": "Developer",
        "role": "developer"
    },
    {
        "username": "qa",
        "email": "qa@gps.example.com",
        "password": "qa123",
        "full_name": "QA Engineer",
        "role": "qa"
    }
]


def create_default_users():
    """Create default users for testing"""
    db = SessionLocal()
    
    try:
        # Create default roles first
        create_default_roles(db)
        print("✓ Default roles created/verified")
        
        # Create users
        for user_data in DEFAULT_USERS:
            # Check if user already exists
            existing_user = db.query(User).filter(User.username == user_data["username"]).first()
            
            if existing_user:
                print(f"⚠ User '{user_data['username']}' already exists, skipping...")
                continue
            
            # Get role
            role = db.query(Role).filter(Role.name == user_data["role"]).first()
            if not role:
                print(f"✗ Role '{user_data['role']}' not found!")
                continue
            
            # Get default tenant (tenant1) for user assignment
            default_tenant = db.query(Tenant).filter(Tenant.name == "tenant1").first()
            tenant_id = default_tenant.id if default_tenant else None
            
            # Create user
            user_id = str(uuid.uuid4())
            user = User(
                id=user_id,
                username=user_data["username"],
                email=user_data["email"],
                password_hash=get_password_hash(user_data["password"]),
                full_name=user_data["full_name"],
                is_active=True,
                tenant_id=tenant_id
            )
            db.add(user)
            db.flush()
            
            # Assign role
            user_role = UserRole(
                id=str(uuid.uuid4()),
                user_id=user_id,
                role_id=role.id
            )
            db.add(user_role)
            
            print(f"✓ Created user '{user_data['username']}' with role '{user_data['role']}'")
        
        db.commit()
        print("\n✅ Default users created successfully!")
        print("\nLogin Credentials:")
        print("=" * 60)
        for user_data in DEFAULT_USERS:
            print(f"Role: {user_data['role'].replace('_', ' ').title()}")
            print(f"  Username: {user_data['username']}")
            print(f"  Password: {user_data['password']}")
            print()
        
    except Exception as e:
        db.rollback()
        print(f"✗ Error creating users: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    create_default_users()
