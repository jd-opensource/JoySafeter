# Docker Egress Provider Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the Docker Envoy egress data plane onto the same Go `egress-controller` xDS control plane the K8s fleet already uses, so both providers run one control/credential plane — behind a flag, with the legacy path preserved for rollback.

**Architecture:** Add a third `controller` value to `JOYSAFETER_ENVOY_XDS_MODE`. In `controller` mode the orchestrator writes the Docker Envoy bootstrap with its ADS pointed at the Go controller (`egress-controller:18000`) instead of the orchestrator's own in-process xDS, does **not** instantiate the in-process `DeltaXdsServer`, and uses a **listener-free** Docker network preparer so Envoy has exactly one config source (the controller). The Docker `AuthoritativeEnforcer` path already declares desired policy to Postgres and waits for apply (`enforcer.rs:134,157-199`); once Envoy is an ADS client of the controller, `wait_applied` resolves against a real connected node. The Go docker compiler is extended to emit the per-sandbox `grpc.sock` AgentBridge control-channel listener alongside the existing `http.sock` egress listener, keeping the single-ADS-source invariant.

**Tech Stack:** Rust (orchestrator: tonic, bollard, sqlx), Go 1.26.5 (`egress-controller`, go-control-plane v0.14.0, Envoy v3 API), Envoy v1.39.0 (pinned digest), docker-compose, Postgres.

## Global Constraints

- **Effective refactor, no backwards-compat (user directive "有效重构,不用兼容").** Docker egress has exactly ONE real path: through the Go controller. Do NOT preserve `filesystem`/`grpc` xDS-mode coexistence for Docker as a supported/rollback option, and do NOT build flag-off rollback scaffolding. `JOYSAFETER_EGRESS_POLICY_AUTHORITY_ENABLED` is retained as the *whole-feature* switch (K8s uses it too — it is not a Docker compat shim), not as a "default to legacy" gate.
- **`sandbox/lds_backend.rs` (`DeltaXdsServer` + `filesystem`/`grpc` backends) becomes dead code** once Docker's calls converge onto the controller (this plan). Per the user's decision, this plan **converges the callers** (Docker no longer references the in-process xDS) but leaves the **physical deletion** of `lds_backend.rs`'s `DeltaXdsServer`/`Filesystem*`/`Grpc*` and their `grpc/server.rs`/`main.rs`/`docker.rs` registration to a **dedicated cleanup pass** (physical delete must first extract the still-needed `DeniedCidr`/`dynamic_forward_proxy_dns_cache_json`/`exec_in_envoy` helpers that `envoy.rs` depends on). Do not physically delete it in this plan.
- The Rust `group_key()` (`egress/authority.rs:102-120`) and the Go controller `group.FromNode` (`egress-controller/internal/group/group.go:101-121`) must produce byte-identical keys; the golden test `v1:9YMnDnoG41rXIUgdMrKfL8IqwNSJU9j8EZTNkQ1fQv8` (`authority.rs:935-941`) must keep passing. Do not change grouping.
- No real credential may enter the Envoy bootstrap, any xDS resource, container env, or logs. Bootstrap carries only cluster addresses and node metadata.
- Envoy image stays pinned to `v1.39.0@sha256:d59f7f5fa10cff6d5892b6c5e7df5c9297ddfb2c3683e33fbfb82da24de4fa66` — `docker-compose.yml:102`.
- Node metadata for `provider=docker` must include `host_id` (migration requires it: `20260731_000001_egress_control_plane.py:57-65`; authority sets it from `egress_policy_host_id` or hostname: `enforcer.rs:162-171`).
- Rust cluster/listener naming contract shared with Go: the control-channel upstream cluster is named **`orchestrator_grpc`** (static, in bootstrap — `envoy.rs:327`); the Go docker compiler's control listener route must target that exact name.

---

## File Structure

- `backend/app/joysafeter_orchestrator_rs/src/config.rs` — add controller-endpoint config fields; recognize `"controller"` mode.
- `backend/app/joysafeter_orchestrator_rs/src/sandbox/envoy.rs` — bootstrap generation for `controller` mode (ADS → controller; keep static `orchestrator_grpc`).
- `backend/app/joysafeter_orchestrator_rs/src/sandbox/docker.rs` — in `controller` mode, skip in-process `DeltaXdsServer`; supply an `EnvoyManager` that never pushes listeners.
- `backend/app/joysafeter_orchestrator_rs/src/egress/enforcer.rs` — `DockerEnvoyNetworkPreparer` (listener-free), selected in `controller` mode.
- `egress-controller/internal/compiler/config.go` — add `OrchestratorGrpcCluster` config field (control-channel upstream name).
- `egress-controller/internal/compiler/render.go` — a `grpcControlListener` pipe listener + its route.
- `egress-controller/internal/compiler/compiler.go` — `buildDockerResources` emits both listeners + both route configs per sandbox.
- `egress-controller/internal/compiler/compiler_test.go` — assert docker groups now yield 2 listeners/sandbox and a control route with no ext_authz.
- `deploy/docker-compose.yml` — controller `SOURCE=postgres`; add controller endpoint + xds-mode env to the orchestrator/deps.
- `deploy/.env.example`, `backend/env.example` — document `JOYSAFETER_ENVOY_XDS_MODE=controller` and the controller endpoint vars.

Each Rust task ends with `cargo test` in `backend/app/joysafeter_orchestrator_rs`; each Go task with `go test` in `egress-controller`.

---

### Task 1: Controller-endpoint config + `controller` mode recognition (Rust)

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/src/config.rs` (fields near `envoy_xds_mode:102`; parsing near `:284`)
- Test: same file (`#[cfg(test)]` module)

**Interfaces:**
- Produces: `JoySafeterConfig.egress_controller_xds_host: String`, `JoySafeterConfig.egress_controller_xds_port: u16`, read from `JOYSAFETER_EGRESS_CONTROLLER_XDS_HOST` (default `"joysafeter-egress-controller"`) and `JOYSAFETER_EGRESS_CONTROLLER_XDS_PORT` (default `18000`). `envoy_xds_mode` now also accepts `"controller"`.

- [ ] **Step 1: Write the failing test**

Add to the `config.rs` tests module:

```rust
#[test]
fn controller_xds_endpoint_has_defaults() {
    // Ensure the env is clean for a defaults check.
    std::env::remove_var("JOYSAFETER_EGRESS_CONTROLLER_XDS_HOST");
    std::env::remove_var("JOYSAFETER_EGRESS_CONTROLLER_XDS_PORT");
    let config = JoySafeterConfig::from_env();
    assert_eq!(config.egress_controller_xds_host, "joysafeter-egress-controller");
    assert_eq!(config.egress_controller_xds_port, 18000);
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend/app/joysafeter_orchestrator_rs && cargo test controller_xds_endpoint_has_defaults`
Expected: FAIL — `no field egress_controller_xds_host on type JoySafeterConfig`.

- [ ] **Step 3: Add the struct fields**

In the `JoySafeterConfig` struct (next to `pub envoy_xds_mode: String,` at `config.rs:102`):

```rust
    /// Host of the Go egress-controller's xDS server, used when
    /// `envoy_xds_mode == "controller"`. Docker only.
    pub egress_controller_xds_host: String,
    /// Port of the Go egress-controller's xDS server (ADS). Default 18000.
    pub egress_controller_xds_port: u16,
```

- [ ] **Step 4: Populate them from env**

In `from_env` (next to `envoy_xds_mode: env_str(...)` at `config.rs:284`):

```rust
            egress_controller_xds_host: env_str(
                "JOYSAFETER_EGRESS_CONTROLLER_XDS_HOST",
                "joysafeter-egress-controller",
            ),
            egress_controller_xds_port: env_u16("JOYSAFETER_EGRESS_CONTROLLER_XDS_PORT", 18000),
```

If no `env_u16` helper exists, mirror the existing `env_str`/`env_bool` helpers already in this file (search for `fn env_bool`) — add:

```rust
fn env_u16(key: &str, default: u16) -> u16 {
    std::env::var(key).ok().and_then(|v| v.parse().ok()).unwrap_or(default)
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend/app/joysafeter_orchestrator_rs && cargo test controller_xds_endpoint_has_defaults`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/joysafeter_orchestrator_rs/src/config.rs
git commit -m "feat(egress): add egress-controller xDS endpoint config for Docker controller mode"
```

---

### Task 2: Bootstrap generation for `controller` mode (Rust)

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/src/sandbox/envoy.rs` (`EnvoyConfig:32-49`, `write_bootstrap_config:323-459`)
- Test: same file (`#[cfg(test)]` module — add one if absent)

**Interfaces:**
- Consumes: `EnvoyConfig.xds_mode` (now may be `"controller"`), new `EnvoyConfig.controller_xds_host: String`, `EnvoyConfig.controller_xds_port: u16`.
- Produces: in `controller` mode the bootstrap's `ads_config.grpc_services[0].envoy_grpc.cluster_name == "xds_cluster"`, and the static `xds_cluster` endpoint address is the controller host/port; the static `orchestrator_grpc` cluster still points at `grpc_target_host:grpc_target_port` (the control-channel upstream).

- [ ] **Step 1: Write the failing test**

Add to `envoy.rs`:

```rust
#[cfg(test)]
mod bootstrap_tests {
    use super::*;

    fn cfg(mode: &str) -> EnvoyConfig {
        EnvoyConfig {
            envoy_image: "img".into(),
            socket_volume: "vol".into(),
            config_dir: "/envoy-config".into(),
            envoy_network: "net".into(),
            grpc_target_host: "joysafeter-orchestrator".into(),
            grpc_target_port: 9090,
            container_name: "joysafeter-envoy".into(),
            xds_mode: mode.into(),
            controller_xds_host: "joysafeter-egress-controller".into(),
            controller_xds_port: 18000,
            denied_cidrs: vec![],
        }
    }

    #[test]
    fn controller_mode_points_ads_at_controller() {
        let bootstrap = cfg("controller").render_bootstrap_value();
        let clusters = bootstrap["static_resources"]["clusters"].as_array().unwrap();
        // orchestrator_grpc still targets the orchestrator (control channel upstream).
        let orch = clusters.iter().find(|c| c["name"] == "orchestrator_grpc").unwrap();
        let orch_addr = &orch["load_assignment"]["endpoints"][0]["lb_endpoints"][0]
            ["endpoint"]["address"]["socket_address"];
        assert_eq!(orch_addr["address"], "joysafeter-orchestrator");
        assert_eq!(orch_addr["port_value"], 9090);
        // xds_cluster targets the Go controller.
        let xds = clusters.iter().find(|c| c["name"] == "xds_cluster").unwrap();
        let xds_addr = &xds["load_assignment"]["endpoints"][0]["lb_endpoints"][0]
            ["endpoint"]["address"]["socket_address"];
        assert_eq!(xds_addr["address"], "joysafeter-egress-controller");
        assert_eq!(xds_addr["port_value"], 18000);
        // ADS is configured.
        assert_eq!(
            bootstrap["dynamic_resources"]["ads_config"]["grpc_services"][0]["envoy_grpc"]["cluster_name"],
            "xds_cluster"
        );
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend/app/joysafeter_orchestrator_rs && cargo test controller_mode_points_ads_at_controller`
Expected: FAIL — `no field controller_xds_host` and `no method render_bootstrap_value`.

- [ ] **Step 3: Add the config fields and a pure render helper**

Add to `EnvoyConfig` (`envoy.rs:32`):

```rust
    /// Controller xDS host, used when `xds_mode == "controller"`.
    pub controller_xds_host: String,
    /// Controller xDS port, used when `xds_mode == "controller"`.
    pub controller_xds_port: u16,
```

Add mode predicate next to `is_grpc_mode` (`envoy.rs:46`):

```rust
    fn is_controller_mode(&self) -> bool {
        self.xds_mode == "controller"
    }
```

Refactor `write_bootstrap_config` to build the JSON via a pure, testable method. Extract the body that constructs `bootstrap` into:

```rust
    /// Build the bootstrap JSON value for the active mode (pure; no I/O).
    pub fn render_bootstrap_value(config: &EnvoyConfig) -> serde_json::Value {
        // ... existing cluster/dynamic_resources construction, but see Step 4 ...
    }
```

and make `EnvoyConfig` expose it: add `pub fn render_bootstrap_value(&self) -> serde_json::Value` on `EnvoyConfig` that returns the value (move the `dns_cache_config`, `clusters`, `dynamic_resources`, `bootstrap` construction from `write_bootstrap_config:324-452` into it). Then `write_bootstrap_config` becomes:

```rust
    async fn write_bootstrap_config(&self) -> anyhow::Result<()> {
        let bootstrap = self.config.render_bootstrap_value();
        let bootstrap_json = serde_json::to_string_pretty(&bootstrap)?;
        self.write_file_in_envoy("/envoy-config/bootstrap.json", &bootstrap_json)
            .await?;
        info!(xds_mode = %self.config.xds_mode, "Wrote Envoy bootstrap config (JSON)");
        Ok(())
    }
```

- [ ] **Step 4: Handle the `controller` branch in `render_bootstrap_value`**

In the moved builder, the `dynamic_resources`/`clusters` selection becomes three-way. Both `grpc` and `controller` add a static `xds_cluster` and use ADS; they differ only in the `xds_cluster` endpoint address:

```rust
        let dynamic_resources = if self.is_grpc_mode() || self.is_controller_mode() {
            // xds_cluster endpoint: controller mode → the Go controller; grpc mode → the orchestrator.
            let (xds_host, xds_port) = if self.is_controller_mode() {
                (self.controller_xds_host.clone(), self.controller_xds_port)
            } else {
                (self.grpc_target_host.clone(), self.grpc_target_port)
            };
            clusters.push(json!({
                "name": "xds_cluster",
                "connect_timeout": "5s",
                "type": "STRICT_DNS",
                "lb_policy": "ROUND_ROBIN",
                "typed_extension_protocol_options": {
                    "envoy.extensions.upstreams.http.v3.HttpProtocolOptions": {
                        "@type": "type.googleapis.com/envoy.extensions.upstreams.http.v3.HttpProtocolOptions",
                        "explicit_http_config": { "http2_protocol_options": {} }
                    }
                },
                "load_assignment": {
                    "cluster_name": "xds_cluster",
                    "endpoints": [{ "lb_endpoints": [{ "endpoint": { "address": {
                        "socket_address": { "address": xds_host, "port_value": xds_port }
                    }}}]}]
                }
            }));
            json!({
                "cds_config": { "ads": {} },
                "lds_config": { "ads": {} },
                "ads_config": {
                    "api_type": "DELTA_GRPC",
                    "transport_api_version": "V3",
                    "grpc_services": [{ "envoy_grpc": { "cluster_name": "xds_cluster" } }]
                }
            })
        } else {
            // filesystem branch — unchanged (envoy.rs:415-432).
            json!({ /* existing filesystem lds_config/cds_config */ })
        };
```

The static `orchestrator_grpc` cluster (the first entry in `clusters`, `envoy.rs:326-354`) is unchanged and keeps pointing at `grpc_target_host:grpc_target_port` — it is the control-channel upstream the controller-emitted `grpc.sock` listener routes to.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend/app/joysafeter_orchestrator_rs && cargo test controller_mode_points_ads_at_controller`
Expected: PASS. Also run `cargo test --lib sandbox::envoy` to confirm no regression.

- [ ] **Step 6: Commit**

```bash
git add backend/app/joysafeter_orchestrator_rs/src/sandbox/envoy.rs
git commit -m "feat(egress): Docker Envoy bootstrap controller mode points ADS at the Go controller"
```

---

### Task 3: Listener-free Docker network preparer selected in `controller` mode (Rust)

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/src/sandbox/envoy.rs` — expose socket-dir-only helpers.
- Modify: `backend/app/joysafeter_orchestrator_rs/src/sandbox/docker.rs:110-155` — do not build `DeltaXdsServer` in `controller` mode.
- Modify: `backend/app/joysafeter_orchestrator_rs/src/egress/enforcer.rs:133-147` — select a listener-free Docker preparer in `controller` mode.
- Test: `enforcer.rs` tests module.

**Interfaces:**
- Consumes: `JoySafeterConfig.envoy_xds_mode`, `EnvoyManager` (Task 2).
- Produces: `EnvoyManager::ensure_sandbox_socket_dir(&self, Uuid) -> anyhow::Result<()>` and `EnvoyManager::remove_sandbox_socket_dir(&self, Uuid) -> anyhow::Result<()>`; a `DockerEnvoyNetworkPreparer` implementing `EgressEnforcer` that, on `enforce`, only ensures the socket dir + initializes the bootstrap, and never pushes LDS/CDS (the controller owns listeners). In `controller` mode `build_enforcer_with_pool` selects it instead of `EnvoyEnforcer`.

- [ ] **Step 1: Write the failing test**

Add to `enforcer.rs` tests:

```rust
#[test]
fn controller_mode_docker_uses_listener_free_preparer() {
    // In controller mode, the Docker preparer must not be the in-process
    // EnvoyEnforcer (which pushes LDS/CDS). We assert the builder returns a
    // preparer whose type name is the listener-free one.
    let mut config = JoySafeterConfig::from_env();
    config.egress_policy_authority_enabled = false; // isolate preparer selection from authority wrap
    config.envoy_enabled = true;
    config.envoy_xds_mode = "controller".to_string();
    let mgr = test_envoy_manager(&config); // helper below
    let preparer = build_enforcer(&config, "docker", Some(mgr))
        .expect("build_enforcer")
        .expect("preparer present");
    assert_eq!(preparer.kind_label(), "docker-controller");
}
```

Add a `kind_label(&self) -> &'static str` method to the `EgressEnforcer` trait (default `"generic"`), overridden by `EnvoyEnforcer` (`"docker-envoy"`), `DockerEnvoyNetworkPreparer` (`"docker-controller"`), and `K8sEnvoyNetworkPreparer` (`"k8s-envoy"`). Provide `test_envoy_manager(&config)` mirroring how `docker.rs:133-152` constructs `EnvoyManager` (a Docker connection is required; if the test env has no Docker daemon, gate this test with `#[ignore]` and document running it under `deploy.sh local`).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend/app/joysafeter_orchestrator_rs && cargo test controller_mode_docker_uses_listener_free_preparer -- --include-ignored`
Expected: FAIL — `no method kind_label` / `no type DockerEnvoyNetworkPreparer`.

- [ ] **Step 3: Add socket-dir-only helpers to `EnvoyManager`**

In `envoy.rs`, extract the socket-dir creation already inlined in `add_sandbox_with_policy:211-213` and `remove_sandbox:304-306` into reusable methods:

```rust
    /// Create only the per-sandbox socket directory (no listener push). Used by
    /// the controller-mode Docker preparer, where the Go controller owns LDS/CDS.
    pub async fn ensure_sandbox_socket_dir(&self, sandbox_id: Uuid) -> anyhow::Result<()> {
        let socket_dir = format!("/sockets/{sandbox_id}");
        self.exec_in_envoy(&format!("mkdir -p {socket_dir} && chmod 777 {socket_dir}"))
            .await?;
        Ok(())
    }

    /// Remove only the per-sandbox socket directory (no listener removal).
    pub async fn remove_sandbox_socket_dir(&self, sandbox_id: Uuid) -> anyhow::Result<()> {
        let _ = self.exec_in_envoy(&format!("rm -rf /sockets/{sandbox_id}")).await;
        Ok(())
    }
```

- [ ] **Step 4: Add `kind_label` to the trait and the `DockerEnvoyNetworkPreparer`**

In `enforcer.rs`, add to the `EgressEnforcer` trait:

```rust
    /// Stable label identifying the concrete preparer; used in tests/telemetry.
    fn kind_label(&self) -> &'static str { "generic" }
```

Add the listener-free preparer (model on `AuthoritativeEnforcer`'s delegation + `EnvoyManager` init):

```rust
/// Docker network preparer for `controller` xDS mode. Prepares the sandbox
/// (socket dir + one-time Envoy bootstrap) but does NOT push listeners — the Go
/// egress-controller serves them over ADS. Pairs with `AuthoritativeEnforcer`,
/// which declares the desired policy to Postgres and waits for the controller ACK.
struct DockerEnvoyNetworkPreparer {
    envoy: std::sync::Arc<crate::sandbox::envoy::EnvoyManager>,
}

#[async_trait::async_trait]
impl EgressEnforcer for DockerEnvoyNetworkPreparer {
    fn kind_label(&self) -> &'static str { "docker-controller" }

    async fn init(&self) -> anyhow::Result<()> {
        // Writes the controller-mode bootstrap and resets nothing else.
        self.envoy.init().await
    }

    async fn enforce(
        &self,
        sandbox_id: Uuid,
        _sandbox_token: &str,
        _networking: Option<&serde_json::Value>,
        _credentials: SandboxCredentials,
    ) -> anyhow::Result<()> {
        // Controller owns listeners; we only guarantee the socket dir exists so
        // Envoy can bind the pipe once the controller pushes the listener.
        self.envoy.ensure_sandbox_socket_dir(sandbox_id).await
    }

    async fn teardown(&self, sandbox_id: Uuid) -> anyhow::Result<()> {
        self.envoy.remove_sandbox_socket_dir(sandbox_id).await
    }

    async fn recover(&self, _pool: &PgPool) -> anyhow::Result<()> {
        // Listener recovery is the controller's job (Postgres desired-state).
        Ok(())
    }
}
```

Also add `fn kind_label(&self) -> &'static str { "docker-envoy" }` to `EnvoyEnforcer`'s impl and `{ "k8s-envoy" }` to `K8sEnvoyNetworkPreparer`'s impl.

- [ ] **Step 5: Select it in the builder**

In `build_enforcer_with_pool` (`enforcer.rs:133`), change the docker arm to branch on mode:

```rust
    let preparer = match provider_name {
        "docker" | "" => envoy_manager.map(|m| {
            if config.envoy_xds_mode == "controller" {
                std::sync::Arc::new(DockerEnvoyNetworkPreparer { envoy: m })
                    as std::sync::Arc<dyn EgressEnforcer>
            } else {
                std::sync::Arc::new(EnvoyEnforcer::new(
                    m,
                    config.llm_egress_allowed_hosts.clone(),
                )) as std::sync::Arc<dyn EgressEnforcer>
            }
        }),
        "k8s" | "kubernetes" if config.egress_policy_authority_enabled => {
            K8sEnvoyNetworkPreparer::from_config(config)?
                .map(|value| std::sync::Arc::new(value) as std::sync::Arc<dyn EgressEnforcer>)
        }
        "k8s" | "kubernetes" => K8sEnvoyNetworkPreparer::from_config(config)?
            .map(|value| std::sync::Arc::new(value) as std::sync::Arc<dyn EgressEnforcer>),
        _ => None,
    };
```

The existing authority-wrap below (`enforcer.rs:148-199`) is unchanged — it wraps this preparer in `AuthoritativeEnforcer` when the flag is on, giving Docker declare→wait_applied against the controller.

- [ ] **Step 6: Skip the in-process `DeltaXdsServer` in controller mode**

In `docker.rs:112-132`, the `grpc` branch builds a `DeltaXdsServer`. Guard it so `controller` mode uses neither in-process xDS backend nor a registered ADS service. Change `if config.envoy_xds_mode == "grpc"` (`docker.rs:114`) to keep the `grpc` behavior only for `"grpc"`, and for `"controller"` fall through to a no-push backend. Since the controller-mode preparer never calls `lds.upsert`/`cds.upsert`, the simplest correct wiring is to reuse the `Filesystem*` backends (they only touch files, never contacted in controller mode) — i.e. leave the `else` branch as-is for `controller`. Confirm `xds_service` stays `None` for `controller` (it already is unless the `grpc` branch runs). No code change needed beyond confirming the `== "grpc"` guard is exact (it is).

- [ ] **Step 7: Run tests**

Run: `cd backend/app/joysafeter_orchestrator_rs && cargo test -- --include-ignored egress::enforcer`
Expected: PASS (the new test + existing enforcer tests). Then `cargo build` to confirm the whole crate compiles.

- [ ] **Step 8: Commit**

```bash
git add backend/app/joysafeter_orchestrator_rs/src/sandbox/envoy.rs \
        backend/app/joysafeter_orchestrator_rs/src/sandbox/docker.rs \
        backend/app/joysafeter_orchestrator_rs/src/egress/enforcer.rs
git commit -m "feat(egress): listener-free Docker preparer for controller xDS mode"
```

---

### Task 4: Go docker compiler emits the AgentBridge control-channel listener

**Files:**
- Modify: `egress-controller/internal/compiler/config.go` — add `OrchestratorGrpcCluster string` (default `"orchestrator_grpc"`).
- Modify: `egress-controller/internal/compiler/render.go` — `grpcControlListener` + `dockerControlRoutes`.
- Modify: `egress-controller/internal/compiler/compiler.go:152-170` — `buildDockerResources` emits both listeners and both route configs per sandbox.
- Test: `egress-controller/internal/compiler/compiler_test.go`

**Interfaces:**
- Consumes: `c.config.SocketRoot`, new `c.config.OrchestratorGrpcCluster`.
- Produces: per docker sandbox, two listeners — `joysafeter_<id>_http` (pipe `.../http.sock`, existing) and `joysafeter_<id>_grpc` (pipe `.../grpc.sock`, HTTP/2, router-only, routes to `orchestrator_grpc`, **no ext_authz**), plus a route config `joysafeter_control_<id>` for the grpc listener.

- [ ] **Step 1: Write the failing test**

Add to `compiler_test.go` (mirror the existing docker test that asserts one listener):

```go
func TestDockerCompileEmitsControlChannelListener(t *testing.T) {
	c := newTestCompiler(t) // existing helper in this test file
	desired := dockerDesiredGeneration(t) // existing helper producing a docker generation with 1 sandbox
	compiled, err := c.Compile(context.Background(), desired)
	if err != nil {
		t.Fatalf("compile: %v", err)
	}
	names := listenerNames(compiled) // existing helper collecting listener names
	var http, grpc bool
	for _, n := range names {
		if strings.HasSuffix(n, "_http") {
			http = true
		}
		if strings.HasSuffix(n, "_grpc") {
			grpc = true
		}
	}
	if !http || !grpc {
		t.Fatalf("expected both _http and _grpc listeners, got %v", names)
	}
	// The control listener must NOT carry ext_authz (control channel is not egress).
	if listenerHasExtAuthz(compiled, "_grpc") { // add helper: scans HCM http_filters
		t.Fatalf("control-channel listener must not have ext_authz")
	}
}
```

If `newTestCompiler`/`dockerDesiredGeneration`/`listenerNames` don't exist under those names, reuse whatever the existing `TestCompile*` docker test uses (open `compiler_test.go` and match its helpers) and add `listenerHasExtAuthz`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd egress-controller && go test ./internal/compiler -run TestDockerCompileEmitsControlChannelListener`
Expected: FAIL — only the `_http` listener is emitted.

- [ ] **Step 3: Add the config field**

In `config.go`, add to the compiler `Config` struct and its defaults/validation:

```go
	// OrchestratorGrpcCluster is the static bootstrap cluster the Docker
	// control-channel (grpc.sock) listener routes to. Must match the Rust
	// bootstrap's "orchestrator_grpc" cluster name.
	OrchestratorGrpcCluster string
```

Default it to `"orchestrator_grpc"` wherever the config is constructed (search `Config{` in `main.go`/`config.go`); do not fail validation if empty — fall back to the constant.

- [ ] **Step 4: Add the control listener + route in `render.go`**

```go
const controlRoutesPrefix = "joysafeter_control_"

// grpcControlListener is the per-sandbox AgentBridge control channel: an HTTP/2
// pipe listener that forwards to the orchestrator. It is NOT external egress, so
// it carries no ext_authz filter — only the router.
func (c *Compiler) grpcControlListener(sandboxID string) map[string]any {
	name := "joysafeter_" + strings.ReplaceAll(sandboxID, "-", "_") + "_grpc"
	routeName := controlRoutesPrefix + strings.ReplaceAll(sandboxID, "-", "_")
	return c.pipeListener(name, path.Join(c.config.SocketRoot, sandboxID, "grpc.sock"),
		routeName, []any{routerFilter()})
}

func (c *Compiler) dockerControlRoutes(sandboxID string) map[string]any {
	cluster := c.config.OrchestratorGrpcCluster
	if cluster == "" {
		cluster = "orchestrator_grpc"
	}
	routeName := controlRoutesPrefix + strings.ReplaceAll(sandboxID, "-", "_")
	return map[string]any{
		"name": routeName,
		"virtual_hosts": []any{map[string]any{
			"name": "control", "domains": []any{"*"}, "routes": []any{
				map[string]any{
					"name":  "control_grpc",
					"match": map[string]any{"prefix": "/"},
					"route": map[string]any{"cluster": cluster, "timeout": "0s"},
				},
			},
		}},
	}
}
```

`pipeListener` (`render.go:188`) already sets HCM with RDS + CONNECT/websocket upgrades; the router-only filter list makes it a plain forwarder. The control channel is gRPC (HTTP/2) — Envoy autodetects H2 over the pipe via the HCM `codec_type: AUTO` default; the upstream `orchestrator_grpc` static cluster is H2 (set in the Rust bootstrap, `envoy.rs:331-337`).

- [ ] **Step 5: Emit both listeners + routes in `buildDockerResources`**

Modify `compiler.go:152-170`:

```go
func (c *Compiler) buildDockerResources(policies []policy.SandboxPolicy, deniedRanges []map[string]any, groupKey string, generation uint64) ([]cachetypes.Resource, []cachetypes.Resource, error) {
	routeDocuments := make([]map[string]any, 0, len(policies)*2)
	listenerDocuments := make([]map[string]any, 0, len(policies)*2)
	for _, sandboxPolicy := range policies {
		routeName := "joysafeter_routes_" + strings.ReplaceAll(sandboxPolicy.SandboxID, "-", "_")
		routeDocuments = append(routeDocuments, buildDockerRoutes(routeName, sandboxPolicy, groupKey, generation))
		listenerDocuments = append(listenerDocuments, c.pipeListener(
			"joysafeter_"+strings.ReplaceAll(sandboxPolicy.SandboxID, "-", "_")+"_http",
			path.Join(c.config.SocketRoot, sandboxPolicy.SandboxID, "http.sock"), routeName,
			forwardHTTPFilters(c.config.AuthzCluster, deniedRanges),
		))
		// Control channel (AgentBridge) — no ext_authz, routes to the orchestrator.
		routeDocuments = append(routeDocuments, c.dockerControlRoutes(sandboxPolicy.SandboxID))
		listenerDocuments = append(listenerDocuments, c.grpcControlListener(sandboxPolicy.SandboxID))
	}
	routes, err := decodeDocuments(routeDocuments, func() proto.Message { return &routev3.RouteConfiguration{} })
	if err != nil {
		return nil, nil, err
	}
	listeners, err := decodeDocuments(listenerDocuments, func() proto.Message { return &listenerv3.Listener{} })
	return routes, listeners, err
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd egress-controller && go test ./internal/compiler`
Expected: PASS (new test + updated existing docker test). If the existing docker test hard-codes "1 listener", update its expectation to 2 and add the `_grpc` assertion.

- [ ] **Step 7: Verify formatting + full suite**

Run: `cd egress-controller && test -z "$(gofmt -l .)" && go test -race ./...`
Expected: clean gofmt, all tests pass.

- [ ] **Step 8: Commit**

```bash
git add egress-controller/internal/compiler/config.go \
        egress-controller/internal/compiler/render.go \
        egress-controller/internal/compiler/compiler.go \
        egress-controller/internal/compiler/compiler_test.go
git commit -m "feat(egress-controller): emit per-sandbox AgentBridge control listener for docker groups"
```

---

### Task 5: Compose wiring — controller reads Postgres; orchestrator in controller mode

**Files:**
- Modify: `deploy/docker-compose.yml:72-125` (controller service `:80`; orchestrator/backend env)
- Modify: `deploy/.env.example`, `backend/env.example`

**Interfaces:**
- Consumes: Task 1 env vars, Task 2 bootstrap.
- Produces: a compose stack where the controller serves docker generations from Postgres and the orchestrator, when `JOYSAFETER_EGRESS_POLICY_AUTHORITY_ENABLED=true` + `JOYSAFETER_ENVOY_XDS_MODE=controller`, points Envoy's ADS at the controller.

- [ ] **Step 1: Flip the controller to the Postgres source**

In `docker-compose.yml:80`, change:

```yaml
      JOYSAFETER_EGRESS_CONTROLLER_SOURCE: file
```
to:
```yaml
      JOYSAFETER_EGRESS_CONTROLLER_SOURCE: ${JOYSAFETER_EGRESS_CONTROLLER_SOURCE:-file}
```

so the default stays `file` (safe rollback) but the smoke/e2e overlay can set `postgres`. Keep the existing `JOYSAFETER_EGRESS_CONTROLLER_DATABASE_URL` (already present at `:82`).

- [ ] **Step 2: Add controller-mode env to the orchestrator/backend service**

Find the orchestrator/backend service in `docker-compose.yml` (the one setting `JOYSAFETER_ENVOY_*`). Add:

```yaml
      JOYSAFETER_ENVOY_XDS_MODE: ${JOYSAFETER_ENVOY_XDS_MODE:-filesystem}
      JOYSAFETER_EGRESS_CONTROLLER_XDS_HOST: ${JOYSAFETER_EGRESS_CONTROLLER_XDS_HOST:-joysafeter-egress-controller}
      JOYSAFETER_EGRESS_CONTROLLER_XDS_PORT: ${JOYSAFETER_EGRESS_CONTROLLER_XDS_PORT:-18000}
      JOYSAFETER_EGRESS_POLICY_AUTHORITY_ENABLED: ${JOYSAFETER_EGRESS_POLICY_AUTHORITY_ENABLED:-false}
      JOYSAFETER_EGRESS_POLICY_HOST_ID: ${JOYSAFETER_EGRESS_POLICY_HOST_ID:-docker-local}
```

Defaults preserve legacy behavior; the e2e (Plan 2) sets `XDS_MODE=controller`, `AUTHORITY_ENABLED=true`, and `CONTROLLER_SOURCE=postgres`.

- [ ] **Step 3: Ensure the controller shares the sockets volume is NOT required — document why**

The controller only compiles the socket *path* into the listener; Envoy (which mounts `joysafeter-sockets:/sockets`, `docker-compose.yml:120`) creates the actual pipe. Confirm the controller's `SocketRoot` config default equals `/sockets` and matches Envoy's mount. If the controller's default `SocketRoot` differs, set `JOYSAFETER_EGRESS_CONTROLLER_SOCKET_ROOT: /sockets` on the controller service. Verify against `egress-controller/internal/config/config.go` (search `SocketRoot`).

- [ ] **Step 4: Document the env in the examples**

Add to `deploy/.env.example` and `backend/env.example` (near the existing egress block):

```bash
# Docker egress control mode. "filesystem" (default, legacy) | "grpc" (legacy in-process xDS) | "controller" (Go egress-controller over ADS).
JOYSAFETER_ENVOY_XDS_MODE=filesystem
# When XDS_MODE=controller, the orchestrator points Envoy's ADS at the Go controller here.
JOYSAFETER_EGRESS_CONTROLLER_XDS_HOST=joysafeter-egress-controller
JOYSAFETER_EGRESS_CONTROLLER_XDS_PORT=18000
# Docker node identity (required for provider=docker generations).
JOYSAFETER_EGRESS_POLICY_HOST_ID=docker-local
# Controller desired-state source: "file" (example snapshot) | "postgres" (real control plane).
JOYSAFETER_EGRESS_CONTROLLER_SOURCE=file
```

Remove the dead `JOYSAFETER_EGRESS_CONTROLLER_ADDR` line from `deploy/.env.example:119` (the orchestrator never reads it — confirmed no reference in `joysafeter_orchestrator_rs/`).

- [ ] **Step 5: Validate compose parses**

Run: `cd deploy && docker compose config >/dev/null && echo OK`
Expected: `OK` (no YAML/interpolation errors).

- [ ] **Step 6: Commit**

```bash
git add deploy/docker-compose.yml deploy/.env.example backend/env.example
git commit -m "feat(deploy): compose wiring for Docker controller-mode egress (default off)"
```

---

### Task 6: Local end-to-end wiring verification (manual gate before Plan 2)

**Files:** none (verification only). This task's deliverable is a documented, reproducible local proof that Docker egress is controller-driven. It is the handoff point to Plan 2 (which automates it in CI with a mock upstream).

**Interfaces:** consumes the full stack from Tasks 1-5.

- [ ] **Step 1: Bring up the stack in controller mode**

Run:
```bash
cd deploy
JOYSAFETER_ENVOY_XDS_MODE=controller \
JOYSAFETER_EGRESS_POLICY_AUTHORITY_ENABLED=true \
JOYSAFETER_EGRESS_CONTROLLER_SOURCE=postgres \
./deploy.sh local
```
Expected: all containers healthy, including `joysafeter-egress-controller`.

- [ ] **Step 2: Confirm Envoy is an ADS client of the controller (cross-source evidence 1 + 2)**

Run:
```bash
docker exec joysafeter-egress-controller /usr/local/bin/joysafeter-egress-controller healthcheck
# controller metric: at least one Envoy connected
docker exec joysafeter-egress-controller sh -c 'wget -qO- http://127.0.0.1:18080/metrics | grep joysafeter_egress_controller_connected_nodes'
```
Expected: `joysafeter_egress_controller_connected_nodes` ≥ 1 after a sandbox with egress is created — proving the Docker Envoy connected to the controller's ADS.

- [ ] **Step 3: Confirm Envoy applied controller config (evidence 1: config_dump)**

Run:
```bash
docker exec joysafeter-envoy sh -c 'curl -s http://127.0.0.1:9901/config_dump' | \
  grep -E 'joysafeter_[0-9a-f_]+_(http|grpc)'
```
Expected: both `_http` and `_grpc` per-sandbox listeners appear — served by the controller over ADS, not the file path.

- [ ] **Step 4: Confirm Postgres records the applied generation (evidence 2)**

Run:
```bash
docker exec joysafeter-postgres psql -U postgres -d joysafeter -c \
 "select state, acked_acks, required_acks from joysafeter_egress_apply_status order by id desc limit 1;"
```
Expected: `state = applied`, `acked_acks = required_acks`.

- [ ] **Step 5: Confirm the legacy Docker in-process xDS is no longer referenced (dead-code convergence proof)**

Per "有效重构,不用兼容", Docker no longer routes to the in-process xDS. Confirm the callers have converged away from it (physical deletion is a separate cleanup pass):

Run:
```bash
cd backend/app/joysafeter_orchestrator_rs
# The Docker provider must no longer construct DeltaXdsServer / Filesystem*/Grpc* backends.
grep -n 'DeltaXdsServer::new\|FilesystemLds::new\|GrpcLds::new' src/sandbox/docker.rs || echo "NO_INPROCESS_XDS_IN_DOCKER"
# The bootstrap the orchestrator writes for Docker must be ADS (controller), not a filesystem path source.
docker exec joysafeter-envoy sh -c 'grep -q "\"ads\"" /envoy-config/bootstrap.json && ! grep -q path_config_source /envoy-config/bootstrap.json && echo CONTROLLER_ONLY_OK'
```
Expected: `NO_INPROCESS_XDS_IN_DOCKER` and `CONTROLLER_ONLY_OK` — Docker's egress data path is the controller only; the `filesystem`/`grpc`/`DeltaXdsServer` code is now unreferenced dead code awaiting the dedicated cleanup pass.

- [ ] **Step 6: Record the evidence**

Capture the outputs of Steps 2-5 into the PR description as the "Docker provider parity" proof. Do not claim success without these four independent artifacts (controller metric, Envoy config_dump, Postgres apply_status, legacy rollback).

---

## Self-Review

**Spec coverage (workstream B of `2026-08-01-unified-egress-provider-parity-and-e2e-verification.md` §3):**
- "compose controller `SOURCE=file`→`postgres`" → Task 5 Step 1. ✅
- "Docker Envoy bootstrap ADS → `egress-controller:18000` + node metadata" → Task 2 + Task 5 Step 2 (node metadata `host_id` via `JOYSAFETER_EGRESS_POLICY_HOST_ID`; the authority already injects the full 7-field selector, `enforcer.rs:177-186`). ✅
- "per-sandbox socket path alignment" → Task 5 Step 3 (`SocketRoot=/sockets`). ✅
- "flag-gated; legacy retained; `lds_backend.rs` deprecated not deleted" → new `controller` mode is additive; defaults unchanged (Tasks 1,2,5); `lds_backend.rs` untouched (Global Constraints). ✅
- Single-ADS-source invariant / control channel → Task 4 (Go compiler emits `grpc.sock` control listener). ✅
- DoD "Docker egress fully controller-driven; flag-off unchanged" → Task 6 Steps 3-5. ✅

**Placeholder scan:** No "TBD/TODO"; every code step has concrete code or an exact command. Task 3 Step 1 and Task 4 Step 1 reference existing test helpers by name and instruct the implementer to match the current test file's helpers if names differ — this is a real-codebase adaptation instruction, not a placeholder.

**Type consistency:** `controller_xds_host`/`controller_xds_port` used identically in Tasks 1-2; `kind_label` added to the trait (Task 3 Step 4) and asserted in Task 3 Step 1; the cluster name `orchestrator_grpc` is fixed in Global Constraints, emitted by Rust (`envoy.rs:327`), and referenced by the Go `dockerControlRoutes` default (Task 4 Step 4). `ensure_sandbox_socket_dir`/`remove_sandbox_socket_dir` defined in Task 3 Step 3 and consumed in Step 4.

**Known follow-on (Plan 2):** C-1 real-Envoy `func-e` acceptance harness + C-2 Docker compose egress smoke (four-source assertions) automate Task 6 in CI with a mock upstream. Plan 3: C-3 kind K8s smoke, C-4 Rust CI lane, D deploy.sh/CI convergence.
