# envoy-types 0.5.1 → 0.7.6 Type-Surface Delta (orchestrator runtime)

- **Date:** 2026-08-04
- **Purpose:** Task 2 deliverable of the tonic-0.14 / envoy-types unification plan. Enumerate every
  `pb::envoy::…` type this crate constructs, diff its generated struct/enum surface between
  `envoy-types 0.5.1` (current runtime) and `=0.7.6` (migration target), classify each delta
  SAFE vs RISK, and derive the single class-wide fix rule Task 6 applies.
- **Method:** field-level diff of the generated sources at
  `~/.cargo/registry/src/*/envoy-types-{0.5.1,0.7.6}/src/generated/*.rs`.

## Headline finding

**The 0.5.1 → 0.7.6 change is a pure *additive-field* bump for every type this crate constructs.**
0.7.6 tracks a newer Envoy API snapshot, so messages gain new optional/scalar/`Vec` fields. Across
the ten families this crate touches there are **zero removed fields, zero retyped fields, and zero
semantic changes** among the messages we construct. The only non-additive delta anywhere in the diff
is a field *reorder* inside `route.v3` rate-limit descriptor actions (`descriptor_key` moved after a
new `default_value`) — and this crate builds no rate-limit config, so it is unreachable.

Consequences:
- **Wire output is unchanged.** A field that did not exist in the 0.5.1 source cannot be set by our
  0.5.1-era code, so after the bump every new field stays at its default (scalar `0`/`""`, `None`,
  empty `Vec`) and is therefore not serialized. The compiled LDS/RDS/CDS protobuf `Any` bytes are
  identical — proven mechanically by the Task 1 oracle (`tests/xds_resource_equivalence.rs`).
- **The only compile impact is `E0063 missing field`** on *exhaustive* struct literals of a family
  that gained a field. Literals that already close with `..Default::default()` are unaffected.

## Class-wide fix rule (what Task 6 applies uniformly)

> For every `E0063 missing field` the 0.7.6 build reports on an envoy-types struct, the fix is to
> append `..Default::default()` to that literal. **Never** set the new field to a non-default value.

Rationale (systematic, not whack-a-mole): because the delta is provably all-additive, the *class* of
the error is known before the compiler emits a single one — "a newer-snapshot message grew an optional
field." Setting a new field would introduce wire bytes that 0.5.1 never emitted and break byte
equivalence; defaulting it reproduces 0.5.1 behavior exactly. This is one justified rule applied to
every site, not N independent guesses. If any error appears that is NOT an additive-field `E0063`
(a rename, a removed field, a changed type), STOP — it falls outside this analysis and must be
root-caused before editing.

## Families this crate constructs (from `grep -rhoE 'envoy_types::pb::…' src`)

Runtime files on 0.5.1 today: `src/sandbox/lds_backend.rs` (largest), `src/kernel/ext_authz.rs`,
`src/grpc/server.rs`, `src/xds_server.rs`, `src/xds/identity.rs`, `src/xds/snapshot.rs`.
`src/xds/compiler.rs` is already on 0.7.6 (via the `envoy_types_v076` alias) and therefore serves as
the in-tree reference for the post-bump shape of cluster/core/listener/route/tls/hcm/ext_authz-filter/
router.

## Per-family delta table

| Family (`pb::envoy::…`) | Change in 0.7.6 | Class | Action |
|---|---|---|---|
| `service::auth::v3` (CheckRequest/Response, OkHttpResponse, DeniedHttpResponse, AuthorizationServer) | **Identical** message surface | SAFE | none (ext_authz decode/encode unchanged) |
| `google::rpc::Status` | **Identical** | SAFE | none |
| `service::discovery::v3` | New `ResourceError` struct; `resource_errors: Vec<ResourceError>` added to `DeltaDiscoveryRequest` + `DeltaDiscoveryResponse` | SAFE (additive `Vec`) | our sites (`lds_backend.rs` @209 response, @1845/test Delta requests) already use `..Default::default()` → no edit; verify no exhaustive literal remains |
| `config::cluster::v3::Cluster` | +`transport_socket_matcher` (optional) | SAFE | `lds_backend.rs` @2175 `Cluster{…}` — ensure `..Default::default()` |
| `config::core::v3` (Address, SocketAddress, gRPC creds, DNS, Http2/3 opts…) | many additive fields; **`Pipe` unchanged `{path,mode}`**, `Node` unchanged shape | SAFE | `Node` @identity.rs:187 uses `..Default::default()`; `Pipe{path,mode}` exhaustive literal stays valid |
| `config::listener::v3` | +`max_sessions_per_event_loop`, `tcp_keepalive`, `fcds_config`, FilterChainMatch additions; **`Filter` unchanged `{name,config_type}`** | SAFE | `Listener`/`FilterChain` literals @2375/2504 already `..Default::default()`; `Filter{name,config_type}` exhaustive stays valid |
| `config::route::v3` (RouteConfiguration, VirtualHost, RouteAction, …) | additive fields; rate-limit descriptor `default_value` add + `descriptor_key` reorder (**not constructed here**) | SAFE | `RouteConfiguration`/`VirtualHost` literals @2466/2608/2663 — ensure `..Default::default()` |
| `config::endpoint::v3` | +`LbEndpointCollection` struct | SAFE | referenced only; no exhaustive-literal risk |
| `extensions::transport_sockets::tls::v3` | +`compliance_policies`, `secrets`, `trust_bundles` | SAFE | TLS context literals — ensure `..Default::default()` |
| `extensions::filters::network::http_connection_manager::v3` | +`stream_flush_timeout`, `forward_proto_config`, tracing fields | SAFE | HCM literal — ensure `..Default::default()` |
| `extensions::filters::network::tcp_proxy::v3` | +`backoff_options`, `proxy_protocol_tlvs`, `upstream_connect_mode`, … | SAFE | TcpProxy literal — ensure `..Default::default()` |
| `extensions::filters::http::ext_authz::v3::ExtAuthz` | +`max_denied_response_body_bytes`, `enforce_response_header_limits`, `retry_policy`, `service_override` | SAFE | ExtAuthz filter literal — ensure `..Default::default()` |
| `extensions::filters::http::router::v3::Router` | +`reject_connect_request_early_data` | SAFE | Router literal — ensure `..Default::default()` |

## tonic-service traits (separate from message shapes)

`AggregatedDiscoveryServiceServer`, `AuthorizationServer` (and the runner `AgentBridgeServer`) are
**tonic-generated** service traits, not envoy message structs. Their surface changes with the tonic
0.12 → 0.14 bump (regenerated in Task 4 for AgentBridge; the envoy-types-provided ADS/auth servers are
recompiled by the 0.7.6 crate against tonic 0.14). That is transport-layer work handled in Task 5, not
a message-field concern; this note covers only the prost message/enum surface.

## Bottom line for execution

The envoy-types portion of the migration is a low-risk, mechanical **"ensure `..Default::default()`"**
pass over the exhaustive struct literals the 0.7.6 build flags, plus the `compiler.rs` `prost14`
simplification. Correctness is not argued from "it compiled" — it is proven by the Task 1 byte oracle
(Task 7 Step 2) and the docker + k3s egress smokes (Task 8).
