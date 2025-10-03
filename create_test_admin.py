#!/usr/bin/env python3
"""
Script to create a test admin user automatically for local testing.
"""
import os
import sys
from dotenv import load_dotenv

# Add the src directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from agent_test.database import SessionLocal, create_tables
from agent_test.models import HumanAgent
from agent_test.auth import get_password_hash

load_dotenv()

def create_test_admin():
    """Create a test admin user automatically."""
    # Create tables if they don't exist
    create_tables()

    db = SessionLocal()
    try:
        # Check if any agents exist
        existing_agent = db.query(HumanAgent).first()
        if existing_agent:
            print("✅ Admin user already exists!")
            print(f"   Agent ID: {existing_agent.agent_id}")
            print(f"   Name: {existing_agent.name}")
            print("   Password: admin123")
            return True

        # Create test admin user
        print("🔧 Creating test admin user...")

        password_hash = get_password_hash("admin123")
        admin_user = HumanAgent(
            agent_id="admin",
            name="Test Administrator",
            email="admin@cooperativanazareth.com",
            password_hash=password_hash,
            is_active=True
        )

        db.add(admin_user)
        db.commit()
        db.refresh(admin_user)

        print("✅ Test admin user created successfully!")
        print(f"   Agent ID: admin")
        print(f"   Password: admin123")
        print(f"   Name: Test Administrator")
        print(f"   Email: admin@cooperativanazareth.com")
        print()
        print("🚀 You can now log in to the admin dashboard at: http://localhost:8000/admin")
        return True

    except Exception as e:
        print(f"❌ Error creating admin user: {e}")
        db.rollback()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    success = create_test_admin()
    sys.exit(0 if success else 1)