#!/usr/bin/env python3
"""
Database migration helper to add the 'role' column to existing human_agents table.
Run this after updating the models.py file.
"""
import os
import sys
from dotenv import load_dotenv
from sqlalchemy import text

# Add the src directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from agent_test.database import SessionLocal, engine

load_dotenv()

def migrate_add_role_column():
    """Add role column to human_agents table if it doesn't exist."""
    db = SessionLocal()
    try:
        print("🔧 Checking if migration is needed...")

        # Check if role column exists
        result = db.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name='human_agents' AND column_name='role'
        """))

        if result.fetchone():
            print("✅ Role column already exists. No migration needed.")
            return

        print("📝 Adding 'role' column to human_agents table...")

        # Add role column with default value 'agent'
        db.execute(text("""
            ALTER TABLE human_agents
            ADD COLUMN role VARCHAR(10) DEFAULT 'agent' NOT NULL
        """))

        print("🔄 Setting first agent as admin...")

        # Set the first agent as admin
        db.execute(text("""
            UPDATE human_agents
            SET role = 'admin'
            WHERE id = (SELECT MIN(id) FROM human_agents)
        """))

        db.commit()

        print("✅ Migration completed successfully!")
        print("   - Added 'role' column to human_agents table")
        print("   - Set first agent as admin")
        print("   - All other agents are set as regular agents")

    except Exception as e:
        print(f"❌ Error during migration: {e}")
        db.rollback()
        print("\nNote: If you're using SQLite, the information_schema query may fail.")
        print("In that case, you might need to recreate the database or manually add the column.")
    finally:
        db.close()

if __name__ == "__main__":
    migrate_add_role_column()
