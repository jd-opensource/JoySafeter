# JoySafeter Docs

This directory contains code-reviewed documentation for the current v2 managed-agent platform.
Use the repository code as the source of truth when updating these files.

## Start Here

- [Documentation status](./DOCUMENTATION_STATUS.md) - current review coverage and known follow-up areas.
- [Architecture overview](./ARCHITECTURE.md) / [中文架构总览](./ARCHITECTURE_CN.md) - service collaboration contracts, runtime topology, data flow, sandbox isolation, and deployment shape.
- [Tutorials](./tutorials/README.md) - step-by-step guides for model secrets, MCP, skills, and running an Agent.
- [API notes](./api/openapi.md) - current API surface notes and response envelope details.

## Supporting Docs

- [Production hardening plan](./production-hardening-plan.md) - implemented reliability pieces and remaining production work.
- [K8s sandbox egress and secret boundary architecture](./plans/2026-07-30-k8s-sandbox-egress-security-architecture.md) - proposed design for production-grade K8s sandbox egress, credential isolation, and multi-provider execution-plane parity.
- [Historical plans](./plans/) - implementation plans and parity notes; each file may include a current status banner.
- [Assets inventory](./assets/README.md) - committed images and screenshot refresh notes.
