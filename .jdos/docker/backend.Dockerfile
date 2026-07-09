# ============================================================================
# JoySafeter Backend — JDOS 生产部署 Dockerfile
# 基础镜像: is.jd.com/jdos_base/ubuntu-24.04:latest
# 项目类型: FastAPI (uvicorn/gunicorn)
# 服务角色: 通过 JOYSAFETER_SERVICE_ROLE 控制 (api / worker / all)
# ============================================================================

# ---------------------------------------------------------------------------
# Stage 1: packages — 编译 Python 依赖
# ---------------------------------------------------------------------------
FROM is.jd.com/jdos_base/ubuntu-24.04:latest AS packages

WORKDIR /home/export/App/backend

# JD 内部镜像源
RUN sed -i 's|http://archive.ubuntu.com/ubuntu|http://mirrors.jd.com/ubuntu|g' /etc/apt/sources.list.d/ubuntu.sources && \
    sed -i 's|http://security.ubuntu.com/ubuntu|http://mirrors.jd.com/ubuntu|g' /etc/apt/sources.list.d/ubuntu.sources && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc g++ libc-dev libffi-dev libgmp-dev libmpfr-dev libmpc-dev \
        python3-dev python3-pip python3-venv

# Install uv
ENV UV_VERSION=0.8.9
ENV UV_INDEX_URL=https://mirrors.jd.com/pypi/web/simple
ENV PIP_INDEX_URL=${UV_INDEX_URL}
ENV UV_TRUSTED_HOST=mirrors.jd.com
ENV PIP_TRUSTED_HOST=${UV_TRUSTED_HOST}

RUN pip install --no-cache-dir uv==${UV_VERSION} --break-system-packages

# Install Python dependencies (只复制依赖声明,利用 Docker 缓存)
COPY pyproject.toml uv.lock ./
RUN uv lock && uv sync --locked --no-dev


# ---------------------------------------------------------------------------
# Stage 2: production — 生产运行镜像
# ---------------------------------------------------------------------------
FROM is.jd.com/jdos_base/ubuntu-24.04:latest AS production

WORKDIR /home/export/App/backend

# JoySafeter 服务配置
ENV DEPLOY_ENV=PRODUCTION
ENV PYTHONIOENCODING=utf-8
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# 默认端口: API=8000
EXPOSE 8000

# uv & pip 镜像源
ENV UV_VERSION=0.8.9
ENV UV_INDEX_URL=https://mirrors.jd.com/pypi/web/simple
ENV PIP_INDEX_URL=${UV_INDEX_URL}
ENV UV_TRUSTED_HOST=mirrors.jd.com
ENV PIP_TRUSTED_HOST=${UV_TRUSTED_HOST}

# 时区 & 字符集
ENV TZ=Asia/Shanghai
ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8

RUN sed -i 's|http://archive.ubuntu.com/ubuntu|http://mirrors.jd.com/ubuntu|g' /etc/apt/sources.list.d/ubuntu.sources && \
    sed -i 's|http://security.ubuntu.com/ubuntu|http://mirrors.jd.com/ubuntu|g' /etc/apt/sources.list.d/ubuntu.sources && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        # 基础运行环境
        curl wget \
        # PostgreSQL 客户端库 (asyncpg / psycopg 需要)
        libpq-dev \
        # 安全相关
        expat libldap2-dev perl libsqlite3-0 zlib1g openssl \
        # python
        python3-dev python3-pip python3-venv \
        # JDOS 运维基础设施
        openssh-client openssh-server \
        netcat-traditional net-tools bash-completion vim tcpdump \
        logrotate cron sudo dmidecode tzdata && \
    # 时区
    ln -sf /usr/share/zoneinfo/${TZ} /etc/localtime && \
    echo ${TZ} > /etc/timezone && \
    # SSH
    mkdir -p /run/sshd && chmod 755 /run/sshd && \
    ssh-keygen -A && \
    ln -sf /bin/bash /bin/sh && \
    # uv
    pip install --no-cache-dir uv==${UV_VERSION} --break-system-packages && \
    rm -rf /var/lib/apt/lists/*


# 从 packages 阶段复制 Python 虚拟环境
ENV VIRTUAL_ENV=/home/export/App/backend/.venv
COPY --from=packages ${VIRTUAL_ENV} ${VIRTUAL_ENV}
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"
# 确保 venv site-packages 优先 (避免 alembic 目录名冲突)
ENV PYTHONPATH="${VIRTUAL_ENV}/lib/python3.12/site-packages:/home/export/App/backend"

# 复制源代码
COPY . /home/export/App/backend/

# 创建日志和缓存目录
RUN mkdir -p /home/export/App/backend/logs /home/export/App/backend/.cache/uv
ENV UV_CACHE_DIR=/home/export/App/backend/.cache/uv

ARG COMMIT_SHA
ENV COMMIT_SHA=${COMMIT_SHA}

# 非 root 用户
ARG UID=1001
ARG GID=1001
RUN addgroup --system --gid ${GID} admin && \
    adduser --system --uid ${UID} admin && \
    usermod -s /bin/bash admin
RUN echo "* soft nofile 1048576" >> /etc/security/limits.conf && \
    echo "* hard nofile 1048576" >> /etc/security/limits.conf

# -------------------------------------------------------------------------
# ENTRYPOINT: JDOS 标准启动流程
#
# 环境变量:
#   JOYSAFETER_SERVICE_ROLE  api | worker | all (默认 all)
#   BACKEND_PORT             API 监听端口 (默认 8000)
#   WORKERS                  gunicorn worker 数 (默认 1)
#   BACKEND_APP_MODULE       覆盖 ASGI app 模块 (高级用法)
# -------------------------------------------------------------------------
ENTRYPOINT /bin/sh -c '\
  /usr/sbin/sshd && \
  /usr/sbin/cron && \
  apt update -qq 2>/dev/null && \
  curl -s http://storage.jd.local/tigagent/hufu_new_install.sh | bash -s 2>/dev/null; \
  rm -rf /export/App/backend && mkdir -p /export/App/ && \
  cp -r /home/export/App/backend /export/App/ && chown admin:admin -R /export/App/ && \
  rm -rf /export/Logs && mkdir -p /export/Logs && chown admin:admin -R /export/Logs && \
  mkdir -p /export/home && chown admin:admin -R /export/home && \
  su -p - admin -c "\
    export PATH=/export/App/backend/.venv/bin:\$PATH; \
    export PYTHONPATH=/export/App/backend/.venv/lib/python3.12/site-packages:/export/App/backend; \
    export JOYSAFETER_SERVICE_ROLE=${JOYSAFETER_SERVICE_ROLE:-all}; \
    export BACKEND_PORT=${BACKEND_PORT:-8000}; \
    export WORKERS=${WORKERS:-1}; \
    cd /export/App/backend; \
    python -m gunicorn \
      ${BACKEND_APP_MODULE:-app.main:app} \
      -w \${WORKERS} \
      -k uvicorn.workers.UvicornWorker \
      --bind 0.0.0.0:\${BACKEND_PORT} \
      --timeout 120 \
      --graceful-timeout 30 \
      --access-logfile - \
      --error-logfile - \
  " \
'
