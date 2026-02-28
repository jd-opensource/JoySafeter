# 后端生产镜像 Dockerfile
# 支持可配置的基础镜像源和 pip 镜像源

# 可配置的基础镜像（默认使用官方镜像，可通过 ARG 切换到国内镜像）
ARG BASE_IMAGE_REGISTRY="swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/"
ARG PYTHON_VERSION=3.12-slim
FROM ${BASE_IMAGE_REGISTRY}python:${PYTHON_VERSION} AS base

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 可配置的 pip 镜像源（默认使用清华大学镜像源，可通过 ARG 切换到其他镜像）
ARG PIP_INDEX_URL=https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple
RUN pip install --no-cache-dir uv -i ${PIP_INDEX_URL}

# 构建阶段
FROM base AS builder

# 传递 pip 镜像源到构建阶段
ARG PIP_INDEX_URL=https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple
ARG UV_INDEX_URL=https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple

COPY pyproject.toml uv.lock* README.md ./

RUN uv sync --frozen --no-dev || uv sync --no-dev -i ${UV_INDEX_URL}

COPY . .

# 生产运行阶段
FROM base AS runner

RUN apt-get update && apt-get install -y \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 从构建阶段复制虚拟环境
COPY --from=builder /app/.venv /app/.venv
COPY . .

RUN mkdir -p /app/logs /app/.cache/uv

# 注意：将虚拟环境的 site-packages 放在 PYTHONPATH 前面，确保优先导入已安装的包
# 这样可以避免本地 alembic 目录与 alembic 包名冲突
# 使用 Python 版本号动态构建路径（Python 3.12）
ENV PYTHONPATH="/app/.venv/lib/python3.12/site-packages:/app"
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV UV_CACHE_DIR=/app/.cache/uv

EXPOSE 8000

CMD ["python", "-m", "gunicorn", "app.main:app", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--preload", "--timeout", "120"]
