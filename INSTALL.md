# JoySafeter Installation

JoySafeter maintains one full-stack installation path: **Docker Compose through
`deploy/deploy.sh`**. Running Python, Rust, and Bun processes on the host is a development
workflow, not a deployment mode.

## Requirements

- Docker Engine or Docker Desktop
- Docker Compose v2
- Git
- At least 4 CPU cores and 8 GB RAM recommended
- `linux/amd64` or `linux/arm64`

## First Installation

```bash
cd deploy
./deploy.sh doctor
./deploy.sh local
```

`doctor` checks Docker, Compose, ports, environment files, and the target architecture without
starting services. `local` prepares environment files, generates and synchronizes the stable
application/Vault keys plus the database password, builds the core services and the default
Claude Code runtime, runs database migrations, and starts the complete stack. Existing valid keys
are preserved.

Open:

- Frontend: `http://localhost:3000`
- API: `http://localhost:8000`
- API docs: `http://localhost:8000/docs`

## Daily Operations

```bash
cd deploy
./deploy.sh up                 # Start or update with existing images
./deploy.sh status             # Show service status
./deploy.sh logs api worker    # Follow logs
./deploy.sh down               # Stop services and keep data volumes
```

## Next Documents

- Builds, image publishing, and deployment: [`deploy/README.md`](deploy/README.md)
- Host-based development and tests: [`DEVELOPMENT.md`](DEVELOPMENT.md)
- Pre-release gates: [`docs/PRODUCTION_READINESS.md`](docs/PRODUCTION_READINESS.md)

Use `./deploy.sh --help` as the command reference. Other documents intentionally avoid copying
the complete option list.
