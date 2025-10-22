#!/usr/bin/env python3
"""
Script to create the first admin user for the Cooperativa Nazareth system.
Run this script after setting up the database to create your first human agent.
"""
import os
import sys
from dotenv import load_dotenv

# Add the src directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from agent_test.database import SessionLocal, create_tables
from agent_test.models import HumanAgent, AgentRole
from agent_test.auth import get_password_hash

load_dotenv()

def create_admin_user():
    """Create the first admin user."""
    # Create tables if they don't exist
    create_tables()

    db = SessionLocal()
    try:
        # Check if any agents exist
        existing_agent = db.query(HumanAgent).first()
        if existing_agent:
            print("⚠️  Admin user already exists!")
            print(f"   Agent ID: {existing_agent.agent_id}")
            print(f"   Name: {existing_agent.name}")
            return

        # Get admin details
        print("🔧 Creating first admin user for Cooperativa Nazareth...")
        print()

        agent_id = input("Agent ID (e.g., 'admin', 'maria.gonzalez'): ").strip()
        if not agent_id:
            print("❌ Agent ID cannot be empty!")
            return

        name = input("Full Name (e.g., 'María González'): ").strip()
        if not name:
            print("❌ Name cannot be empty!")
            return

        email = input("Email (e.g., 'maria@cooperativanazareth.com'): ").strip()
        if not email:
            print("❌ Email cannot be empty!")
            return

        password = input("Password (min 8 characters): ").strip()
        if len(password) < 8:
            print("❌ Password must be at least 8 characters!")
            return

        # Create the admin user
        password_hash = get_password_hash(password)
        admin_user = HumanAgent(
            agent_id=agent_id,
            name=name,
            email=email,
            password_hash=password_hash,
            role=AgentRole.ADMIN,
            is_active=True
        )

        db.add(admin_user)
        db.commit()
        db.refresh(admin_user)

        print()
        print("✅ Admin user created successfully!")
        print(f"   Agent ID: {admin_user.agent_id}")
        print(f"   Name: {admin_user.name}")
        print(f"   Email: {admin_user.email}")
        print()
        print("🚀 You can now log in to the agent panel at: http://localhost:8000/panel")
        print("   Use the Agent ID and password you just created.")

    except Exception as e:
        print(f"❌ Error creating admin user: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    create_admin_user()