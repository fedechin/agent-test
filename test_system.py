#!/usr/bin/env python3
"""
Simple test script to verify the enhanced RAG agent system.
Tests basic functionality without requiring full deployment.
"""
import os
import sys
from pathlib import Path

# Add the src directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def test_imports():
    """Test that all new modules can be imported."""
    print("🧪 Testing module imports...")

    try:
        from agent_test.models import Conversation, Message, HumanAgent, ConversationStatus
        print("✅ Models imported successfully")
    except ImportError as e:
        print(f"❌ Failed to import models: {e}")
        return False

    try:
        from agent_test.database import create_tables, get_db
        print("✅ Database module imported successfully")
    except ImportError as e:
        print(f"❌ Failed to import database: {e}")
        return False

    try:
        from agent_test.conversation_manager import ConversationManager
        print("✅ Conversation manager imported successfully")
    except ImportError as e:
        print(f"❌ Failed to import conversation manager: {e}")
        return False

    try:
        from agent_test.auth import get_password_hash, verify_password
        print("✅ Auth module imported successfully")
    except ImportError as e:
        print(f"❌ Failed to import auth: {e}")
        return False

    return True

def test_conversation_manager():
    """Test conversation manager functionality."""
    print("\n🧪 Testing conversation manager...")

    try:
        from agent_test.conversation_manager import ConversationManager
        cm = ConversationManager()

        # Test human handover detection
        test_cases = [
            ("hablar con humano", True),
            ("quiero hablar con una persona", True),
            ("¿cuánto cuesta el producto?", False),
            ("human agent please", True),
            ("esto no funciona", True),
        ]

        for message, expected in test_cases:
            result = cm.should_handover_to_human(message)
            if result == expected:
                print(f"✅ '{message}' -> {result} (correct)")
            else:
                print(f"❌ '{message}' -> {result} (expected {expected})")
                return False

        print("✅ Conversation manager tests passed")
        return True

    except Exception as e:
        print(f"❌ Conversation manager test failed: {e}")
        return False

def test_auth_functions():
    """Test authentication functions."""
    print("\n🧪 Testing authentication functions...")

    try:
        from agent_test.auth import get_password_hash, verify_password

        # Test password hashing
        password = "test_password_123"
        hashed = get_password_hash(password)

        if verify_password(password, hashed):
            print("✅ Password hashing and verification works")
        else:
            print("❌ Password verification failed")
            return False

        # Test wrong password
        if not verify_password("wrong_password", hashed):
            print("✅ Wrong password correctly rejected")
        else:
            print("❌ Wrong password incorrectly accepted")
            return False

        return True

    except Exception as e:
        print(f"❌ Auth test failed: {e}")
        return False

def test_file_structure():
    """Test that all required files exist."""
    print("\n🧪 Testing file structure...")

    required_files = [
        "src/agent_test/models.py",
        "src/agent_test/database.py",
        "src/agent_test/conversation_manager.py",
        "src/agent_test/auth.py",
        "templates/login.html",
        "templates/agent_dashboard.html",
        "pyproject.toml",
        "docker-compose.yml",
        ".env.example",
        "create_admin.py",
        "production-setup.md"
    ]

    all_exist = True
    for file_path in required_files:
        if Path(file_path).exists():
            print(f"✅ {file_path}")
        else:
            print(f"❌ {file_path} (missing)")
            all_exist = False

    return all_exist

def test_templates():
    """Test that HTML templates contain expected content."""
    print("\n🧪 Testing HTML templates...")

    # Test login template
    login_path = Path("templates/login.html")
    if login_path.exists():
        content = login_path.read_text()
        if "Cooperativa Nazareth" in content and "agent_id" in content:
            print("✅ Login template contains expected content")
        else:
            print("❌ Login template missing expected content")
            return False
    else:
        print("❌ Login template not found")
        return False

    # Test dashboard template
    dashboard_path = Path("templates/agent_dashboard.html")
    if dashboard_path.exists():
        content = dashboard_path.read_text()
        if "Dashboard" in content and "Conversaciones Pendientes" in content:
            print("✅ Dashboard template contains expected content")
        else:
            print("❌ Dashboard template missing expected content")
            return False
    else:
        print("❌ Dashboard template not found")
        return False

    return True

def main():
    """Run all tests."""
    print("🚀 Testing Cooperativa Nazareth Enhanced RAG Agent System")
    print("=" * 60)

    tests = [
        ("File Structure", test_file_structure),
        ("Module Imports", test_imports),
        ("Conversation Manager", test_conversation_manager),
        ("Authentication", test_auth_functions),
        ("HTML Templates", test_templates),
    ]

    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ {test_name} failed with exception: {e}")
            results.append((test_name, False))

    print("\n" + "=" * 60)
    print("📊 Test Results Summary")
    print("=" * 60)

    passed = 0
    total = len(results)

    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {test_name}")
        if result:
            passed += 1

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All tests passed! System is ready for deployment.")
        print("\nNext steps:")
        print("1. Copy .env.example to .env and configure your API keys")
        print("2. Run: poetry install (when network allows)")
        print("3. Run: python create_admin.py (to create first admin user)")
        print("4. Run: poetry run uvicorn src.agent_test.main:app --reload")
        print("5. Visit: http://localhost:8000/admin to access the dashboard")
    else:
        print(f"\n⚠️  {total - passed} tests failed. Please review the errors above.")

    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)