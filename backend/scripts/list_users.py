#!/usr/bin/env python3
"""
列出数据库中的用户

使用方法:
    uv run python scripts/list_users.py
"""

import asyncio
import os
import sys

# Add backend directory to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select

from app.core.database import async_session_factory
from app.models.auth import AuthUser


async def list_users():
    """列出所有用户"""
    async with async_session_factory() as session:
        stmt = select(AuthUser.id, AuthUser.username, AuthUser.email).limit(20)
        result = await session.execute(stmt)
        users = result.all()

        if not users:
            print("数据库中没有用户")
            return

        print(f"\n找到 {len(users)} 个用户:\n")
        print(f"{'ID':<40} {'Username':<20} {'Email':<30}")
        print("-" * 90)

        for user_id, username, email in users:
            print(f"{user_id:<40} {username:<20} {email:<30}")


if __name__ == "__main__":
    asyncio.run(list_users())
