# JoySafeter Installation

JoySafeter is not yet released for production. Use Docker Compose for the supported full-stack setup.

## Requirements

- Docker 20.10+
- Docker Compose 2+
- At least 4 CPU cores and 8 GB RAM recommended for the complete local stack
- Python 3.12+, Rust, and Bun are only required for host-based development

## First Local Deployment

```bash
cd deploy
./deploy.sh doctor
./deploy.sh local
```

`local` builds the core images, starts PostgreSQL and Redis, runs database migrations, and starts frontend, API, worker, Rust orchestrator, Envoy, and SkillSpector.

Open:

- Frontend: `http://localhost:3000`
- API: `http://localhost:8000`
- API docs: `http://localhost:8000/docs`

## Fast Restart or Update

After images exist locally:

```bash
cd deploy
./deploy.sh up
```

`up` skips image builds and SkillSpector source preparation, but still runs preflight checks and database migrations.

## Deploy Pre-built Images

```bash
cd deploy
./deploy.sh pull --registry registry.example.com/your-org --tag v0.3.2
./deploy.sh up
```

Use immutable version tags outside local development.

## Operations

```bash
cd deploy
./deploy.sh status
./deploy.sh logs api worker
./deploy.sh restart frontend
./deploy.sh down
```

## Host-based Development

For Python, Rust, and frontend processes running directly on the host, use [`DEVELOPMENT.md`](DEVELOPMENT.md) or:

```bash
cd deploy
./local-test.sh
```

## Next Documents

- Deployment modes and troubleshooting: [`deploy/README.md`](deploy/README.md)
- Runtime architecture: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- Pre-release gates: [`docs/PRODUCTION_READINESS.md`](docs/PRODUCTION_READINESS.md)
