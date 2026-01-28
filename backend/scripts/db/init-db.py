#!/usr/bin/env python3
"""
数据库初始化脚本
等待数据库就绪，创建数据库（如果不存在），然后运行 Alembic 迁移
"""

import os
import subprocess
import sys
from pathlib import Path

import psycopg2
from psycopg2 import sql

# 确保可以导入同目录的模块
sys.path.insert(0, str(Path(__file__).parent))
from utils import get_db_config, load_env_file, print_db_info, wait_for_db

# 加载 .env 文件
env_path = load_env_file()
if env_path:
    print(f"📋 已加载环境变量文件: {env_path}")


def fix_collation_warning(config):
    """修复 PostgreSQL collation 版本警告"""
    try:
        conn = psycopg2.connect(
            host=config["host"],
            port=config["port"],
            user=config["user"],
            password=config["password"],
            database=config["db_name"],
        )
        conn.autocommit = True
        cursor = conn.cursor()

        # 更新 collation 版本信息，消除警告
        cursor.execute(
            """
            UPDATE pg_database
            SET datcollversion = NULL
            WHERE datname = %s AND datcollversion IS NOT NULL
        """,
            (config["db_name"],),
        )

        if cursor.rowcount > 0:
            print(f"✅ 已修复数据库 {config['db_name']} 的 collation 版本警告")

        cursor.close()
        conn.close()
        return True
    except Exception as e:
        # 忽略错误，不影响主流程
        print(f"⚠️  修复 collation 警告时出错（可忽略）: {e}")
        return True


def create_database_if_not_exists(config):
    """如果数据库不存在则创建"""
    try:
        conn = psycopg2.connect(
            host=config["host"],
            port=config["port"],
            user=config["user"],
            password=config["password"],
            database="postgres",
        )
        conn.autocommit = True
        cursor = conn.cursor()

        db_name = config["db_name"]

        # 检查数据库是否存在
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
        exists = cursor.fetchone()

        if not exists:
            print(f"📦 创建数据库: {db_name}")
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))
            print(f"✅ 数据库创建成功: {db_name}")
        else:
            print(f"✅ 数据库已存在: {db_name}")
            # 如果数据库已存在，尝试修复 collation 警告
            fix_collation_warning(config)

        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ 创建数据库失败: {e}")
        return False


def run_migrations(config):
    """运行 Alembic 迁移"""
    print("🚀 运行数据库迁移...")

    # 自动检测工作目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if "/scripts/db" in script_dir or "\\scripts\\db" in script_dir:
        # 本地运行：backend/scripts/db/init-db.py -> backend/
        work_dir = os.path.dirname(os.path.dirname(script_dir))
    elif script_dir.startswith("/app"):
        # Docker 容器运行
        work_dir = "/app"
    else:
        # 默认使用当前工作目录
        work_dir = os.getcwd()

    print(f"📁 工作目录: {work_dir}")

    # 为 alembic 构造同步/异步 URL，并通过 env 传递
    host = config["host"]
    port = config["port"]
    user = config["user"]
    password = config["password"]
    db_name = config["db_name"]

    sync_url = f"postgresql://{user}:{password}@{host}:{port}/{db_name}"

    env = os.environ.copy()
    env["DATABASE_URL"] = sync_url
    env["POSTGRES_HOST"] = host
    env["POSTGRES_PORT"] = str(port)
    env["POSTGRES_USER"] = user
    env["POSTGRES_PASSWORD"] = password
    env["POSTGRES_DB"] = db_name

    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=work_dir,
        env=env,
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        print("✅ 数据库迁移完成")
        if result.stdout:
            print(result.stdout)
        return True
    else:
        print("❌ 数据库迁移失败")
        if result.stderr:
            print(result.stderr)
        return False


def main():
    """主函数"""
    # 获取数据库配置
    config = get_db_config()

    print("=" * 60)
    print("🚀 开始数据库初始化")
    print("=" * 60)
    print_db_info(config)
    print("=" * 60)

    # 1. 等待数据库就绪（连接到 postgres 数据库）
    postgres_config = config.copy()
    postgres_config["db_name"] = "postgres"
    if not wait_for_db(postgres_config):
        print("❌ 无法连接到数据库，初始化失败")
        sys.exit(1)

    # 2. 创建数据库（如果不存在）
    if not create_database_if_not_exists(config):
        print("❌ 数据库创建失败，初始化失败")
        sys.exit(1)

    # 3. 运行迁移
    if not run_migrations(config):
        print("❌ 数据库迁移失败，初始化失败")
        sys.exit(1)

    # 4. 修复 collation 警告（可选）
    fix_collation_warning(config)

    print("=" * 60)
    print("✅ 数据库初始化完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
