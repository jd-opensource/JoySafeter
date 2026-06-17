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
COPY skillspector_service/ /app/skillspector_service/

ENV PYTHONUNBUFFERED=1
EXPOSE 8010

CMD ["uvicorn", "skillspector_service.app:app", "--host", "0.0.0.0", "--port", "8010"]
