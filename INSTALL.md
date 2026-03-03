# JoySafeter Installation Guide

Below you will find comprehensive setup instructions depending on your deployment needs.

## Prerequisites

| Requirement | Version |
|-------------|---------|
| Docker | 20.10+ |
| Docker Compose | 2.0+ |
| Python | 3.12+ (for local development) |
| Node.js | 20+ (for local development) |
| PostgreSQL | 15+ (optional, if not using Docker) |
| Redis | 7+ (required, used for caching and session management) |

## Solution 1: One-Click Run (Recommended)

```bash
# Initialize environment & Build images locally & Start services automatically
sh deploy/quick-start.sh
```

## Solution 2: Manual Deployment

```bash
cd deploy

# 1. Build images
sh deploy.sh build --all

# 2. Initialize environment variables
cp ../frontend/env.example ../frontend/.env
cp ../backend/env.example ../backend/.env

# IMPORTANT!! Configure TAVILY_API_KEY for search (Register at https://www.tavily.com/)
# Replace tvly-* with your actual API Key
echo 'TAVILY_API_KEY=tvly-*' >> ../backend/.env

# 3. Initialize database
docker compose --profile init up

# 4. Start services
docker compose -f docker-compose.yml up

# Stop services
docker compose -f docker-compose.yml down
```

## Using Pre-built Docker Images

We provide pre-built Docker images on GitHub Container Registry. You can use them directly:

```bash
# Pull images from GitHub Container Registry
docker pull docker.io/jdopensource/joysafeter-backend:latest
docker pull docker.io/jdopensource/joysafeter-frontend:latest
docker pull docker.io/jdopensource/joysafeter-mcp:latest

# Or use docker-compose with pre-built images
cd deploy
export DOCKER_REGISTRY=docker.io/jdopensource
docker-compose -f docker-compose.yml up -d
```

**Available Images:**
- `docker.io/jdopensource/joysafeter-backend:latest` - Backend API service
- `docker.io/jdopensource/joysafeter-frontend:latest` - Frontend web application
- `docker.io/jdopensource/joysafeter-mcp:latest` - MCP server with security tools

All images support multi-architecture (amd64, arm64).

## Alternative Setup Methods

### Option 1: Interactive Installation

Use the installation wizard to configure your environment:

```bash
cd deploy

# Interactive installation
./install.sh

# Or quick install for development
./install.sh --mode dev --non-interactive
```

After installation, start services with scenario-specific scripts:

```bash
# Development scenario
./scripts/dev.sh

# Production scenario
./scripts/prod.sh

# Test scenario
./scripts/test.sh

# Minimal scenario (middleware only)
./scripts/minimal.sh

# Local development (backend/frontend run locally)
./scripts/dev-local.sh
```

### Option 2: Manual Docker Compose

For advanced users who want full control:

```bash
cd deploy

# 1. Create configuration files
cp .env.example .env
cd ../backend && cp env.example .env

# 2. Start middleware (PostgreSQL + Redis)
cd ../deploy
./scripts/start-middleware.sh

# 3. Start full services
docker-compose up -d
```

### Option 3: Environment Check

Before starting, you can check your environment:

```bash
cd deploy
./scripts/check-env.sh
```

This will verify:
- Docker installation and status
- Docker Compose version
- Port availability
- Configuration files
- Disk space

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

# Start server
uv run uvicorn app.main:app --reload --port 8000
```

</details>

<details>
<summary><strong>Frontend Setup</strong></summary>

```bash
cd frontend

# Install dependencies
bun install  # or: npm install

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
