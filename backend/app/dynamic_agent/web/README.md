# Web Visualization API

Complete REST API for the web visualization system, supporting deep linking between Chat and Visualization pages.

**Status**: ✅ Production Ready (with Mock Data)
**Base URL**: `http://localhost:8888/api/web`

## 📚 Documentation

- **Full Documentation**: See [`docs/backend/agent/web/README.md`](../../../../docs/backend/agent/web/README.md)
- **Quick Start**: See [`docs/backend/agent/web/QUICKSTART.md`](../../../../docs/backend/agent/web/QUICKSTART.md)

## 📦 Core Files

| File | Purpose |
|------|---------|
| `models.py` | Pydantic data models and validation |
| `mock_data.py` | Realistic mock data generation |
| `routes.py` | FastAPI route handlers |
| `__init__.py` | Module initialization and exports |

## 🚀 Quick Start

```bash
# Start the server
uv run python -m agent.server

# API endpoints available at http://localhost:8888/api/web
```
