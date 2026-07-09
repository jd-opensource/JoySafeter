# JoySafeter Installation Guide

Below you will find comprehensive setup instructions depending on your deployment needs.

## Prerequisites

- Docker 20.10+ and Docker Compose 2.0+
- Python 3.12+ and Node.js 20+ (only for local development)
- PostgreSQL/Redis are included in Docker deployment

## Recommended: Docker Compose

```bash
cd deploy
./deploy.sh doctor
./deploy.sh local
```

`doctor` prepares missing env files and checks Docker, Compose, the Docker daemon CPU
architecture, SkillSpector sources, Docker socket access, ports, and the Compose config. It
does not start containers. `local` repeats the checks, starts PostgreSQL/Redis/SkillSpector,
waits for local Redis, runs database migrations, and then starts the full local stack.

Access points:

- Frontend: `http://localhost:3000`
- Backend API: `http://localhost:8000`
- API Docs: `http://localhost:8000/docs`

The backend runtime is split into Python `api`, Rust `orchestrator-rs`, and Python `worker`
services, alongside PostgreSQL, Redis, Envoy, and SkillSpector. The Python orchestrator profile
has been removed; use the `rust-orchestrator` profile through `deploy.sh local`.

For cloud PostgreSQL/Redis, image building, prebuilt images, and troubleshooting, see
[deploy/README.md](deploy/README.md).
For service ownership, runtime topology, data flow, and deployment-mode selection, also see
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Using Pre-built Docker Images

```bash
cd deploy
./deploy.sh doctor

# Pull writes BACKEND_FULL_IMAGE, FRONTEND_FULL_IMAGE, ORCHESTRATOR_RS_FULL_IMAGE,
# and SKILLSPECTOR_FULL_IMAGE into deploy/.env after the images are pulled.
./deploy.sh pull --registry registry.example.com/your-org --tag v0.3.2
docker compose --profile local-redis --profile rust-orchestrator up -d --no-build
```

## Local Test One-Command Startup

```bash
cd deploy
./local-test.sh
```


## Environment Check

```bash
cd deploy
./deploy.sh doctor
```

## Manual Setup

<details>
<summary><strong>Backend Setup</strong></summary>

```bash
cd backend

# Install uv package manager
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create environment and install dependencies
uv venv && source .venv/bin/activate
uv sync

# Configure environment
cp env.example .env
# Edit .env with your settings

# Initialize database
createdb joysafeter
alembic upgrade head

# Start API
JOYSAFETER_SERVICE_ROLE=api \
uv run uvicorn app.joysafeter_api.main:app --reload --host 0.0.0.0 --port 8000
```

> To match the Compose runtime, also start Rust orchestrator and the worker:
>
> ```bash
> cd backend/app/joysafeter_orchestrator_rs
> JOYSAFETER_GRPC_HOST=0.0.0.0 JOYSAFETER_GRPC_PORT=9090 cargo run --release
>
> cd backend
> JOYSAFETER_SERVICE_ROLE=worker \
> uv run uvicorn app.joysafeter_worker.main:app --host 127.0.0.1 --port 8002 --workers 1
> ```
>
> See [DEVELOPMENT.md](DEVELOPMENT.md).

</details>

<details>
<summary><strong>Frontend Setup</strong></summary>

```bash
cd frontend

# Install dependencies
bun install

# Configure environment
cp env.example .env.local

# Start development server
bun run dev
```

</details>

## Access Points

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| API Documentation | http://localhost:8000/docs |
| ReDoc | http://localhost:8000/redoc |

## Troubleshooting

- Run `cd deploy && ./deploy.sh doctor` first. It validates the same env, platform, socket,
  port, SkillSpector, and Compose prerequisites used by `./deploy.sh local`.
- If you are on Apple Silicon or Colima, let `deploy.sh local` auto-detect the Docker daemon
  architecture, or force it with `./deploy.sh local --arch arm64`.
- If database tables are missing after a manual Compose start, run
  `docker compose --profile local-redis --profile rust-orchestrator --profile init run --rm db-init`.
- If you use cloud Redis, leave off the `local-redis` profile and set `REDIS_URL` in `deploy/.env`.
  For cloud PostgreSQL, override the `POSTGRES_*` variables there as well.
