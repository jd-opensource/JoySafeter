#!/usr/bin/env python3
"""
数据库脚本工具模块
提供统一的数据库配置获取和连接等待功能
"""

import os
import sys
import time
from typing import Optional, TypedDict

import psycopg2
from psycopg2 import OperationalError


class DBConfig(TypedDict):
    """数据库配置类型"""

    user: str
    password: str
    host: str
    port: int
    db_name: str


def load_env_file() -> Optional[str]:
    """
    加载 .env 文件
    返回加载的文件路径，如果未加载则返回 None
    """
    try:
        from dotenv import load_dotenv

        # 自动检测 .env 文件位置
        script_dir = os.path.dirname(os.path.abspath(__file__))
        env_paths = [
            os.path.join(script_dir, "../../.env"),  # backend/.env
            "/app/.env",  # Docker 容器内
            ".env",  # 当前目录
        ]

        for env_path in env_paths:
            if os.path.exists(env_path):
                load_dotenv(env_path, override=False)
                return env_path
    except ImportError:
        pass

    return None


def get_db_config(require_all: bool = True) -> DBConfig:
    """
    从环境变量获取数据库配置

    从 POSTGRES_* 环境变量构建配置

    Args:
        require_all: 是否要求所有配置项必须存在，否则报错退出

    Returns:
        DBConfig: 数据库配置字典
    """
    # 从分项环境变量获取
    is_in_container = os.path.exists("/app")

    if is_in_container:
        host = os.getenv("POSTGRES_HOST", "db")
        port = int(os.getenv("POSTGRES_PORT", "5432"))
    else:
        host = os.getenv("POSTGRES_HOST", "localhost")
        # 本地运行优先使用 POSTGRES_PORT_HOST（Docker 映射端口）
        port = int(os.getenv("POSTGRES_PORT_HOST") or os.getenv("POSTGRES_PORT", "5432"))

    # 本地运行且配置了容器内主机名时，自动纠正
    if (not is_in_container) and host == "db":
        print("⚠️  本地运行但 POSTGRES_HOST=db，自动改为 localhost")
        host = "localhost"

    user = os.getenv("POSTGRES_USER")
    password = os.getenv("POSTGRES_PASSWORD")
    db_name = os.getenv("POSTGRES_DB")

    # 检查必要的配置是否存在
    if require_all:
        missing = []
        if not user:
            missing.append("POSTGRES_USER")
        if not password:
            missing.append("POSTGRES_PASSWORD")
        if not db_name:
            missing.append("POSTGRES_DB")

        if missing:
            print(f"❌ 错误：未设置以下环境变量：{', '.join(missing)}")
            print("   请在 backend/.env 文件中配置数据库信息")
            sys.exit(1)

    return DBConfig(
        user=user or "",
        password=password or "",
        host=host,
        port=port,
        db_name=db_name or "",
    )


def wait_for_db(
    config: Optional[DBConfig] = None,
    max_retries: int = 30,
    retry_interval: int = 2,
) -> bool:
    """
    等待数据库连接可用

    Args:
        config: 数据库配置，如果为 None 则自动获取
        max_retries: 最大重试次数
        retry_interval: 重试间隔（秒）

    Returns:
        bool: 连接是否成功
    """
    if config is None:
        config = get_db_config()

    host = config["host"]
    port = config["port"]
    user = config["user"]
    password = config["password"]
    database = config["db_name"]

    print(f"🔍 等待数据库就绪 ({host}:{port})...")

    for i in range(max_retries):
        try:
            conn = psycopg2.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                database=database,
                connect_timeout=5,
            )
            conn.close()
            print("✅ 数据库已就绪")
            return True
        except OperationalError as e:
            if i < max_retries - 1:
                print(f"⏳ 尝试 {i + 1}/{max_retries}: 数据库未就绪，等待中...")
                time.sleep(retry_interval)
            else:
                print(f"❌ 数据库连接失败: {e}")
                return False

    return False


def print_db_info(config: DBConfig) -> None:
    """打印数据库配置信息（隐藏密码）"""
    print(f"数据库主机: {config['host']}:{config['port']}")
    print(f"数据库用户: {config['user']}")
    print(f"数据库名称: {config['db_name']}")
