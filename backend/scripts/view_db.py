#!/usr/bin/env python3
"""
PostgreSQL Database Viewer

Usage:
    python scripts/view_db.py                    # List all tables
    python scripts/view_db.py users              # View users table structure and data
    python scripts/view_db.py users --limit 10   # View first 10 rows of users table
    python scripts/view_db.py users --where "id = 'xxx'"  # Conditional query
    python scripts/view_db.py --sql "SELECT * FROM users LIMIT 5"  # Execute custom SQL
"""

import argparse
import socket
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to path
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
            f"⚠️  PostgreSQL {host}:{port} is not reachable, but {host}:5432 is available; "
            f"auto-switching to 5432 (consider fixing POSTGRES_* env vars in backend/.env)"
        )
        return fixed

    return database_url


class DatabaseViewer:
    """Database viewer tool"""

    def __init__(self, database_url: str):
        self.database_url = database_url
        # Use sync engine (simpler, suitable for a viewer tool)
        self.engine = create_engine(database_url, echo=False)

    def close(self):
        """Close database connection"""
        self.engine.dispose()

    def list_tables(self) -> List[str]:
        """List all table names"""
        with self.engine.connect() as conn:
            # Use PostgreSQL information_schema to query all user tables
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
        """Get detailed table info (columns, types, constraints, etc.)"""
        with self.engine.connect() as conn:
            # Get column info
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

            # Get primary key info
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

            # Get foreign key info
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

            # Get index info
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

            # Get row count
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
        """Get table data"""
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
                    # Handle special types
                    if isinstance(val, datetime):
                        row_dict[col] = val.isoformat()
                    elif val is None:
                        row_dict[col] = None
                    else:
                        row_dict[col] = str(val)
                data.append(row_dict)

            return data

    def execute_sql(self, sql: str) -> tuple[List[str], List[Dict[str, Any]]]:
        """Execute custom SQL query"""
        with self.engine.connect() as conn:
            result = conn.execute(text(sql))

            # If it's a SELECT query, return results
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
                # For non-SELECT queries (INSERT, UPDATE, DELETE, etc.)
                return [], []


def print_table_list(tables: List[str]):
    """Print table list"""
    print("\n" + "=" * 60)
    print("Database Tables")
    print("=" * 60)

    if not tables:
        print("No tables in the database")
        return

    print(f"{'#':<6} {'Table Name':<50}")
    print("-" * 60)
    for idx, table_name in enumerate(tables, 1):
        print(f"{idx:<6} {table_name:<50}")

    print("-" * 60)
    print(f"Total: {len(tables)} tables\n")


def print_table_info(table_name: str, info: Dict[str, Any]):
    """Print table structure info"""
    print("\n" + "=" * 80)
    print(f"Table: {table_name}")
    print("=" * 80)

    # Column info
    print("\nColumns:")
    print(f"{'Column':<30} {'Type':<25} {'Nullable':<8} {'Default':<30}")
    print("-" * 80)
    for col in info["columns"]:
        nullable = "yes" if col["nullable"] else "no"
        default = (col["default"] or "-")[:28]
        print(f"{col['name']:<30} {col['type']:<25} {nullable:<8} {default:<30}")

    # Primary key
    if info["primary_keys"]:
        print(f"\nPrimary key: {', '.join(info['primary_keys'])}")

    # Foreign keys
    if info["foreign_keys"]:
        print("\nForeign keys:")
        for fk in info["foreign_keys"]:
            print(f"  {fk['column']} → {fk['references']}")

    # Indexes
    if info["indexes"]:
        print(f"\nIndexes ({len(info['indexes'])}):")
        for idx in info["indexes"][:10]:  # Show only first 10
            print(f"  • {idx['name']}")
        if len(info["indexes"]) > 10:
            print(f"  ... and {len(info['indexes']) - 10} more indexes")

    # Row count
    print(f"\nRow count: {info['row_count']}\n")


def print_table_data(table_name: str, data: List[Dict[str, Any]], columns: Optional[List[str]] = None):
    """Print table data"""
    if not data:
        print("No data\n")
        return

    if columns is None:
        columns = list(data[0].keys()) if data else []

    # Calculate column widths (limited to max width)
    col_widths = {}
    max_col_width = 40

    for col in columns:
        # Column name width
        col_width = len(col)
        # Data width
        for row in data[:100]:  # Only check first 100 rows
            val = str(row.get(col, ""))[:max_col_width]
            col_width = max(col_width, len(val))
        col_widths[col] = min(col_width, max_col_width)

    # Print header
    header = " | ".join(f"{col:<{col_widths[col]}}" for col in columns)
    print(header)
    print("-" * len(header))

    # Print data rows
    for row in data:
        values = []
        for col in columns:
            val = str(row.get(col, ""))[:max_col_width]
            values.append(f"{val:<{col_widths[col]}}")
        print(" | ".join(values))

    print(f"\nShowing {len(data)} records\n")


def main():
    parser = argparse.ArgumentParser(
        description="PostgreSQL Database Viewer", formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__
    )
    parser.add_argument("table", nargs="?", help="Table name to view (omit to list all tables)")
    parser.add_argument("--limit", type=int, default=100, help="Row limit for queries (default: 100)")
    parser.add_argument("--offset", type=int, default=0, help="Row offset for queries (default: 0)")
    parser.add_argument("--where", type=str, help="WHERE clause (e.g.: \"id = 'xxx'\")")
    parser.add_argument("--sql", type=str, help="Execute custom SQL query")
    parser.add_argument("--info-only", action="store_true", help="Show table structure only, no data")
    parser.add_argument(
        "--database-url",
        type=str,
        default=None,
        help="Override the database URL from config (e.g.: postgresql+asyncpg://user:pass@localhost:5432/dbname). Defaults to building from POSTGRES_* env vars",
    )

    args = parser.parse_args()

    # Use synchronous database URL
    database_url = args.database_url or settings.database_url

    # If using asyncpg (async driver), convert to sync driver
    if "+asyncpg" in database_url:
        database_url = database_url.replace("+asyncpg", "")
        # Prefer psycopg (newer), then try psycopg2
        try:
            import psycopg  # noqa: F401

            database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        except ImportError:
            try:
                import psycopg2  # noqa: F401

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
                # Use default, let SQLAlchemy auto-detect
                pass

    # Common local dev pitfall: docker maps to 5432, but .env has a different port
    database_url = _maybe_fix_localhost_port(database_url)

    viewer = DatabaseViewer(database_url)

    try:
        if args.sql:
            # Execute custom SQL
            print(f"\nExecuting SQL: {args.sql}\n")
            columns, data = viewer.execute_sql(args.sql)
            if columns:
                print_table_data("Query Results", data, columns)
            else:
                print("✓ SQL executed successfully\n")

        elif args.table:
            # View specified table
            table_name = args.table

            # Get table info
            info = viewer.get_table_info(table_name)
            print_table_info(table_name, info)

            # Get data (unless info-only mode)
            if not args.info_only:
                data = viewer.get_table_data(table_name, limit=args.limit, offset=args.offset, where=args.where)
                print_table_data(table_name, data)

        else:
            # List all tables
            tables = viewer.list_tables()
            print_table_list(tables)

    except Exception as e:
        print(f"\n❌ Error: {e}\n")
        import traceback

        if args.sql or (args.table and not args.info_only):
            traceback.print_exc()
        sys.exit(1)

    finally:
        viewer.close()


if __name__ == "__main__":
    main()
