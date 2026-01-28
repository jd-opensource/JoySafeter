#!/usr/bin/env python3
"""
等待数据库就绪的 Python 脚本
用于在 Docker 容器中等待数据库服务可用
"""

import sys
from pathlib import Path

# 确保可以导入同目录的模块
sys.path.insert(0, str(Path(__file__).parent))
from utils import get_db_config, load_env_file, wait_for_db

# 加载 .env 文件
env_path = load_env_file()
if env_path:
    print(f"📋 已加载环境变量文件: {env_path}")


if __name__ == "__main__":
    # 获取数据库配置并等待连接
    config = get_db_config()

    if not wait_for_db(config):
        sys.exit(1)
