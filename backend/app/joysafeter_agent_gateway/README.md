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
  → authenticated bidirectional `GatewayManagementService.PolicyStream`
  → Gateway validates and stages one generation
  → Gateway publishes direct-xDS listener/cluster resources
  → Envoy ACK
  → Gateway commits and replicates the generation
  → Gateway returns the terminal result with the caller's command_id
```

The Gateway never connects back to Orchestrator. Authenticated callers open the
stream, retain durable policy intent, and replay unacknowledged commands with the
same command ID after reconnect. Commands for the same sandbox are processed by
one dedicated ordered lane; independent sandboxes share a global concurrency
limit without hash collisions. Replaying
an already-active generation is an in-memory no-op and does not republish xDS or
replicate another delta.

BotToken is used only inside the identity provider and must never enter the
management contract, Gateway, replica stream, or Envoy. Header values are
redacted from Debug/log output. They do exist in Gateway/Envoy memory and in the
authenticated hot-standby snapshot, so those workloads, admin endpoints, and
transport links are part of the trusted credential boundary.

## Availability

- Kubernetes Lease elects one ADS/management leader and supplies the fencing
  epoch. Lease loss revokes mutations and closes ADS streams.
- The leader publishes a digest-verified full snapshot, then ordered deltas;
  followers consume and ACK each revision on one authenticated bidirectional
  gRPC stream and retain a complete in-memory hot snapshot.
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
| `9093` | HTTP | Health, readiness, and metrics only |
| `9094` | gRPC | Bidirectional policy stream, management/recovery, and Gateway replication |

`/health/live`, `/health/ready`, and `/metrics` are unauthenticated and must be
restricted by network policy.

Policy command failures return only stable `error_code`, `retryable`, and safe
message fields correlated by `command_id`. Unary management failures expose the
same information as gRPC status metadata. Detailed infrastructure, replication,
and Envoy errors remain only in the Gateway log.

Policy stream health is exported through the
`joysafeter_agent_gateway_policy_stream_*` metric family, including active and
total connections, commands in flight, and bounded-queue saturation. Policy and
xDS delivery result/latency metrics remain the source for command outcomes.

## Required configuration

| Variable | Purpose |
|---|---|
| `JOYSAFETER_XDS_AUTH_KEYRING` | JSON key-id to ADS token map |
| `JOYSAFETER_XDS_AUTH_WRITE_KEY_ID` | Active ADS key id |
| `JOYSAFETER_AGENT_GATEWAY_MANAGEMENT_TOKEN` | Bearer token for the policy stream and management requests |
| `JOYSAFETER_AGENT_GATEWAY_REPLICATION_TOKEN` | Replica protocol Bearer token when HA is enabled |
| `JOYSAFETER_AGENT_GATEWAY_REPLICATION_ENDPOINT` | Leader-only Gateway bidirectional gRPC endpoint |
| `JOYSAFETER_AGENT_GATEWAY_HOT_STANDBY_MIN_ACKS` | Required follower ACK quorum; default `1` |
| `JOYSAFETER_AGENT_GATEWAY_REPLICATION_ACK_TIMEOUT_MS` | Follower ACK timeout; default `1000` |
| `JOYSAFETER_AGENT_GATEWAY_POLICY_STREAM_MAX_OUTSTANDING` | Global admitted policy commands; default `512` |
| `JOYSAFETER_AGENT_GATEWAY_POLICY_STREAM_MAX_CONCURRENCY` | Concurrent policy executions across independent sandbox lanes; default `256` |
| `JOYSAFETER_AGENT_GATEWAY_POLICY_LANE_QUEUE_CAPACITY` | Per-sandbox ordered lane queue; default `128` |
| `JOYSAFETER_AGENT_GATEWAY_MAX_POLICY_STREAMS` | Concurrent authenticated Orchestrator streams; default `64` |
| `JOYSAFETER_AGENT_GATEWAY_MAX_REPLICATION_STREAMS` | Concurrent unique follower streams; default `32` |
| `JOYSAFETER_AGENT_GATEWAY_REPLICATION_RECONNECT_BASE_DELAY_MS` | Initial follower reconnect delay; default `100` |
| `JOYSAFETER_AGENT_GATEWAY_REPLICATION_RECONNECT_MAX_DELAY_MS` | Maximum follower reconnect delay; default `5000` |
| `JOYSAFETER_AGENT_GATEWAY_REPLICATION_KEEPALIVE_INTERVAL_SECS` | Follower HTTP/2 keepalive interval; default `10` |
| `JOYSAFETER_AGENT_GATEWAY_REPLICATION_KEEPALIVE_TIMEOUT_SECS` | Follower HTTP/2 keepalive timeout; default `5` |
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

The current gRPC transport is plaintext and relies on the management and
replication Bearer tokens plus Kubernetes NetworkPolicy. Add strict mesh mTLS
before exposing port `9094` outside the trusted cluster network. Policy-stream
Proto changes are intentionally not backward compatible, so deploy them with a
blue/green cutover or a maintenance window rather than a mixed-version rolling
upgrade. Pin production images by digest.

## Verification

```bash
cargo fmt --manifest-path backend/app/joysafeter_agent_gateway/Cargo.toml --all -- --check
cargo clippy --all-targets --manifest-path backend/app/joysafeter_agent_gateway/Cargo.toml -- -D warnings
cargo test --manifest-path backend/app/joysafeter_agent_gateway/Cargo.toml
```
