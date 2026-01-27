#!/usr/bin/env python3
"""
Test script for Web Visualization API
Tests all endpoints with mock data
"""

import logging
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.dynamic_agent.web.mock_data import (
    generate_execution_tree,
    generate_sessions_for_user,
    generate_tasks_for_session,
    get_mock_tool_by_name,
    get_mock_tools,
)
from app.dynamic_agent.web.models import (
    SessionResponse,
    TaskSummaryResponse,
)

logger = logging.getLogger(__name__)


def test_session_generation():
    """Test session generation"""
    print("\n📋 Testing Session Generation...")
    sessions = generate_sessions_for_user("user_123", count=3)
    print(f"✓ Generated {len(sessions)} sessions")
    for session in sessions:
        print(f"  - {session.id}: {session.title}")
    return sessions[0].id if sessions else None


def test_task_generation(session_id):
    """Test task generation"""
    print("\n📋 Testing Task Generation...")
    tasks = generate_tasks_for_session(session_id, count=2)
    print(f"✓ Generated {len(tasks)} tasks")
    for task in tasks:
        print(f"  - {task.id}: {task.title}")
    return tasks[0].id if tasks else None


def test_execution_tree(task_id):
    """Test execution tree generation"""
    print("\n🌳 Testing Execution Tree Generation...")
    execution = generate_execution_tree(task_id)
    print(f"✓ Generated execution tree: {execution.id}")
    print(f"  - Agents: {execution.total_agents_count}")
    print(f"  - Tools: {execution.total_tools_count}")
    print(f"  - Duration: {execution.total_duration_ms}ms")
    print(f"  - Success Rate: {execution.success_rate}%")
    return execution


def test_tools():
    """Test tool information"""
    print("\n🔧 Testing Tool Information...")
    tools = get_mock_tools()
    print(f"✓ Found {len(tools)} tools:")
    for tool in tools:
        print(f"  - {tool.name}: {tool.description}")

    # Test specific tool
    print("\n🔧 Testing Specific Tool...")
    tool = get_mock_tool_by_name("nmap_scan")
    if tool:
        print(f"✓ Found tool: {tool.name}")
        print(f"  - Category: {tool.category}")
        print(f"  - Parameters: {list(tool.parameters.keys())}")
    else:
        print("✗ Tool not found")


def test_data_models():
    """Test data model validation"""
    print("\n📊 Testing Data Model Validation...")

    # Test SessionResponse
    session = SessionResponse(
        id="test_session",
        user_id="user_123",
        title="Test Session",
        created_at=1700000000000,
        updated_at=1700000000000,
        task_count=3,
    )
    print(f"✓ SessionResponse validated: {session.id}")

    # Test TaskSummaryResponse
    task = TaskSummaryResponse(
        id="test_task",
        session_id="test_session",
        title="Test Task",
        description="Test Description",
        status="completed",
        start_time=1700000000000,
        end_time=1700000060000,
        duration_ms=60000,
        execution_id="test_exec",
        root_agent_id="test_agent",
        agent_count=5,
        tool_count=10,
        success_rate=95.0,
    )
    print(f"✓ TaskSummaryResponse validated: {task.id}")


def main():
    """Run all tests"""
    print("=" * 60)
    print("🧪 Web Visualization API Test Suite")
    print("=" * 60)

    try:
        # Test data models
        test_data_models()

        # Test session generation
        session_id = test_session_generation()
        if not session_id:
            print("✗ Failed to generate sessions")
            return False

        # Test task generation
        task_id = test_task_generation(session_id)
        if not task_id:
            print("✗ Failed to generate tasks")
            return False

        # Test execution tree
        execution = test_execution_tree(task_id)
        if not execution:
            print("✗ Failed to generate execution tree")
            return False

        # Test tools
        test_tools()

        print("\n" + "=" * 60)
        print("✅ All tests passed!")
        print("=" * 60)
        return True

    except Exception as e:
        logger.error(f"Test failed with error: {e}")
        logger.exception("Test traceback")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
