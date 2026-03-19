import asyncio

from app.core.db.session import async_session_maker
from sqlalchemy import text


async def main():
    async with async_session_maker() as session:
        result = await session.execute(text("SELECT id, name FROM graphs WHERE name LIKE '%Skill Creator%'"))
        graphs = result.fetchall()
        print("Graphs found:", graphs)
        for g in graphs:
            state_result = await session.execute(
                text("SELECT nodes FROM graph_states WHERE graph_id = :gid"), {"gid": g[0]}
            )
            state = state_result.fetchone()
            print(f"Graph {g[1]} state nodes length:", len(state[0]) if state and state[0] else 0)


asyncio.run(main())
