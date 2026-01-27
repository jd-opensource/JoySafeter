#!/usr/bin/env python3
"""
清理数据库数据脚本
删除所有表数据，但保留表结构（用于测试环境重置）
"""
import os
import sys
from pathlib import Path

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# 确保可以导入同目录的模块
sys.path.insert(0, str(Path(__file__).parent))
from utils import get_db_config, load_env_file, print_db_info, wait_for_db

# 加载 .env 文件
env_path = load_env_file()
if env_path:
    print(f"📋 已加载环境变量文件: {env_path}")


def get_all_tables(conn, schema='public'):
    """获取所有表名"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = %s
        ORDER BY tablename;
    """, (schema,))
    tables = [row[0] for row in cursor.fetchall()]
    cursor.close()
    return tables


def truncate_all_tables(conn, schema='public'):
    """清空所有表的数据"""
    cursor = conn.cursor()
    tables = get_all_tables(conn, schema)

    if not tables:
        print("ℹ️  数据库中没有表")
        cursor.close()
        return True

    print(f"📋 找到 {len(tables)} 个表")

    try:
        print("🗑️  开始清空表数据...")
        table_names = [sql.Identifier(table) for table in tables]
        truncate_sql = sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(
            sql.SQL(', ').join(table_names)
        )

        cursor.execute(truncate_sql)
        if not conn.isolation_level == ISOLATION_LEVEL_AUTOCOMMIT:
            conn.commit()

        print(f"✅ 成功清空 {len(tables)} 个表的数据")
        cursor.close()
        return True

    except Exception as e:
        print(f"❌ 清空表数据失败: {e}")
        if not conn.isolation_level == ISOLATION_LEVEL_AUTOCOMMIT:
            conn.rollback()
        cursor.close()
        return False


def clean_database_data(config, schema: str = 'public'):
    """清理数据库数据"""
    try:
        conn = psycopg2.connect(
            host=config["host"],
            port=config["port"],
            user=config["user"],
            password=config["password"],
            database=config["db_name"],
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)

        if not truncate_all_tables(conn, schema):
            return False

        conn.close()
        return True

    except Exception as e:
        print(f"❌ 清理数据库失败: {e}")
        return False


def main():
    """主函数"""
    # 获取数据库配置
    config = get_db_config()
    schema = os.getenv("POSTGRES_SCHEMA", "public")

    print("=" * 60)
    print("🗑️  数据库数据清理")
    print("=" * 60)
    print_db_info(config)
    print(f"Schema: {schema}")
    print("=" * 60)
    print()
    print("⚠️  警告：此操作将删除所有表数据，但保留表结构！")
    print()

    if os.getenv("FORCE_CLEAN") != "true":
        response = input("确认继续？(yes/no): ").strip().lower()
        if response not in ['yes', 'y']:
            print("❌ 操作已取消")
            sys.exit(0)

    if not wait_for_db(config):
        print("❌ 无法连接到数据库，清理失败")
        sys.exit(1)

    if not clean_database_data(config, schema):
        print("❌ 数据库清理失败")
        sys.exit(1)

    print("=" * 60)
    print("✅ 数据库数据清理完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
