# JoySafeter Egress Controller

`joysafeter-egress-controller` is the dedicated Envoy xDS control plane. It is
not an HTTP proxy and never receives decrypted provider credentials.

The Phase 1 source adapter reads a strict, versioned snapshot bundle from disk
for deterministic shadow-mode validation. The production PostgreSQL adapter is
also implemented: every replica performs startup/full reconciliation and uses
`LISTEN joysafeter_egress_generation` for low-latency wakeups. It consumes only
provider-neutral, ref-only policy rows through an injected compiler; raw xDS is
not a durable database contract.

## Security defaults

- xDS requires mutual TLS by default.
- TLS 1.3 is required by default.
- Node metadata is mandatory and deterministically selects one resource group.
- Invalid candidates are never retried unchanged after a NACK.
- A NACK restores the last-known-good snapshot for the entire node group.
- REST xDS fetch is disabled; Envoy uses streaming ADS.
- Health and metrics endpoints never expose resource bodies.
- Desired generation content is immutable at the PostgreSQL trigger layer.
- Missed notifications are repaired by periodic full reconciliation.

## Required node metadata

Envoy nodes must provide `deployment_id`, `environment`, `region`, `provider`,
`shard_id`, `envoy_version`, and `config_schema_version`. Docker nodes must also
provide `host_id`.

## Development

```bash
JOYSAFETER_EGRESS_XDS_MTLS=false \
JOYSAFETER_EGRESS_CONTROLLER_SOURCE=file \
JOYSAFETER_EGRESS_CONTROLLER_SNAPSHOT_FILE=./config/snapshots.example.json \
go run ./cmd/controller
```

Production must mount a server certificate, private key, and client CA at the
configured TLS paths. Do not disable mTLS outside an isolated local network.

Set `JOYSAFETER_EGRESS_CONTROLLER_DATABASE_URL` to enable durable publication,
ACK/NACK, and Envoy connection-lease recording. The database must already be at
the current Alembic head. Status writes use a bounded asynchronous queue; queue
overflow leaves the generation unapplied rather than blocking or failing open
inside an xDS callback.

Production sets `JOYSAFETER_EGRESS_CONTROLLER_SOURCE=postgres`. In this mode the
controller strictly decodes policy schema v1 and compiles deterministic LDS,
RDS, and CDS resources. Kubernetes groups receive shared credential and forward
proxy listeners; Docker groups receive one private Unix-socket listener per
sandbox. Local shadow mode must opt into `file` explicitly.

Compilation failures are isolated per node group. A malformed generation keeps
that group's last-known-good snapshot and remains unapplied, while unrelated
groups continue reconciling and serving xDS.

On restart, the controller first recompiles and restores the newest durable
`applied` generation for every group as last-known-good. A newer generation
already marked `failed` is not republished, preventing a restart-driven NACK
loop or rollback to an empty snapshot.

The strict policy schema is defined in `internal/policy`. Unknown fields,
secret-bearing fields, IP-literal upstreams, invalid IDNA hosts, unsafe headers,
malformed credential references, and resource-count abuse are rejected before
xDS compilation.
