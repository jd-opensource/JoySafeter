# base image
FROM is.jd.com/jdos_base/ubuntu-24.04:latest AS packages

WORKDIR /home/export/App/api


# if you located in China, you can use aliyun mirror to speed up
# RUN sed -i 's@deb.debian.org@mirrors.aliyun.com@g' /etc/apt/sources.list.d/debian.sources

RUN sed -i 's|http://archive.ubuntu.com/ubuntu|http://mirrors.jd.com/ubuntu|g' /etc/apt/sources.list.d/ubuntu.sources && \
    sed -i 's|http://security.ubuntu.com/ubuntu|http://mirrors.jd.com/ubuntu|g' /etc/apt/sources.list.d/ubuntu.sources && \
    apt-get update \
    && apt-get install -y --no-install-recommends gcc g++ libc-dev libffi-dev libgmp-dev libmpfr-dev libmpc-dev

# Install uv
ENV UV_VERSION=0.8.9
ENV UV_INDEX_URL=https://mirrors.jd.com/pypi/web/simple
ENV PIP_INDEX_URL=${UV_INDEX_URL}
ENV UV_TRUSTED_HOST=mirrors.jd.com
ENV PIP_TRUSTED_HOST=${UV_TRUSTED_HOST}

RUN apt-get install -y --no-install-recommends \
    python3-dev \
    python3-pip \
    python3-venv \
    && pip install --no-cache-dir uv==${UV_VERSION} --break-system-packages

# Install Python dependencies
COPY pyproject.toml uv.lock ./
RUN  uv lock && uv sync --locked --no-dev

# production stage
FROM is.jd.com/jdos_base/ubuntu-24.04:latest AS production

WORKDIR /home/export/App/api

ENV FLASK_APP=app.py
ENV EDITION=SELF_HOSTED
ENV DEPLOY_ENV=PRODUCTION
ENV CONSOLE_API_URL=http://127.0.0.1:5001
ENV CONSOLE_WEB_URL=http://127.0.0.1:3000
ENV SERVICE_API_URL=http://127.0.0.1:5001
ENV APP_WEB_URL=http://127.0.0.1:3000

EXPOSE 5001

# Install uv
ENV UV_VERSION=0.8.9
ENV UV_INDEX_URL=https://mirrors.jd.com/pypi/web/simple
ENV PIP_INDEX_URL=${UV_INDEX_URL}
ENV UV_TRUSTED_HOST=mirrors.jd.com
ENV PIP_TRUSTED_HOST=${UV_TRUSTED_HOST}

# set timezone
ENV TZ=Asia/Shanghai

# Set UTF-8 locale
ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8
ENV PYTHONIOENCODING=utf-8

RUN sed -i 's|http://archive.ubuntu.com/ubuntu|http://mirrors.jd.com/ubuntu|g' /etc/apt/sources.list.d/ubuntu.sources && \
    sed -i 's|http://security.ubuntu.com/ubuntu|http://mirrors.jd.com/ubuntu|g' /etc/apt/sources.list.d/ubuntu.sources && \
    apt-get update \
    # Install dependencies
    && apt-get install -y --no-install-recommends \
        # basic environment
        curl nodejs libgmp-dev libmpfr-dev libmpc-dev \
        # For Security
        expat libldap2-dev perl libsqlite3-0 zlib1g \
        # install fonts to support the use of tools like pypdfium2
        fonts-noto-cjk \
        # install a package to improve the accuracy of guessing mime type and file extension
        media-types \
        # install libmagic to support the use of python-magic guess MIMETYPE
        libmagic1 \
        python3-dev \
        python3-pip \
        python3-venv \
        wget \
        openssl openssh-client openssh-server \
        netcat-traditional net-tools bash-completion vim tcpdump logrotate cron sudo dmidecode tzdata && \
    ln -sf /usr/share/zoneinfo/${TZ} /etc/localtime && \
    echo ${TZ} > /etc/timezone && \
    mkdir -p /run/sshd && chmod 755 /run/sshd && \
    ssh-keygen -A && \
    ln -sf /bin/bash /bin/sh && \
    pip install --no-cache-dir uv==${UV_VERSION} --break-system-packages && \
    rm -rf /var/lib/apt/lists/*


# Copy Python environment and packages
ENV VIRTUAL_ENV=/home/export/App/api/.venv
COPY --from=packages ${VIRTUAL_ENV} ${VIRTUAL_ENV}
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"

# Download nltk data
#RUN python -c "import nltk; nltk.download('punkt'); nltk.download('averaged_perceptron_tagger')"
COPY docker/nltk_data /root/nltk_data

ENV TIKTOKEN_CACHE_DIR=/home/export/App/api/.tiktoken_cache

#RUN python -c "import tiktoken; tiktoken.encoding_for_model('gpt2')"
COPY  docker/tiktoken_cache $TIKTOKEN_CACHE_DIR

# Copy source code
COPY . /home/export/App/api/

# Copy entrypoint
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ARG COMMIT_SHA
ENV COMMIT_SHA=${COMMIT_SHA}


# Don't run production as root
ARG UID=1001
ARG GID=1001
RUN addgroup --system --gid ${GID} admin && adduser --system --uid ${UID} admin && usermod -s /bin/bash admin
RUN echo "* soft nofile 1048576" >> /etc/security/limits.conf && \
    echo "* hard nofile 1048576" >> /etc/security/limits.conf

#ENTRYPOINT ["/bin/bash", "/entrypoint.sh"]

ENTRYPOINT /bin/sh -c '\
#  echo $PATH && ls -l $(which gunicorn)  && \
# export $(grep -v "^#" ./.env | xargs) && \
  /usr/sbin/sshd && \
  /usr/sbin/cron && \
  apt update && \
  curl -s http://storage.jd.local/tigagent/hufu_new_install.sh | bash -s && \
  rm -rf /export/App/api  && mkdir -p /export/App/ && \
  cp -r /home/export/App/api /export/App/ &&  chown admin:admin -R /export/App/ && \
  rm -rf /export/Logs && mkdir -p /export/Logs && chown admin:admin -R /export/Logs && \
  mkdir -p /export/home && chown admin:admin -R /export/home && \
  su -p - admin -c "export PATH=/export/App/api/.venv/bin:$PATH; export MODE=${MODE};export CELERY_MIN_WORKERS=${CELERY_MIN_WORKERS};export CELERY_AUTO_SCALE=${CELERY_AUTO_SCALE};export CELERY_MAX_WORKERS=${CELERY_MAX_WORKERS};export SERVER_WORKER_AMOUNT=${SERVER_WORKER_AMOUNT};export SERVER_WORKER_CONNECTIONS=${SERVER_WORKER_CONNECTIONS};export CELERY_QUEUES=${CELERY_QUEUES};export GUNICORN_MAX_REQUESTS=${GUNICORN_MAX_REQUESTS};export GUNICORN_MAX_REQUESTS_JITTER=${GUNICORN_MAX_REQUESTS_JITTER};export GUNICORN_GRACEFUL_TIMEOUT=${GUNICORN_GRACEFUL_TIMEOUT};cd /export/App/api; /entrypoint.sh" \
'
