#!/usr/bin/env python3
"""
Fix existing role enum values in the database.
This script handles the case where role column already exists with lowercase values.
"""
import os
import sys
from dotenv import load_dotenv
from sqlalchemy import text, inspect

# Add the src directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from agent_test.database import SessionLocal, engine

load_dotenv()

def fix_role_enum():
    """Fix role enum values to use uppercase."""
    db = SessionLocal()
    try:
        print("🔧 Checking database state...")

        # Check if role column exists
        inspector = inspect(engine)
        columns = [col['name'] for col in inspector.get_columns('human_agents')]

        if 'role' not in columns:
            print("❌ Role column doesn't exist yet. Run migrate_add_role.py first.")
            return

        print("📝 Fixing enum values...")

        # Drop the existing role column
        db.execute(text("ALTER TABLE human_agents DROP COLUMN IF EXISTS role"))

        # Drop the old enum type if it exists
        db.execute(text("DROP TYPE IF EXISTS agentrole"))

        # Create the correct enum type
        db.execute(text("""
            CREATE TYPE agentrole AS ENUM ('ADMIN', 'AGENT')
        """))

        # Add the column back with the correct type
        db.execute(text("""
            ALTER TABLE human_agents
            ADD COLUMN role agentrole DEFAULT 'AGENT' NOT NULL
        """))

        # Set the first agent as admin
        db.execute(text("""
            UPDATE human_agents
            SET role = 'ADMIN'
            WHERE id = (SELECT MIN(id) FROM human_agents)
        """))

        db.commit()

        print("✅ Successfully fixed role enum values!")
        print("   - Recreated agentrole enum with uppercase values")
        print("   - Set first agent as ADMIN")

    except Exception as e:
        print(f"❌ Error fixing enum: {e}")
        db.rollback()
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    fix_role_enum()
