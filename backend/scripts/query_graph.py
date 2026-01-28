#!/usr/bin/env python3
"""
查询 Graph 的 Nodes 和 Edges 信息

用法:
    python scripts/query_graph.py <graph_id>
    python scripts/query_graph.py 2a78bd23-8cf8-4148-b47e-2c54377f0bd1
"""

import json
import sys
import uuid
from pathlib import Path
from typing import Any, Dict

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine, text  # noqa: E402

from app.core.settings import settings  # noqa: E402


def format_node(row: Dict[str, Any]) -> dict:
    """格式化节点信息"""
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
    """格式化边信息"""
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
    """查询 graph 的 nodes 和 edges"""
    graph_uuid = uuid.UUID(graph_id)

    # 使用同步数据库 URL
    database_url = settings.database_url

    # 如果使用 asyncpg（异步驱动），需要转换为同步驱动
    if "+asyncpg" in database_url:
        database_url = database_url.replace("+asyncpg", "")
        # 优先尝试使用 psycopg（新版本），然后尝试 psycopg2
        try:
            import psycopg

            database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        except ImportError:
            try:
                import psycopg2

                database_url = database_url.replace("postgresql://", "postgresql+psycopg2://", 1)
            except ImportError:
                # 如果都没有，使用默认的 postgresql://（SQLAlchemy 会尝试自动检测）
                pass
    elif not any(x in database_url for x in ["+psycopg2", "+psycopg", "+asyncpg"]):
        # URL 中没有指定驱动，尝试添加同步驱动
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
                # 使用默认，让 SQLAlchemy 自动检测
                pass

    engine = create_engine(database_url, echo=False)

    try:
        with engine.connect() as conn:
            # 查询 graph
            graph_result = conn.execute(text("SELECT * FROM graphs WHERE id = :graph_id"), {"graph_id": graph_uuid})
            graph_row = graph_result.fetchone()

            if not graph_row:
                print(f"❌ Graph 不存在: {graph_id}")
                return

            graph_dict = dict(graph_row._mapping)

            print("=" * 80)
            print("Graph 信息")
            print("=" * 80)
            print(f"ID: {graph_dict['id']}")
            print(f"名称: {graph_dict['name']}")
            print(f"描述: {graph_dict['description'] or '(无)'}")
            print(f"用户ID: {graph_dict['user_id']}")
            print(f"工作空间ID: {graph_dict['workspace_id']}")
            print(f"是否已部署: {graph_dict['is_deployed']}")
            print(f"创建时间: {graph_dict['created_at']}")
            print(f"更新时间: {graph_dict['updated_at']}")
            print()

            # 查询 nodes
            print("=" * 80)
            print("Nodes (节点)")
            print("=" * 80)
            nodes_result = conn.execute(
                text("SELECT * FROM graph_nodes WHERE graph_id = :graph_id ORDER BY created_at"),
                {"graph_id": graph_uuid},
            )
            nodes_rows = nodes_result.fetchall()
            nodes = [dict(row._mapping) for row in nodes_rows]

            print(f"节点总数: {len(nodes)}")
            print()

            if nodes:
                for idx, node_row in enumerate(nodes, 1):
                    print(f"节点 {idx}:")
                    node_info = format_node(node_row)
                    print(f"  ID: {node_info['id']}")
                    print(f"  类型: {node_info['type']}")
                    print(f"  位置: ({node_info['position']['x']}, {node_info['position']['y']})")
                    print(f"  绝对位置: ({node_info['position_absolute']['x']}, {node_info['position_absolute']['y']})")
                    print(f"  尺寸: {node_info['width']} x {node_info['height']}")
                    prompt_preview = node_info["prompt"][:100] if node_info["prompt"] else "(无)"
                    print(f"  提示词: {prompt_preview}{'...' if len(node_info['prompt']) > 100 else ''}")
                    tools_count = len(node_info["tools"]) if isinstance(node_info["tools"], dict) else 0
                    print(f"  工具数量: {tools_count}")
                    data_preview = json.dumps(node_info["data"], ensure_ascii=False, indent=2)[:200]
                    print(
                        f"  数据: {data_preview}{'...' if len(json.dumps(node_info['data'], ensure_ascii=False)) > 200 else ''}"
                    )
                    print()
            else:
                print("  无节点")
            print()

            # 查询 edges
            print("=" * 80)
            print("Edges (边)")
            print("=" * 80)
            edges_result = conn.execute(
                text("SELECT * FROM graph_edges WHERE graph_id = :graph_id ORDER BY created_at"),
                {"graph_id": graph_uuid},
            )
            edges_rows = edges_result.fetchall()
            edges = [dict(row._mapping) for row in edges_rows]

            print(f"边总数: {len(edges)}")
            print()

            if edges:
                for idx, edge_row in enumerate(edges, 1):
                    print(f"边 {idx}:")
                    edge_info = format_edge(edge_row)
                    print(f"  ID: {edge_info['id']}")
                    print(f"  源节点ID: {edge_info['source_node_id']}")
                    print(f"  目标节点ID: {edge_info['target_node_id']}")
                    edge_type = edge_info["data"].get("edge_type", "normal")
                    print(f"  边类型: {edge_type}")
                    route_key = edge_info["data"].get("route_key", "(无)")
                    print(f"  路由键: {route_key}")
                    source_handle_id = edge_info["data"].get("source_handle_id", "(无)")
                    print(f"  源句柄ID: {source_handle_id}")
                    data_preview = json.dumps(edge_info["data"], ensure_ascii=False, indent=2)[:200]
                    print(
                        f"  数据: {data_preview}{'...' if len(json.dumps(edge_info['data'], ensure_ascii=False)) > 200 else ''}"
                    )
                    print()
            else:
                print("  无边")
            print()

            # 输出 JSON 格式（便于程序处理）
            print("=" * 80)
            print("JSON 格式输出")
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
        print("用法: python scripts/query_graph.py <graph_id>")
        print("示例: python scripts/query_graph.py 2a78bd23-8cf8-4148-b47e-2c54377f0bd1")
        sys.exit(1)

    graph_id = sys.argv[1]

    try:
        # 验证 UUID 格式
        uuid.UUID(graph_id)
    except ValueError:
        print(f"❌ 无效的 Graph ID 格式: {graph_id}")
        sys.exit(1)

    try:
        query_graph(graph_id)
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
