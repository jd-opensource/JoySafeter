"""
Migrate non-DeepAgents canvas graphs to DSL mode.

Usage:
    python -m scripts.migrate_to_dsl [--dry-run] [--graph-id UUID] [--limit N]

Flags:
    --dry-run     Parse and validate but don't persist changes
    --graph-id    Migrate a single graph (for testing)
    --limit       Max number of graphs to migrate (default: all)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DSL_V1_SUPPORTED_TYPES = {
    "agent",
    "condition",
    "router_node",
    "function_node",
    "http_request_node",
    "direct_reply",
    "human_input",
    "tool_node",
}


# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------


@dataclass
class MigrationResult:
    graph_id: str
    status: str  # "success" | "skipped_deepagents" | "skipped_already_dsl" | failure reason
    detail: Any = None


@dataclass
class MigrationReport:
    total: int = 0
    migrated: int = 0
    skipped_deepagents: int = 0
    skipped_already_dsl: int = 0
    failed: int = 0
    failures: list[MigrationResult] = field(default_factory=list)

    def add(self, result: MigrationResult) -> None:
        self.total += 1
        if result.status == "success":
            self.migrated += 1
        elif result.status == "skipped_deepagents":
            self.skipped_deepagents += 1
        elif result.status == "skipped_already_dsl":
            self.skipped_already_dsl += 1
        else:
            self.failed += 1
            self.failures.append(result)

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "migrated": self.migrated,
            "skipped_deepagents": self.skipped_deepagents,
            "skipped_already_dsl": self.skipped_already_dsl,
            "failed": self.failed,
            "failures": [
                {"graph_id": f.graph_id, "reason": f.status, "detail": str(f.detail)}
                for f in self.failures
            ],
        }


# ---------------------------------------------------------------------------
# Migration logic
# ---------------------------------------------------------------------------


def _is_deepagents_graph(nodes: list) -> bool:
    """Check if any node has useDeepAgents enabled."""
    for node in nodes:
        data = getattr(node, "data", None) or {}
        config = data.get("config", {})
        if config.get("useDeepAgents"):
            return True
    return False


async def migrate_graph(
    graph,
    nodes: list,
    edges: list,
    db: AsyncSession,
    *,
    dry_run: bool = False,
) -> MigrationResult:
    """Migrate a single graph to DSL mode."""
    from app.core.dsl.dsl_code_generator import generate_dsl_code
    from app.core.dsl.dsl_parser import DSLParser
    from app.core.graph.graph_schema import GraphSchema

    graph_id = str(graph.id)

    # Already migrated?
    variables = graph.variables or {}
    if variables.get("graph_mode") == "dsl":
        return MigrationResult(graph_id, "skipped_already_dsl")

    # DeepAgents graph?
    if _is_deepagents_graph(nodes):
        return MigrationResult(graph_id, "skipped_deepagents")

    # Step 1: Build schema from DB
    try:
        schema = GraphSchema.from_db(graph, nodes, edges)
    except Exception as e:
        return MigrationResult(graph_id, "schema_from_db", str(e))

    # Step 2: Check for unsupported node types
    unsupported = {n.type for n in schema.nodes} - DSL_V1_SUPPORTED_TYPES
    if unsupported:
        return MigrationResult(graph_id, "unsupported_node_types", list(unsupported))

    # Step 3: Generate DSL code
    try:
        code = generate_dsl_code(schema)
    except Exception as e:
        return MigrationResult(graph_id, "dsl_generate_code", str(e))

    # Step 4: Verify round-trip
    parser = DSLParser()
    parse_result = parser.parse(code)
    errors = [e for e in parse_result.errors if e.severity == "error"]
    if errors:
        error_msgs = "; ".join(e.message for e in errors[:5])
        return MigrationResult(graph_id, "parse_roundtrip", error_msgs)

    # Step 5: Persist (unless dry-run)
    if not dry_run:
        new_variables = dict(variables)
        new_variables["dsl_code"] = code
        new_variables["graph_mode"] = "dsl"
        graph.variables = new_variables
        await db.flush()

    return MigrationResult(graph_id, "success")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def run_migration(
    *,
    dry_run: bool = False,
    graph_id: str | None = None,
    limit: int | None = None,
) -> MigrationReport:
    """Run the migration against the database."""
    from app.core.database import get_async_session_factory
    from app.models.graph import AgentGraph, GraphEdge, GraphNode

    report = MigrationReport()
    session_factory = get_async_session_factory()

    async with session_factory() as db:
        # Build query
        query = select(AgentGraph).where(AgentGraph.deleted_at.is_(None))
        if graph_id:
            query = query.where(AgentGraph.id == uuid.UUID(graph_id))
        if limit:
            query = query.limit(limit)

        result = await db.execute(query)
        graphs = result.scalars().all()

        logger.info(f"[Migration] Found {len(graphs)} graphs to process")

        for graph in graphs:
            # Load nodes and edges
            nodes_result = await db.execute(
                select(GraphNode)
                .where(GraphNode.graph_id == graph.id)
                .where(GraphNode.deleted_at.is_(None))
            )
            nodes = nodes_result.scalars().all()

            edges_result = await db.execute(
                select(GraphEdge)
                .where(GraphEdge.graph_id == graph.id)
                .where(GraphEdge.deleted_at.is_(None))
            )
            edges = edges_result.scalars().all()

            migration_result = await migrate_graph(
                graph, nodes, edges, db, dry_run=dry_run
            )
            report.add(migration_result)

            status_icon = {
                "success": "OK",
                "skipped_deepagents": "SKIP(DA)",
                "skipped_already_dsl": "SKIP(DSL)",
            }.get(migration_result.status, "FAIL")

            logger.info(
                f"[Migration] [{status_icon}] graph={graph.id} "
                f"name='{graph.name}' status={migration_result.status}"
            )

        if not dry_run:
            await db.commit()
            logger.info("[Migration] Changes committed")
        else:
            logger.info("[Migration] Dry run — no changes committed")

    return report


def main():
    parser = argparse.ArgumentParser(description="Migrate canvas graphs to DSL mode")
    parser.add_argument("--dry-run", action="store_true", help="Don't persist changes")
    parser.add_argument("--graph-id", type=str, help="Migrate a single graph")
    parser.add_argument("--limit", type=int, help="Max graphs to migrate")
    args = parser.parse_args()

    report = asyncio.run(
        run_migration(
            dry_run=args.dry_run,
            graph_id=args.graph_id,
            limit=args.limit,
        )
    )

    print("\n" + "=" * 60)
    print("Migration Report")
    print("=" * 60)
    print(json.dumps(report.to_dict(), indent=2))

    if report.failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
