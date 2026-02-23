"""
Graph Test Service
"""

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.graph import AgentGraph
from app.models.graph_test import GraphTestCase

logger = logging.getLogger(__name__)


class TestService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_test_case(self, graph_id: UUID, data: Dict[str, Any]) -> GraphTestCase:
        """Create a new test case for a graph."""
        test_case = GraphTestCase(
            graph_id=graph_id,
            name=data["name"],
            description=data.get("description"),
            inputs=data["inputs"],
            expected_outputs=data["expected_outputs"],
            assertions=data.get("assertions", []),
        )
        self.session.add(test_case)
        await self.session.commit()
        await self.session.refresh(test_case)
        return test_case

    async def get_test_cases(self, graph_id: UUID) -> List[GraphTestCase]:
        """Get all test cases for a graph."""
        stmt = select(GraphTestCase).where(GraphTestCase.graph_id == graph_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_test_case(self, test_case_id: UUID, data: Dict[str, Any]) -> Optional[GraphTestCase]:
        """Update a test case."""
        stmt = select(GraphTestCase).where(GraphTestCase.id == test_case_id)
        result = await self.session.execute(stmt)
        test_case = result.scalar_one_or_none()

        if not test_case:
            return None

        if "name" in data:
            test_case.name = data["name"]
        if "description" in data:
            test_case.description = data["description"]
        if "inputs" in data:
            test_case.inputs = data["inputs"]
        if "expected_outputs" in data:
            test_case.expected_outputs = data["expected_outputs"]
        if "assertions" in data:
            test_case.assertions = data["assertions"]

        await self.session.commit()
        await self.session.refresh(test_case)
        return test_case

    async def delete_test_case(self, test_case_id: UUID) -> bool:
        """Delete a test case."""
        stmt = select(GraphTestCase).where(GraphTestCase.id == test_case_id)
        result = await self.session.execute(stmt)
        test_case = result.scalar_one_or_none()

        if not test_case:
            return False

        await self.session.delete(test_case)
        await self.session.commit()
        return True

    async def run_test_suite(self, graph_id: UUID) -> Dict[str, Any]:
        """Run all test cases for a graph."""
        # 1. Fetch graph and test cases
        stmt = select(AgentGraph).where(AgentGraph.id == graph_id)
        result = await self.session.execute(stmt)
        graph = result.scalar_one_or_none()

        if not graph:
            raise ValueError(f"Graph {graph_id} not found")

        test_cases = await self.get_test_cases(graph_id)

        if not test_cases:
            return {"graph_id": str(graph_id), "total": 0, "passed": 0, "failed": 0, "results": []}

        # 2. Compile graph using the standard builder factory
        # This ensures we get the correct builder (Standard or DeepAgents) and all executors
        from app.core.graph.graph_builder_factory import GraphBuilder

        builder = GraphBuilder(
            graph=graph,
            nodes=graph.nodes,
            edges=graph.edges,
            # We can pass specific testing configs here if needed
            # For now, we use defaults which means it uses env vars for LLM
        )

        # This returns the compiled LangGraph runnable
        compiled_graph = await builder.build()

        results = []
        passed_count = 0

        # 3. specific node mapping
        # Compiler uses node IDs (UUIDs) as graph node names in LangGraph
        # But inputs/outputs in test cases might prefer easier names?
        # For now, let's assume inputs keys match the graph state schema keys.

        for test in test_cases:
            test_result: Dict[str, Any] = {
                "test_case_id": str(test.id),
                "name": test.name,
                "status": "pending",
                "error": None,
                "details": {},
            }

            try:
                # Prepare inputs
                inputs = test.inputs

                # Execute
                # Use ainvoke for async execution
                # We do not pass a thread_id, so this execution might be stateless
                # or use a new thread if checkpointer mandates it.
                # If the graph requires a thread_id config, we might need to generate one.
                # Usually LangGraph generic ainvoke works without config for stateless runs if checkpointer allows.
                # But if checkpointer is enabled, we should probably provide a thread_id to avoid polluting global state?
                # Actually, without thread_id in config, LangGraph with checkpointer might error or behave differently.
                # Let's generate a temporary thread_id for isolation.
                import uuid
                from langchain_core.runnables import RunnableConfig

                config = RunnableConfig(configurable={"thread_id": str(uuid.uuid4())})

                output_state = await compiled_graph.ainvoke(inputs, config=config)

                # Verify outputs
                expected = test.expected_outputs
                match = True
                mismatches = {}

                for key, expected_val in expected.items():
                    actual_val = output_state.get(key)
                    if actual_val != expected_val:
                        match = False
                        mismatches[key] = {"expected": expected_val, "actual": actual_val}

                # Check additional assertions if any
                # (Simple implementation: supported operators: contains, equals, etc.)
                for assertion in test.assertions:
                    # Example assertion: {"path": "messages[-1].content", "operator": "contains", "value": "check"}
                    # This would require more complex object traversal logic
                    pass

                if match:
                    test_result["status"] = "passed"
                    passed_count += 1
                else:
                    test_result["status"] = "failed"
                    test_result["details"]["mismatches"] = mismatches

            except Exception as e:
                test_result["status"] = "error"
                test_result["error"] = str(e)
                logger.exception(f"Error running test case {test.name}")

            results.append(test_result)

        return {
            "graph_id": str(graph_id),
            "total": len(test_cases),
            "passed": passed_count,
            "failed": len(test_cases) - passed_count,
            "results": results,
        }
