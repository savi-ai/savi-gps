"""Migration script to add password_hash column to users table"""
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.core.database import engine, SessionLocal
from app.core.config import settings
from sqlalchemy import text
import sqlite3

def migrate_add_password_hash():
    """Add password_hash column to users table if it doesn't exist"""
    db_path = settings.DATABASE_URL.replace("sqlite:///", "")
    
    if not os.path.exists(db_path):
        print(f"Database file {db_path} does not exist. It will be created on first run.")
        return
    
    try:
        # Connect to SQLite database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if column exists
        cursor.execute("PRAGMA table_info(users)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'password_hash' in columns:
            print("✓ Column 'password_hash' already exists in users table")
            conn.close()
            return
        
        # Add password_hash column
        print("Adding password_hash column to users table...")
        cursor.execute("""
            ALTER TABLE users 
            ADD COLUMN password_hash TEXT NOT NULL DEFAULT ''
        """)
        
        # For existing users, set a placeholder (they'll need to reset password)
        cursor.execute("""
            UPDATE users 
            SET password_hash = '' 
            WHERE password_hash IS NULL OR password_hash = ''
        """)
        
        conn.commit()
        conn.close()
        
        print("✓ Successfully added password_hash column to users table")
        print("⚠ Note: Existing users will need to reset their passwords")
        
    except Exception as e:
        print(f"✗ Error migrating database: {e}")
        raise


if __name__ == "__main__":
    migrate_add_password_hash()
