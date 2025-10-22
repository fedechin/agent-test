#!/usr/bin/env python3
"""
Database migration helper to add the 'role' column to existing human_agents table.
Run this after updating the models.py file.
"""
import os
import sys
from dotenv import load_dotenv
from sqlalchemy import text, inspect

# Add the src directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from agent_test.database import SessionLocal, engine

load_dotenv()

def migrate_add_role_column():
    """Add role column to human_agents table if it doesn't exist."""
    db = SessionLocal()
    try:
        print("🔧 Checking if migration is needed...")

        # Check if role column exists using SQLAlchemy inspector (works with all databases)
        inspector = inspect(engine)
        columns = [col['name'] for col in inspector.get_columns('human_agents')]

        if 'role' in columns:
            print("✅ Role column already exists. No migration needed.")
            return

        print("📝 Adding 'role' column to human_agents table...")

        # For PostgreSQL, create enum type first
        db.execute(text("""
            DO $$ BEGIN
                CREATE TYPE agentrole AS ENUM ('ADMIN', 'AGENT');
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$;
        """))

        # Add role column with default value 'AGENT' (uppercase to match Python enum)
        db.execute(text("""
            ALTER TABLE human_agents
            ADD COLUMN role agentrole DEFAULT 'AGENT' NOT NULL
        """))

        print("🔄 Setting first agent as admin...")

        # Set the first agent as admin (uppercase to match Python enum)
        db.execute(text("""
            UPDATE human_agents
            SET role = 'ADMIN'
            WHERE id = (SELECT MIN(id) FROM human_agents)
        """))

        db.commit()

        print("✅ Migration completed successfully!")
        print("   - Created agentrole enum type")
        print("   - Added 'role' column to human_agents table")
        print("   - Set first agent as ADMIN")
        print("   - All other agents are set as AGENT")

    except Exception as e:
        print(f"❌ Error during migration: {e}")
        db.rollback()
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    migrate_add_role_column()
