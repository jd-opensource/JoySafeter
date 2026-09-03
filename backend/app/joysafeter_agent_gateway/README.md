# JoySafeter Agent Gateway

Agent Gateway is the independently deployable control plane for the sandbox
egress boundary. Envoy remains the data plane. The service accepts resolved
egress policies from Orchestrator, renders authenticated Delta xDS resources,
tracks Envoy ACK/NACK, and maintains node placement.

## Ownership and data flow

PostgreSQL and the Orchestrator credential/identity services are the only
durable truth. Gateway has no database, Redis access, vault key, or provider
credential. Its xDS and replication state is disposable process memory.

```text
Orchestrator resolves policy + UserToken/AgentToken
  → authenticated management API
  → Gateway validates and stages one generation
  → Gateway publishes direct-xDS listener/cluster resources
  → Envoy ACK
  → Gateway commits and replicates the generation
  → Orchestrator may start the task
```

BotToken is used only inside the identity provider and must never enter the
management contract, Gateway, replica stream, or Envoy. Header values are
redacted from Debug/log output. They do exist in Gateway/Envoy memory and in the
authenticated hot-standby snapshot, so those workloads, admin endpoints, and
transport links are part of the trusted credential boundary.

## Availability

- Kubernetes Lease elects one ADS/management leader and supplies the fencing
  epoch. Lease loss revokes mutations and closes ADS streams.
- The leader publishes a digest-verified full snapshot, then ordered deltas;
  followers ACK each revision and retain a complete in-memory hot snapshot.
- Promotion starts from the verified snapshot, then Orchestrator validates it
  against PostgreSQL generations and replays missing or mismatched policies.
- Apply is transactional: validate → stage → publish → Envoy ACK → commit →
  follower ACK quorum → revalidate authority epoch.
- Invalid credentials, stale generations, ACK timeout, replication failure, or
  recovery mismatch fail closed.

## Runtime ports

| Port | Protocol | Purpose |
|---|---|---|
| `9092` | gRPC | Authenticated Delta ADS |
| `9093` | HTTP | Health, metrics, management, replica watch/ACK |

`/health/live`, `/health/ready`, and `/metrics` are unauthenticated and must be
restricted by network policy.

## Required configuration

| Variable | Purpose |
|---|---|
| `JOYSAFETER_XDS_AUTH_KEYRING` | JSON key-id to ADS token map |
| `JOYSAFETER_XDS_AUTH_WRITE_KEY_ID` | Active ADS key id |
| `JOYSAFETER_AGENT_GATEWAY_MANAGEMENT_TOKEN` | Orchestrator management Bearer token |
| `JOYSAFETER_AGENT_GATEWAY_REPLICATION_TOKEN` | Replica protocol Bearer token when HA is enabled |
| `JOYSAFETER_AGENT_GATEWAY_REPLICATION_URL` | Leader-only Gateway HTTP Service base URL |
| `JOYSAFETER_AGENT_GATEWAY_HOT_STANDBY_MIN_ACKS` | Required follower ACK quorum; default `1` |
| `JOYSAFETER_AGENT_GATEWAY_REPLICATION_ACK_TIMEOUT_MS` | Follower ACK timeout; default `1000` |
| `JOYSAFETER_AGENT_GATEWAY_LEADER_ELECTION_ENABLED` | Enable Kubernetes Lease election |
| `JOYSAFETER_AGENT_GATEWAY_LEADER_LEASE_NAME` | Lease name |
| `JOYSAFETER_AGENT_GATEWAY_LEADER_LEASE_DURATION_SECS` | Lease duration; default `15` |
| `JOYSAFETER_AGENT_GATEWAY_LEADER_RENEW_INTERVAL_SECS` | Renew interval; default `5` |
| `JOYSAFETER_AGENT_GATEWAY_NODE_VISIBILITY` | `node_scoped` or `unscoped` |
| `JOYSAFETER_AGENT_GATEWAY_DELIVERY_TIMEOUT_SECS` | Envoy ACK timeout; default `20` |
| `JOYSAFETER_AGENT_GATEWAY_SHUTDOWN_GRACE_SECS` | Drain limit; default `10` |

Tokens must be distinct random values with 32–512 non-whitespace ASCII bytes.
Use mesh mTLS for workload identity and transport encryption. The Gateway Pod
must not receive PostgreSQL, Redis, vault-encryption, storage, BotToken, or
provider credentials.

## Verification

```bash
cargo fmt --manifest-path backend/app/joysafeter_agent_gateway/Cargo.toml --all -- --check
cargo clippy --all-targets --manifest-path backend/app/joysafeter_agent_gateway/Cargo.toml -- -D warnings
cargo test --manifest-path backend/app/joysafeter_agent_gateway/Cargo.toml
```
