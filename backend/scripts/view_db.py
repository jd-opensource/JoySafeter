#!/usr/bin/env python3
"""
PostgreSQL 数据库查看工具

用法:
    python scripts/view_db.py                    # 列出所有表
    python scripts/view_db.py users              # 查看 users 表的结构和数据
    python scripts/view_db.py users --limit 10   # 查看 users 表的前 10 条数据
    python scripts/view_db.py users --where "id = 'xxx'"  # 条件查询
    python scripts/view_db.py --sql "SELECT * FROM users LIMIT 5"  # 执行自定义 SQL
"""

import argparse
import socket
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine.url import make_url  # noqa: E402

from app.core.settings import settings  # noqa: E402


def _is_tcp_port_open(host: str, port: int, timeout_seconds: float = 0.5) -> bool:
    """Best-effort check whether host:port is accepting TCP connections."""
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except OSError:
        return False


def _maybe_fix_localhost_port(database_url: str) -> str:
    """
    If database URL points to localhost on a non-default port that's not listening,
    but localhost:5432 is listening, auto-switch to 5432 and print a hint.
    """
    try:
        url = make_url(database_url)
    except Exception:
        return database_url

    host = url.host
    port = url.port
    if not host or not port:
        return database_url

    if host not in ("localhost", "127.0.0.1", "::1"):
        return database_url

    if port == 5432:
        return database_url

    if _is_tcp_port_open(host, port):
        return database_url

    if _is_tcp_port_open(host, 5432):
        fixed = url.set(port=5432).render_as_string(hide_password=False)
        print(
            f"⚠️  检测到 PostgreSQL {host}:{port} 无法连接，但 {host}:5432 可用；"
            f"已自动切换到 5432（建议修正 backend/.env 的 POSTGRES_* 环境变量配置）"
        )
        return fixed

    return database_url


class DatabaseViewer:
    """数据库查看工具"""

    def __init__(self, database_url: str):
        self.database_url = database_url
        # 使用同步引擎（更简单，适合查看工具）
        self.engine = create_engine(database_url, echo=False)

    def close(self):
        """关闭数据库连接"""
        self.engine.dispose()

    def list_tables(self) -> List[str]:
        """列出所有表名"""
        with self.engine.connect() as conn:
            # 使用 PostgreSQL 的 information_schema 查询所有用户表
            result = conn.execute(
                text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """)
            )
            tables = [row[0] for row in result.fetchall()]
        return tables

    def get_table_info(self, table_name: str) -> Dict[str, Any]:
        """获取表的详细信息（列、类型、约束等）"""
        with self.engine.connect() as conn:
            # 获取列信息
            columns_result = conn.execute(
                text("""
                SELECT
                    column_name,
                    data_type,
                    character_maximum_length,
                    is_nullable,
                    column_default
                FROM information_schema.columns
                WHERE table_schema = 'public'
                AND table_name = :table_name
                ORDER BY ordinal_position
            """),
                {"table_name": table_name},
            )

            columns = []
            for row in columns_result.fetchall():
                col_type = row[1]
                if row[2]:  # character_maximum_length
                    col_type += f"({row[2]})"
                columns.append(
                    {
                        "name": row[0],
                        "type": col_type,
                        "nullable": row[3] == "YES",
                        "default": row[4],
                    }
                )

            # 获取主键信息
            pk_result = conn.execute(
                text("""
                SELECT column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.constraint_column_usage AS ccu
                    ON tc.constraint_name = ccu.constraint_name
                    AND tc.table_schema = ccu.table_schema
                WHERE tc.constraint_type = 'PRIMARY KEY'
                AND tc.table_schema = 'public'
                AND tc.table_name = :table_name
            """),
                {"table_name": table_name},
            )
            primary_keys = [row[0] for row in pk_result.fetchall()]

            # 获取外键信息
            fk_result = conn.execute(
                text("""
                SELECT
                    kcu.column_name,
                    ccu.table_name AS foreign_table_name,
                    ccu.column_name AS foreign_column_name
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage AS ccu
                    ON ccu.constraint_name = tc.constraint_name
                    AND ccu.table_schema = tc.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                AND tc.table_schema = 'public'
                AND tc.table_name = :table_name
            """),
                {"table_name": table_name},
            )
            foreign_keys = [{"column": row[0], "references": f"{row[1]}.{row[2]}"} for row in fk_result.fetchall()]

            # 获取索引信息
            index_result = conn.execute(
                text("""
                SELECT
                    indexname,
                    indexdef
                FROM pg_indexes
                WHERE schemaname = 'public'
                AND tablename = :table_name
            """),
                {"table_name": table_name},
            )
            indexes = [{"name": row[0], "definition": row[1]} for row in index_result.fetchall()]

            # 获取行数
            count_result = conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))
            row_count = count_result.scalar()

            return {
                "columns": columns,
                "primary_keys": primary_keys,
                "foreign_keys": foreign_keys,
                "indexes": indexes,
                "row_count": row_count,
            }

    def get_table_data(
        self, table_name: str, limit: int = 100, offset: int = 0, where: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """获取表数据"""
        with self.engine.connect() as conn:
            query = f'SELECT * FROM "{table_name}"'
            params = {}

            if where:
                query += f" WHERE {where}"

            query += " LIMIT :limit OFFSET :offset"
            params.update({"limit": limit, "offset": offset})

            result = conn.execute(text(query), params)
            rows = result.fetchall()
            columns = result.keys()

            data = []
            for row in rows:
                row_dict = {}
                for col, val in zip(columns, row):
                    # 处理特殊类型
                    if isinstance(val, datetime):
                        row_dict[col] = val.isoformat()
                    elif val is None:
                        row_dict[col] = None
                    else:
                        row_dict[col] = str(val)
                data.append(row_dict)

            return data

    def execute_sql(self, sql: str) -> tuple[List[str], List[Dict[str, Any]]]:
        """执行自定义 SQL 查询"""
        with self.engine.connect() as conn:
            result = conn.execute(text(sql))

            # 如果是 SELECT 查询，返回结果
            if result.returns_rows:
                rows = result.fetchall()
                columns = list(result.keys())

                data = []
                for row in rows:
                    row_dict = {}
                    for col, val in zip(columns, row):
                        if isinstance(val, datetime):
                            row_dict[col] = val.isoformat()
                        elif val is None:
                            row_dict[col] = None
                        else:
                            row_dict[col] = str(val)
                    data.append(row_dict)

                return columns, data
            else:
                # 对于非 SELECT 查询（INSERT, UPDATE, DELETE 等）
                return [], []


def print_table_list(tables: List[str]):
    """打印表列表"""
    print("\n" + "=" * 60)
    print("数据库表列表")
    print("=" * 60)

    if not tables:
        print("数据库中没有表")
        return

    print(f"{'序号':<6} {'表名':<50}")
    print("-" * 60)
    for idx, table_name in enumerate(tables, 1):
        print(f"{idx:<6} {table_name:<50}")

    print("-" * 60)
    print(f"共 {len(tables)} 个表\n")


def print_table_info(table_name: str, info: Dict[str, Any]):
    """打印表结构信息"""
    print("\n" + "=" * 80)
    print(f"表: {table_name}")
    print("=" * 80)

    # 列信息
    print("\n列信息:")
    print(f"{'列名':<30} {'类型':<25} {'可空':<8} {'默认值':<30}")
    print("-" * 80)
    for col in info["columns"]:
        nullable = "是" if col["nullable"] else "否"
        default = (col["default"] or "-")[:28]
        print(f"{col['name']:<30} {col['type']:<25} {nullable:<8} {default:<30}")

    # 主键
    if info["primary_keys"]:
        print(f"\n主键: {', '.join(info['primary_keys'])}")

    # 外键
    if info["foreign_keys"]:
        print("\n外键:")
        for fk in info["foreign_keys"]:
            print(f"  {fk['column']} → {fk['references']}")

    # 索引
    if info["indexes"]:
        print(f"\n索引 ({len(info['indexes'])} 个):")
        for idx in info["indexes"][:10]:  # 只显示前10个
            print(f"  • {idx['name']}")
        if len(info["indexes"]) > 10:
            print(f"  ... 还有 {len(info['indexes']) - 10} 个索引")

    # 行数
    print(f"\n数据行数: {info['row_count']}\n")


def print_table_data(table_name: str, data: List[Dict[str, Any]], columns: Optional[List[str]] = None):
    """打印表数据"""
    if not data:
        print("没有数据\n")
        return

    if columns is None:
        columns = list(data[0].keys()) if data else []

    # 计算列宽（限制最大宽度）
    col_widths = {}
    max_col_width = 40

    for col in columns:
        # 列名宽度
        col_width = len(col)
        # 数据宽度
        for row in data[:100]:  # 只检查前100行
            val = str(row.get(col, ""))[:max_col_width]
            col_width = max(col_width, len(val))
        col_widths[col] = min(col_width, max_col_width)

    # 打印表头
    header = " | ".join(f"{col:<{col_widths[col]}}" for col in columns)
    print(header)
    print("-" * len(header))

    # 打印数据行
    for row in data:
        values = []
        for col in columns:
            val = str(row.get(col, ""))[:max_col_width]
            values.append(f"{val:<{col_widths[col]}}")
        print(" | ".join(values))

    print(f"\n显示 {len(data)} 条记录\n")


def main():
    parser = argparse.ArgumentParser(
        description="PostgreSQL 数据库查看工具", formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__
    )
    parser.add_argument("table", nargs="?", help="要查看的表名（不指定则列出所有表）")
    parser.add_argument("--limit", type=int, default=100, help="查询数据条数限制（默认: 100）")
    parser.add_argument("--offset", type=int, default=0, help="查询数据偏移量（默认: 0）")
    parser.add_argument("--where", type=str, help="WHERE 条件（例如: \"id = 'xxx'\"）")
    parser.add_argument("--sql", type=str, help="执行自定义 SQL 查询")
    parser.add_argument("--info-only", action="store_true", help="仅显示表结构，不显示数据")
    parser.add_argument(
        "--database-url",
        type=str,
        default=None,
        help="覆盖配置中的数据库连接 URL（例如: postgresql+asyncpg://user:pass@localhost:5432/dbname）。默认从 POSTGRES_* 环境变量构建",
    )

    args = parser.parse_args()

    # 使用同步数据库 URL
    database_url = args.database_url or settings.database_url

    # 如果使用 asyncpg（异步驱动），需要转换为同步驱动
    if "+asyncpg" in database_url:
        database_url = database_url.replace("+asyncpg", "")
        # 优先尝试使用 psycopg（新版本），然后尝试 psycopg2
        try:
            import psycopg  # noqa: F401

            database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        except ImportError:
            try:
                import psycopg2  # noqa: F401

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
                # 使用默认，让 SQLAlchemy 自动检测
                pass

    # 常见本地开发坑：docker 实际映射到 5432，但 .env 里写了 5432 / 其他端口
    database_url = _maybe_fix_localhost_port(database_url)

    viewer = DatabaseViewer(database_url)

    try:
        if args.sql:
            # 执行自定义 SQL
            print(f"\n执行 SQL: {args.sql}\n")
            columns, data = viewer.execute_sql(args.sql)
            if columns:
                print_table_data("查询结果", data, columns)
            else:
                print("✓ SQL 执行成功\n")

        elif args.table:
            # 查看指定表
            table_name = args.table

            # 获取表信息
            info = viewer.get_table_info(table_name)
            print_table_info(table_name, info)

            # 获取数据（如果不是仅查看结构）
            if not args.info_only:
                data = viewer.get_table_data(table_name, limit=args.limit, offset=args.offset, where=args.where)
                print_table_data(table_name, data)

        else:
            # 列出所有表
            tables = viewer.list_tables()
            print_table_list(tables)

    except Exception as e:
        print(f"\n❌ 错误: {e}\n")
        import traceback

        if args.sql or (args.table and not args.info_only):
            traceback.print_exc()
        sys.exit(1)

    finally:
        viewer.close()


if __name__ == "__main__":
    main()
