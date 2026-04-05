#!/usr/bin/env python3
"""
Query Graph nodes and edges information

Usage:
    python scripts/query_graph.py <graph_id>
    python scripts/query_graph.py 2a78bd23-8cf8-4148-b47e-2c54377f0bd1
"""

import json
import sys
import uuid
from pathlib import Path
from typing import Any, Dict

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine, text  # noqa: E402

from app.core.settings import settings  # noqa: E402


def format_node(row: Dict[str, Any]) -> dict:
    """Format node information"""
    import json as json_module

    tools = json_module.loads(row["tools"]) if isinstance(row["tools"], str) else row["tools"]
    memory = json_module.loads(row["memory"]) if isinstance(row["memory"], str) else row["memory"]
    data = json_module.loads(row["data"]) if isinstance(row["data"], str) else row["data"]

    return {
        "id": str(row["id"]),
        "graph_id": str(row["graph_id"]),
        "type": row["type"],
        "position": {
            "x": float(row["position_x"]),
            "y": float(row["position_y"]),
        },
        "position_absolute": {
            "x": float(row["position_absolute_x"])
            if row["position_absolute_x"] is not None
            else float(row["position_x"]),
            "y": float(row["position_absolute_y"])
            if row["position_absolute_y"] is not None
            else float(row["position_y"]),
        },
        "width": float(row["width"]),
        "height": float(row["height"]),
        "prompt": row["prompt"],
        "tools": tools,
        "memory": memory,
        "data": data,
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


def format_edge(row: Dict[str, Any]) -> dict:
    """Format edge information"""
    import json as json_module

    data = json_module.loads(row["data"]) if isinstance(row["data"], str) else row["data"]

    return {
        "id": str(row["id"]),
        "graph_id": str(row["graph_id"]),
        "source_node_id": str(row["source_node_id"]),
        "target_node_id": str(row["target_node_id"]),
        "data": data,
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


def query_graph(graph_id: str):
    """Query graph nodes and edges"""
    graph_uuid = uuid.UUID(graph_id)

    # Use synchronous database URL
    database_url = settings.database_url

    # If using asyncpg (async driver), convert to sync driver
    if "+asyncpg" in database_url:
        database_url = database_url.replace("+asyncpg", "")
        # Prefer psycopg (newer), then try psycopg2
        try:
            import psycopg

            database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        except ImportError:
            try:
                import psycopg2

                database_url = database_url.replace("postgresql://", "postgresql+psycopg2://", 1)
            except ImportError:
                # If neither available, use default postgresql:// (SQLAlchemy will auto-detect)
                pass
    elif not any(x in database_url for x in ["+psycopg2", "+psycopg", "+asyncpg"]):
        # URL has no driver specified, try adding a sync driver
        try:
            import psycopg  # noqa: F401

            database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        except ImportError:
            try:
                import psycopg2  # noqa: F401

                database_url = database_url.replace("postgresql://", "postgresql+psycopg2://", 1)
            except ImportError:
                pass
            except ImportError:
                # Use default, let SQLAlchemy auto-detect
                pass

    engine = create_engine(database_url, echo=False)

    try:
        with engine.connect() as conn:
            # Query graph
            graph_result = conn.execute(text("SELECT * FROM graphs WHERE id = :graph_id"), {"graph_id": graph_uuid})
            graph_row = graph_result.fetchone()

            if not graph_row:
                print(f"❌ Graph not found: {graph_id}")
                return

            graph_dict = dict(graph_row._mapping)

            print("=" * 80)
            print("Graph Info")
            print("=" * 80)
            print(f"ID: {graph_dict['id']}")
            print(f"Name: {graph_dict['name']}")
            print(f"Description: {graph_dict['description'] or '(none)'}")
            print(f"User ID: {graph_dict['user_id']}")
            print(f"Workspace ID: {graph_dict['workspace_id']}")
            print(f"Deployed: {graph_dict['is_deployed']}")
            print(f"Created at: {graph_dict['created_at']}")
            print(f"Updated at: {graph_dict['updated_at']}")
            print()

            # Query nodes
            print("=" * 80)
            print("Nodes")
            print("=" * 80)
            nodes_result = conn.execute(
                text("SELECT * FROM graph_nodes WHERE graph_id = :graph_id ORDER BY created_at"),
                {"graph_id": graph_uuid},
            )
            nodes_rows = nodes_result.fetchall()
            nodes = [dict(row._mapping) for row in nodes_rows]

            print(f"Total nodes: {len(nodes)}")
            print()

            if nodes:
                for idx, node_row in enumerate(nodes, 1):
                    print(f"Node {idx}:")
                    node_info = format_node(node_row)
                    print(f"  ID: {node_info['id']}")
                    print(f"  Type: {node_info['type']}")
                    print(f"  Position: ({node_info['position']['x']}, {node_info['position']['y']})")
                    print(f"  Absolute position: ({node_info['position_absolute']['x']}, {node_info['position_absolute']['y']})")
                    print(f"  Size: {node_info['width']} x {node_info['height']}")
                    prompt_preview = node_info["prompt"][:100] if node_info["prompt"] else "(none)"
                    print(f"  Prompt: {prompt_preview}{'...' if len(node_info['prompt']) > 100 else ''}")
                    tools_count = len(node_info["tools"]) if isinstance(node_info["tools"], dict) else 0
                    print(f"  Tool count: {tools_count}")
                    data_preview = json.dumps(node_info["data"], ensure_ascii=False, indent=2)[:200]
                    print(
                        f"  Data: {data_preview}{'...' if len(json.dumps(node_info['data'], ensure_ascii=False)) > 200 else ''}"
                    )
                    print()
            else:
                print("  No nodes")
            print()

            # Query edges
            print("=" * 80)
            print("Edges")
            print("=" * 80)
            edges_result = conn.execute(
                text("SELECT * FROM graph_edges WHERE graph_id = :graph_id ORDER BY created_at"),
                {"graph_id": graph_uuid},
            )
            edges_rows = edges_result.fetchall()
            edges = [dict(row._mapping) for row in edges_rows]

            print(f"Total edges: {len(edges)}")
            print()

            if edges:
                for idx, edge_row in enumerate(edges, 1):
                    print(f"Edge {idx}:")
                    edge_info = format_edge(edge_row)
                    print(f"  ID: {edge_info['id']}")
                    print(f"  Source node ID: {edge_info['source_node_id']}")
                    print(f"  Target node ID: {edge_info['target_node_id']}")
                    edge_type = edge_info["data"].get("edge_type", "normal")
                    print(f"  Edge type: {edge_type}")
                    route_key = edge_info["data"].get("route_key", "(none)")
                    print(f"  Route key: {route_key}")
                    source_handle_id = edge_info["data"].get("source_handle_id", "(none)")
                    print(f"  Source handle ID: {source_handle_id}")
                    data_preview = json.dumps(edge_info["data"], ensure_ascii=False, indent=2)[:200]
                    print(
                        f"  Data: {data_preview}{'...' if len(json.dumps(edge_info['data'], ensure_ascii=False)) > 200 else ''}"
                    )
                    print()
            else:
                print("  No edges")
            print()

            # Output in JSON format (for programmatic use)
            print("=" * 80)
            print("JSON Output")
            print("=" * 80)
            result = {
                "graph": {
                    "id": str(graph_dict["id"]),
                    "name": graph_dict["name"],
                    "description": graph_dict["description"],
                    "user_id": graph_dict["user_id"],
                    "workspace_id": str(graph_dict["workspace_id"]) if graph_dict["workspace_id"] else None,
                    "is_deployed": graph_dict["is_deployed"],
                    "created_at": graph_dict["created_at"].isoformat() if graph_dict["created_at"] else None,
                    "updated_at": graph_dict["updated_at"].isoformat() if graph_dict["updated_at"] else None,
                },
                "nodes": [format_node(node_row) for node_row in nodes],
                "edges": [format_edge(edge_row) for edge_row in edges],
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))

    finally:
        engine.dispose()


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/query_graph.py <graph_id>")
        print("Example: python scripts/query_graph.py 2a78bd23-8cf8-4148-b47e-2c54377f0bd1")
        sys.exit(1)

    graph_id = sys.argv[1]

    try:
        # Validate UUID format
        uuid.UUID(graph_id)
    except ValueError:
        print(f"❌ Invalid Graph ID format: {graph_id}")
        sys.exit(1)

    try:
        query_graph(graph_id)
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
