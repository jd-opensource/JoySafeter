# Development Guide

This guide covers host-based development. Full-stack installation, image builds, and deployment
use [`deploy/deploy.sh`](deploy/README.md) instead.

## Prerequisites

- Docker Engine or Docker Desktop with Compose v2
- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Rust toolchain from `rust-toolchain.toml`
- Bun 1.2+ and Node.js 20+
- Git

## One-command Development Stack

```bash
cd deploy
./deploy.sh dev
```

The script starts PostgreSQL, Redis, Envoy, and supporting containers, runs migrations, then starts
the Python API, Rust orchestrator, Python worker, and Next.js frontend on the host.

Open:

- Frontend: `http://localhost:3000`
- API: `http://localhost:8000`
- API docs: `http://localhost:8000/docs`

Press `Ctrl+C` to stop host processes. Supporting containers remain available for the next run;
stop them with `cd deploy && docker compose down`.

## Install Dependencies

```bash
cd backend
uv sync --dev
cp -n env.example .env

cd ../frontend
bun install
cp -n env.example .env.local
```

Environment definitions have one source of truth:

- `backend/env.example` for backend variables
- `frontend/env.example` for frontend variables
- `deploy/.env.example` for Compose and deployment overrides

## Run Components Manually

Start PostgreSQL, Redis, Envoy, and migrations through `./deploy/deploy.sh dev` at least once, then
run components in separate terminals when focused debugging is needed.

```bash
# API
cd backend
JOYSAFETER_SERVICE_ROLE=api \
uv run uvicorn app.joysafeter_api.main:app --reload --host 0.0.0.0 --port 8000

# Worker
cd backend
JOYSAFETER_SERVICE_ROLE=worker WORKER_HTTP_HOST=127.0.0.1 \
uv run uvicorn app.joysafeter_worker.main:app --host 127.0.0.1 --port 8002 --workers 1

# Rust orchestrator
cargo run --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml --release

# Frontend
cd frontend
bun run dev
```

## Runner Protocol Code Generation

`proto/joysafeter.proto` is the only source of truth for the Runner protocol. Regenerate the
checked-in Python protobuf modules after every schema change:

```bash
cd backend
uv run python scripts/generate_runner_proto.py
```

The orchestrator regenerates `src/grpc/joysafeter.rs` through its `build.rs` during Cargo builds;
the sandbox runner generates its Rust module into Cargo `OUT_DIR`. Do not hand-edit generated
protobuf files.

## Tests and Quality Checks

```bash
# Backend
cd backend
uv run pytest
uv run ruff check .
uv run ruff format --check .

# Frontend
cd frontend
bun run test
bun run lint
bun run type-check
bun run format:check

# Rust orchestrator
cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml

# Sandbox runner workspace
cargo test --manifest-path sandbox-runner/Cargo.toml

# MCP connection matrix (L1 is offline; L2 needs a running local API)
cd tests/mcp_connection_matrix
../../backend/.venv/bin/python -m pytest test_matrix_infrastructure.py test_l1_direct.py
JOYSAFETER_TEST_PASSWORD='<local-admin-password>' \
  ../../backend/.venv/bin/python -m pytest test_l2_contract.py
```

Database-backed Rust tests read `JOYSAFETER_TEST_DATABASE_URL`. Point it at a dedicated,
fully migrated test database that is not used by any running API, worker, or orchestrator.
A live scheduler can legitimately claim test-created `pending` tasks and make state-machine
assertions nondeterministic; never run these tests against a deployed environment database.

Install repository hooks after backend dependencies are ready:

```bash
cd backend
uv run pre-commit install --install-hooks
uv run pre-commit run --all-files
```

## Database Migrations

```bash
cd backend
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head
```

Review generated migrations before committing them. Deployment automatically runs
`alembic upgrade head`; do not maintain a second manual deployment procedure here.

## xDS Control Plane Verification

Run the focused control-plane checks from the repository root:

```bash
cd backend
../backend/.venv/bin/pytest -q \
  tests/test_xds_control_plane_architecture.py \
  tests/test_typed_id_architecture.py
cd ..

cargo fmt --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml --all -- --check
cargo check --all-targets --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml
cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml \
  --test public_surface_contract \
  --test runner_transport_boundary \
  --test runtime_supervision_contract \
  --test network_policy_composition_contract \
  --test network_policy_service_contract \
  --test sandbox_destroy_boundary \
  --test xds_placement_reconciliation \
  --test envoy_capability_boundary \
  --test envoy_render_boundary \
  --test xds_authority_lifecycle \
  --test xds_delivery_contract \
  --test xds_delivery_transport \
  --test xds_observability \
  --test xds_recovery_lifecycle \
  --test xds_resource_ownership \
  --test xds_transport_contract

# Destructive Docker-backed Envoy fixture
JOYSAFETER_RUN_LIVE_ENVOY=1 cargo test \
  --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml \
  --test mcp_live_envoy -- --ignored
```

## Local Kubernetes Verification (Colima + Helm)

Colima must be running with Kubernetes enabled and the active kubectl context must be `colima`.
Colima plus the Helm chart is the only supported local Kubernetes verification path.

```bash
colima status
kubectl config current-context
kubectl get nodes
./deploy/deploy.sh k8s deploy --dry-run \
  --release joysafeter-local \
  --namespace joysafeter-local

# 使用刚构建的统一镜像 Registry 覆盖 Helm 中的 orchestrator 与四个 runtime 镜像
./deploy/deploy.sh --tag local k8s deploy --dry-run --sync-images \
  --release joysafeter-local \
  --namespace joysafeter-local

# 部署后验证控制面、唯一 xDS authority、Envoy 节点收敛和四个 runtime 镜像
./deploy/deploy.sh k8s verify \
  --release joysafeter-local \
  --namespace joysafeter-local \
  --runtime-images
```

Runner gRPC and ADS must render as distinct service ports. Deployment verification must wait for
the orchestrator readiness endpoint and the Envoy DaemonSet before exercising Runner and managed
network-policy flows. `--runtime-images` creates short-lived probe Pods and therefore requires Pod
create/delete permission in the target namespace.

## Component Guides

- Backend structure and service roles: [`backend/README.md`](backend/README.md)
- Frontend structure and scripts: [`frontend/README.md`](frontend/README.md)
- Runtime architecture: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- Contribution process: [`CONTRIBUTING.md`](CONTRIBUTING.md)
