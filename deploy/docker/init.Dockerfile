# 数据库初始化 Dockerfile
# 支持可配置的基础镜像源和 pip 镜像源

# 可配置的基础镜像（默认使用官方镜像，可通过 ARG 切换到国内镜像）
ARG BASE_IMAGE_REGISTRY="swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/"
ARG PYTHON_VERSION=3.12-slim
FROM ${BASE_IMAGE_REGISTRY}python:${PYTHON_VERSION}

# 可配置的 pip 镜像源（默认使用清华大学镜像源，可通过 ARG 切换到其他镜像）
ARG PIP_INDEX_URL=https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    postgresql-client \
    build-essential \
    gcc \
    g++ \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# 设置工作目录
WORKDIR /app

# 复制精简的依赖文件
COPY requirements-db-init.txt .

# 安装 Python 依赖（只安装数据库初始化所需的包）
RUN pip install --no-cache-dir -r requirements-db-init.txt -i ${PIP_INDEX_URL}

# 复制数据库初始化脚本
COPY scripts/db/ scripts/db/

# 复制 Alembic 配置和迁移文件
COPY alembic.ini .
COPY alembic/ alembic/

# 复制应用核心文件（数据库和配置）
COPY app/__init__.py app/
COPY app/core/__init__.py app/core/
COPY app/core/database.py app/core/
COPY app/core/settings.py app/core/

# 复制数据模型（Alembic 需要导入所有模型）
COPY app/models/ app/models/

# 复制工具模块（message.py 需要 media.py 中的类型，__init__.py 需要 datetime.py）
COPY app/utils/__init__.py app/utils/
COPY app/utils/media.py app/utils/
COPY app/utils/datetime.py app/utils/

# 设置环境变量
# 注意：确保 Python 可以找到 app 模块
#ENV PYTHONPATH="/app"
ENV PYTHONPATH=/usr/local/lib/python3.12/site-packages


# 运行初始化脚本（默认，可在 docker-compose 中覆盖）
# 脚本路径相对于 backend 目录（context）
CMD ["python", "scripts/db/init-db.py"]
