#!/usr/bin/env python3
"""
One-time script to stamp the database with the current Alembic revision.
Run this once on Railway to tell Alembic that the migration is already applied.

Usage: railway run python3 stamp_migration.py
"""
import subprocess
import sys

print("🏷️  Stamping database with current Alembic revision...")
print("This marks the migration as already applied without running it.")

try:
    result = subprocess.run(
        ["alembic", "stamp", "head"],
        check=True,
        capture_output=True,
        text=True
    )
    print(result.stdout)
    print("✅ Database stamped successfully!")
    print("   Migration 4bf8c2a7d7c6 is now marked as applied.")
    print("   Future migrations will run normally.")
except subprocess.CalledProcessError as e:
    print(f"❌ Error stamping database: {e}")
    print(e.stderr)
    sys.exit(1)
