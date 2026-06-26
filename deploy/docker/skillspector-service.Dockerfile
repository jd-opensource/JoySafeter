ARG BASE_IMAGE_REGISTRY="swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/"
ARG PYTHON_VERSION=3.12-slim-bookworm
FROM ${BASE_IMAGE_REGISTRY}python:${PYTHON_VERSION}

WORKDIR /app

ARG PIP_INDEX_URL=https://pypi.org/simple

RUN python -m venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /tmp/skillspector-src
COPY --from=skillspector pyproject.toml README.md ./
COPY --from=skillspector src/ ./src/

RUN pip install --no-cache-dir --upgrade pip -i ${PIP_INDEX_URL} \
    && pip install --no-cache-dir -i ${PIP_INDEX_URL} . fastapi "uvicorn[standard]"

WORKDIR /app
COPY app.py /app/joysafeter_skillspector/app.py

ENV PYTHONUNBUFFERED=1
EXPOSE 8010

# Concurrency tuning (override via the skillspector service environment):
#   SKILLSPECTOR_WORKERS           — uvicorn worker processes. Scans are
#                                    CPU-bound (semgrep static analysis), so set
#                                    this to the container's CPU quota to get
#                                    real parallelism past the GIL. Default 2.
#   SKILLSPECTOR_LIMIT_CONCURRENCY — max in-flight requests before uvicorn
#                                    returns 503. Keep it a touch above
#                                    workers so a small queue is allowed but
#                                    overload sheds fast (backend treats a
#                                    failed scan as fail-open). Default 4.
ENV SKILLSPECTOR_WORKERS=2 \
    SKILLSPECTOR_LIMIT_CONCURRENCY=4

# Shell form so the env vars expand at container start.
CMD uvicorn joysafeter_skillspector.app:app \
    --host 0.0.0.0 --port 8010 \
    --workers "${SKILLSPECTOR_WORKERS}" \
    --limit-concurrency "${SKILLSPECTOR_LIMIT_CONCURRENCY}"
