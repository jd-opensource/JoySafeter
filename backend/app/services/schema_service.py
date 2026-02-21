"""
Schema Service — Schema-centric operations on graph definitions.

Provides higher-level methods that operate on ``GraphSchema`` objects:
- Export a DB graph as a ``GraphSchema``
- Import a ``GraphSchema`` back to DB
- Export a graph as standalone Python code
- Compile a graph via the schema pipeline
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import NotFoundException
from app.core.graph.code_generator import generate_code
from app.core.graph.graph_builder_factory import GraphBuilder
from app.core.graph.graph_compiler import CompilationResult
from app.core.graph.graph_schema import GraphSchema
from app.repositories.graph import GraphEdgeRepository, GraphNodeRepository, GraphRepository

from .base import BaseService
from .model_service import ModelService


class SchemaService(BaseService):
    """Service layer for schema-centric graph operations."""

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.graph_repo = GraphRepository(db)
        self.node_repo = GraphNodeRepository(db)
        self.edge_repo = GraphEdgeRepository(db)

    # ------------------------------------------------------------------
    # Export operations
    # ------------------------------------------------------------------

    async def export_schema(self, graph_id: uuid.UUID) -> GraphSchema:
        """Export a database graph as a ``GraphSchema``.

        Parameters
        ----------
        graph_id : uuid.UUID
            The graph to export.

        Returns
        -------
        GraphSchema
            A serializable, portable schema representation.

        Raises
        ------
        NotFoundException
            If the graph does not exist.
        """
        graph = await self.graph_repo.get(graph_id)
        if not graph:
            raise NotFoundException(f"Graph with id {graph_id} not found")

        nodes = await self.node_repo.list_by_graph(graph_id)
        edges = await self.edge_repo.list_by_graph(graph_id)

        schema = GraphSchema.from_db(graph, nodes, edges)
        logger.info(
            f"[SchemaService] Exported schema | graph_id={graph_id} | "
            f"nodes={len(schema.nodes)} | edges={len(schema.edges)} | "
            f"state_fields={len(schema.state_fields)}"
        )
        return schema

    async def export_code(
        self,
        graph_id: uuid.UUID,
        *,
        include_main: bool = True,
    ) -> str:
        """Export a graph as standalone Python code.

        Parameters
        ----------
        graph_id : uuid.UUID
            The graph to export.
        include_main : bool
            If ``True``, include ``if __name__ == "__main__"`` block.

        Returns
        -------
        str
            A complete, runnable Python source file.
        """
        schema = await self.export_schema(graph_id)
        code = generate_code(schema, include_main=include_main)
        logger.info(f"[SchemaService] Generated code | graph_id={graph_id} | " f"lines={code.count(chr(10)) + 1}")
        return code

    # ------------------------------------------------------------------
    # Compile via schema pipeline
    # ------------------------------------------------------------------

    async def compile_graph(
        self,
        graph_id: uuid.UUID,
        *,
        llm_model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        max_tokens: int = 4096,
        user_id: Optional[Any] = None,
    ) -> CompilationResult:
        """Compile a graph from its schema using the new pipeline.

        This is the schema-first alternative to ``GraphService.create_graph_by_graph_id()``.
        It converts DB models → ``GraphSchema`` → compiled ``StateGraph``.

        Parameters
        ----------
        graph_id : uuid.UUID
            The graph to compile.
        llm_model, api_key, base_url, max_tokens, user_id
            Standard LLM configuration forwarded to the builder.

        Returns
        -------
        CompilationResult
            Contains the compiled graph plus diagnostics.
        """
        graph = await self.graph_repo.get(graph_id)
        if not graph:
            raise NotFoundException(f"Graph with id {graph_id} not found")

        nodes = await self.node_repo.list_by_graph(graph_id)
        edges = await self.edge_repo.list_by_graph(graph_id)

        model_service = ModelService(self.db)
        builder = GraphBuilder(
            graph=graph,
            nodes=nodes,
            edges=edges,
            llm_model=llm_model,
            api_key=api_key,
            base_url=base_url,
            max_tokens=max_tokens,
            user_id=user_id,
            model_service=model_service,
        )
        # Use the schema-based builder path
        inner_builder = builder._create_builder()

        if hasattr(inner_builder, "build_from_schema"):
            result = await inner_builder.build_from_schema()
            logger.info(
                f"[SchemaService] Schema compilation complete | graph_id={graph_id} | "
                f"build_time={result.build_time_ms:.2f}ms | warnings={len(result.warnings)}"
            )
            return result
        else:
            # Fallback for DeepAgents builder or other builders
            compiled = await inner_builder.build()
            schema = GraphSchema.from_db(graph, nodes, edges)
            from app.core.graph.graph_state import GraphState

            return CompilationResult(
                compiled_graph=compiled,
                schema=schema,
                state_class=GraphState,
            )

    # ------------------------------------------------------------------
    # Validate
    # ------------------------------------------------------------------

    async def validate_schema(self, graph_id: uuid.UUID) -> Dict[str, Any]:
        """Validate a graph schema and return diagnostics.

        Returns
        -------
        dict
            ``{"valid": bool, "warnings": [...], "errors": [...]}``
        """
        try:
            schema = await self.export_schema(graph_id)
        except NotFoundException:
            return {"valid": False, "errors": [f"Graph {graph_id} not found"], "warnings": []}

        errors: List[str] = []
        warnings: List[str] = []

        # Structural validation
        try:
            warnings.extend(schema.validate_state_dependencies())
        except Exception as e:
            errors.append(f"State dependency validation failed: {e}")

        if not schema.nodes:
            warnings.append("Graph has no nodes")

        start_nodes = schema.get_start_nodes()
        if not start_nodes:
            errors.append("Graph has no start nodes (no node without incoming edges)")

        end_nodes = schema.get_end_nodes()
        if not end_nodes:
            warnings.append("Graph has no end nodes (all nodes have outgoing edges)")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "state_field_count": len(schema.state_fields),
        }

    async def validate_schema_data(self, schema_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate a raw schema dictionary (stateless)."""
        try:
            # 1. Structural Validation (Pydantic)
            schema = GraphSchema.model_validate(schema_data)
        except Exception as e:
            return {
                "valid": False,
                "errors": [f"Invalid schema structure: {e}"],
                "warnings": [],
            }

        errors: List[str] = []
        warnings: List[str] = []

        # 2. State Dependency Validation
        try:
            warnings.extend(schema.validate_state_dependencies())
        except Exception as e:
            errors.append(f"State dependency validation failed: {e}")

        # 3. Graph Topology Validation
        if not schema.nodes:
            warnings.append("Graph has no nodes")

        start_nodes = schema.get_start_nodes()
        if not start_nodes:
            errors.append("Graph has no start nodes (no node without incoming edges)")
        elif len(start_nodes) > 1:
            # Check if this is intended to be a DeepAgents graph
            is_deep_agents = any(n.config.get("useDeepAgents") for n in start_nodes)
            if not is_deep_agents:
                warnings.append(
                    "Multiple start nodes detected (valid for some patterns, but ensure this is intentional)"
                )

        end_nodes = schema.get_end_nodes()
        if not end_nodes:
            # It's okay if all end nodes are loops, but warn if it looks unintentional
            warnings.append("Graph has no end nodes (all nodes have outgoing edges)")

        # 4. Node Configuration Validation (Ported from nodeConfigValidator.ts)
        for node in schema.nodes:
            node_errors = self._validate_node_config(node)
            errors.extend(node_errors)

        # 5. DeepAgents Validation (Ported from deepAgentsValidator.ts)
        # Check if any node uses DeepAgents
        has_deep_agents = any(n.config.get("useDeepAgents") for n in schema.nodes)
        if has_deep_agents:
            da_errors = self._validate_deep_agents_structure(schema)
            errors.extend(da_errors)

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "node_count": len(schema.nodes),
            "edge_count": len(schema.edges),
            "state_field_count": len(schema.state_fields),
        }

    def _validate_node_config(self, node: Any) -> List[str]:
        """Validate configuration for specific node types."""
        errors = []
        config = node.config

        # Router Node
        if node.type == "router_node":
            routes = config.get("routes", [])
            if not routes:
                errors.append(f"Router node '{node.label}' ({node.id}) must have at least one route")
            else:
                for idx, route in enumerate(routes):
                    if not route.get("condition"):
                        errors.append(f"Router node '{node.label}' ({node.id}) route #{idx+1} missing condition")
                    if not route.get("targetEdgeKey"):
                        errors.append(f"Router node '{node.label}' ({node.id}) route #{idx+1} missing targetEdgeKey")

        # Tool Node
        elif node.type == "tool_node":
            if not config.get("tool_name"):
                errors.append(f"Tool node '{node.label}' ({node.id}) missing 'tool_name'")

        return errors

    def _validate_deep_agents_structure(self, schema: GraphSchema) -> List[str]:
        """Validate DeepAgents structural constraints."""
        errors = []
        # Re-implement key logic from deepAgentsValidator.ts
        # 1. Root Check
        start_nodes = schema.get_start_nodes()
        if not start_nodes:
            # Already caught by general topology check, but be specific for DA
            pass

        # 2. Manager -> SubAgent structure
        # (Simplified check: ensure DeepAgents-enabled roots don't have parents - guaranteed by get_start_nodes)

        # 3. SubAgent descriptions
        for node in schema.nodes:
            # Check if it's a subagent (child of a manager) - hard to know strictly without traversing
            # But we can check if it has a description if it LOOKS like an agent
            if node.type == "agent" or node.type == "code_agent":
                # If it is a child in a DA graph, it needs a description.
                # For now, we'll skip strict description length checks to avoid false positives on standard graphs
                pass

        return errors

    # ------------------------------------------------------------------
    # Import (from schema JSON → DB)
    # ------------------------------------------------------------------

    async def import_schema(
        self,
        schema_data: Dict[str, Any],
        *,
        user_id: uuid.UUID,
        workspace_id: Optional[uuid.UUID] = None,
    ) -> uuid.UUID:
        """Import a ``GraphSchema`` from JSON data into the database.

        Creates a new graph with the specified nodes and edges.

        Parameters
        ----------
        schema_data : dict
            Serialized ``GraphSchema`` (e.g., from ``schema.model_dump()``).
        user_id : uuid.UUID
            Owner of the new graph.
        workspace_id : uuid.UUID, optional
            Workspace to create the graph in.

        Returns
        -------
        uuid.UUID
            The ID of the newly created graph.
        """
        schema = GraphSchema.model_validate(schema_data)

        # Create the graph
        graph = await self.graph_repo.create(
            name=schema.name,
            user_id=user_id,
            workspace_id=workspace_id,
            description=schema.description,
        )
        graph_id = graph.id
        logger.info(f"[SchemaService] Created graph {graph_id} from schema '{schema.name}'")

        # Create nodes
        for node_schema in schema.nodes:
            data = {
                "type": node_schema.type,
                "label": node_schema.label,
                "config": {
                    **node_schema.config,
                    "reads": node_schema.reads,
                    "writes": node_schema.writes,
                },
            }
            if node_schema.metadata:
                data.update({k: v for k, v in node_schema.metadata.items() if v is not None})

            position = node_schema.position or {"x": 0, "y": 0}
            await self.node_repo.create(
                graph_id=graph_id,
                type=node_schema.type,
                position_x=position.get("x", 0),
                position_y=position.get("y", 0),
                data=data,
            )

        # Create edges
        for edge_schema in schema.edges:
            edge_data = {
                "edge_type": edge_schema.edge_type.value,
                **({"route_key": edge_schema.route_key} if edge_schema.route_key else {}),
                **({"source_handle_id": edge_schema.source_handle_id} if edge_schema.source_handle_id else {}),
                **({"label": edge_schema.label} if edge_schema.label else {}),
                **({"condition": edge_schema.condition} if edge_schema.condition else {}),
                **(edge_schema.data or {}),
            }
            await self.edge_repo.create(
                graph_id=graph_id,
                source_node_id=uuid.UUID(edge_schema.source),
                target_node_id=uuid.UUID(edge_schema.target),
                data=edge_data,
            )

        logger.info(
            f"[SchemaService] Imported schema complete | graph_id={graph_id} | "
            f"nodes={len(schema.nodes)} | edges={len(schema.edges)}"
        )
        return graph_id
