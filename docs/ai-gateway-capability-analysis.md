# AI Gateway 能力分析 & JoySafeter Agent Gateway 借鉴建议

## 执行摘要

**ai-gateway** 是 Envoy 生态的 AI 流量网关,专注于 LLM/GenAI 服务的路由、认证、限流、可观测。**joysafeter-agent-gateway** 是 JoySafeter 沙箱的 egress 策略控制面,通过 xDS 将网络策略下发给 Envoy sidecar。

两者**架构相似**(都是 Envoy control plane),但**场景不同**(ai-gateway 是南北流量入口网关,joysafeter 是东西流量 sidecar 控制面)。以下是可借鉴的 7 个关键能力维度,按优先级排序。

---

## 架构对比

| 维度 | ai-gateway | joysafeter-agent-gateway | 相似度 |
|---|---|---|---|
| **定位** | AI 流量入口网关(南北) | 沙箱 egress 策略控制面(东西) | 不同场景 |
| **控制面** | Envoy Gateway + 自定义 controller | 独立 xDS 服务器 + policy publisher | ✅ 都是 xDS |
| **数据面** | Envoy Gateway 管理的 Envoy proxy | DaemonSet Envoy sidecar | ✅ 都是 Envoy |
| **配置源** | k8s CRD (AIGatewayRoute/AIServiceBackend) | orchestrator gRPC + Redis stream | 不同 |
| **HA 模式** | controller leader election | ✅ 已实现 leader + hot standby | 已有 |
| **语言** | Go | Rust | 不同 |

---

## 可借鉴能力(优先级排序)

### ⭐⭐⭐ Tier 1:高价值、可直接复用的模式

#### 1. **结构化指标体系**(internal/metrics/)

**ai-gateway 做了什么:**
- **OpenTelemetry 标准化指标**:Prometheus + OTLP 双协议导出
- **多维度标签**:`provider`(OpenAI/Anthropic/AWS), `model`, `route`, `backend`, `status_code`
- **LLM 专用指标**:
  - `genai_request_duration_seconds` — 请求延迟直方图
  - `genai_tokens_total{type="prompt|completion"}` — token 使用量(成本监控)
  - `genai_request_active` — 并发数
  - `genai_errors_total{error_type}` — 按错误类型分类

**joysafeter 当前状态:**
- 无结构化指标暴露(没有 `/metrics` endpoint 或只有基础 HTTP 计数)
- 无 xDS 交付延迟、pending delivery、NACK 计数等控制面健康指标
- **问题**:无法量化 H1/C1/L1 修复的效果,生产故障难定位

**借鉴建议:**
```rust
// src/observability/metrics.rs
use prometheus::{HistogramVec, IntCounterVec, IntGaugeVec, Registry};

pub struct GatewayMetrics {
    // xDS delivery 健康度
    xds_delivery_duration: HistogramVec,        // labels: sandbox_id, resource_type, outcome(ack/nack/timeout)
    xds_pending_deliveries: IntGaugeVec,        // labels: resource_type, node_id
    xds_nack_total: IntCounterVec,              // labels: resource_type, error_code

    // 控制面性能
    policy_apply_duration: HistogramVec,        // labels: operation(apply/remove/prune), outcome
    mutation_lane_wait: HistogramVec,           // 验证 lane 不阻塞

    // HA 状态
    leader_status: IntGauge,                    // 1=leader, 0=follower
    lease_renewals_total: IntCounterVec,        // labels: outcome(success/conflict/timeout)
    replication_lag_seconds: HistogramVec,      // follower 与 leader 的投影差异

    // 策略状态
    active_sandboxes: IntGauge,
    tombstone_count: IntGaugeVec,               // 验证 L1 不泄漏
}

// 暴露 Prometheus /metrics
pub async fn metrics_server(registry: Registry) -> Result<()> {
    let app = axum::Router::new()
        .route("/metrics", get(|| async move {
            prometheus::TextEncoder::new().encode_to_string(&registry.gather())
        }));
    // 绑定到 HTTP_PORT (9093)
}
```

**优先级:** ⭐⭐⭐ **立即做** — e2e 测试和生产监控的基础,能直接证明本次 21 项修复的价值。

---

#### 2. **ExtProc 外部处理器模式**(internal/extproc/)

**ai-gateway 做了什么:**
- Envoy 的 **External Processing filter** 回调 gateway 做请求/响应变换
- 动态注入认证头(AWS SigV4、GCP token、Azure API key)
- 请求 body mutation(模型名重写、redaction 脱敏)
- 响应流式处理(SSE streaming chat completion 的 token 计数)

**joysafeter 当前状态:**
- **不适用** — joysafeter 是 egress 策略(listener/cluster xDS),不需要 L7 body 变换
- 但 ExtProc 的**回调架构**可借鉴到**动态策略注入**场景

**借鉴场景(如果未来需要):**
- **动态 egress 路由覆盖**:orchestrator 可能想临时改某个 sandbox 的 egress 路由而不重新下发完整策略 → ExtProc 回调 gateway 查询 override 表
- **L7 审计/脱敏**:sandbox 出站请求带敏感数据 → ExtProc 回调做 redaction 再放行

**优先级:** ⭐ **观望** — 当前场景不需要;未来有 L7 动态策略需求时再评估。

---

#### 3. **OpenTelemetry Tracing 集成**(internal/tracing/)

**ai-gateway 做了什么:**
- **分布式追踪**:入口 HTTPRoute → backend 调用 → Envoy upstream 全链路 trace
- **自动 context 传播**:从 Envoy `x-request-id` / `traceparent` header 提取 trace context
- **Span attributes**:route name, backend, model, token count, error type

**joysafeter 借鉴点:**
- **控制面操作追踪**:`orchestrator.apply_policy` → `gateway.apply_policy` → `xDS.deliver` → `Envoy.ACK` 全链路
- **故障定位**:apply 超时时,trace 直接看到是卡在 lane wait、xDS flush 还是 Envoy ACK
- **与 sandbox 业务 trace 关联**:sandbox 的出站请求 trace 可关联到其策略 apply trace(通过 sandbox_id)

**实现建议:**
```rust
// Cargo.toml
opentelemetry = "0.21"
opentelemetry-otlp = "0.14"
tracing-opentelemetry = "0.22"

// src/main.rs
let tracer = opentelemetry_otlp::new_pipeline()
    .tracing()
    .with_exporter(opentelemetry_otlp::new_exporter().tonic())
    .install_batch(opentelemetry_sdk::runtime::Tokio)?;
let telemetry = tracing_opentelemetry::layer().with_tracer(tracer);
tracing_subscriber::registry().with(telemetry).init();

// 在 apply_policy 入口:
#[tracing::instrument(skip(self), fields(sandbox_id=%req.sandbox_id, generation=%req.generation))]
async fn apply_policy(&self, req: ApplyPolicyRequest) -> Result<(), Status> {
    tracing::info!("apply start");
    let _span_guard = tracing::span!(Level::INFO, "xds_delivery").entered();
    // ... delivery logic
}
```

**优先级:** ⭐⭐ **中期做** — 对生产故障定位有巨大价值,但不阻塞当前功能。建议在第一轮修复验证后(3-6个月)加入。

---

### ⭐⭐ Tier 2:架构借鉴,需适配场景

#### 4. **Controller-Runtime 控制器模式**(internal/controller/)

**ai-gateway 做了什么:**
- **k8s CRD 驱动**:watch `AIGatewayRoute` CRD → reconcile → 生成 Envoy `HTTPRoute` + `ExtensionPolicy`
- **Reconcile 幂等**:状态完全由 k8s 对象定义,controller 无状态
- **Finalizer 清理**:CRD 删除时自动清理关联的 Envoy 配置

**joysafeter 对应物:**
- 当前:`policy_stream_subscriber.rs` 监听 Redis stream,`policy_publisher.rs` 管理内存投影
- CRD 模式不适合 joysafeter(配置源是 orchestrator 的 PostgreSQL,不是 k8s)

**但可借鉴的模式:**
- **Reconciliation loop**:定期对账 orchestrator 的 sandbox live set 与 gateway 的投影 → 修复 drift
- **幂等写**:当前 `apply_policy` 靠 generation fencing,可强化为"目标状态 reconcile"(每次 apply 都先读当前、diff、只推增量)

**实现建议(可选的 reconcile 增强):**
```rust
// src/application/reconciler.rs
pub struct Reconciler {
    orchestrator_client: OrchestratorClient,
    policy_publisher: Arc<PolicyPublisher>,
}

impl Reconciler {
    /// 定期(5min)从 orchestrator 拉 sandbox live set,与 gateway 投影对账
    pub async fn reconcile_loop(&self) {
        loop {
            match self.orchestrator_client.list_live_sandboxes().await {
                Ok(live) => {
                    let projected = self.policy_publisher.list_sandboxes();
                    let to_remove = projected.difference(&live);  // gateway 有但 orchestrator 没有
                    for sbx in to_remove {
                        warn!("drift detected: {sbx} stale in gateway, pruning");
                        self.policy_publisher.remove(sbx).await;
                    }
                }
                Err(e) => warn!("reconcile failed: {e}"),
            }
            sleep(Duration::from_secs(300)).await;
        }
    }
}
```

**优先级:** ⭐⭐ **可选增强** — 当前 policy stream + gRPC 主路径已足够,reconcile 是额外保险。建议在 soak 测试发现 drift 时再加。

---

#### 5. **Backend 认证插件系统**(internal/backendauth/)

**ai-gateway 做了什么:**
- **可插拔后端认证**:AWS SigV4、GCP Service Account Token、Azure Managed Identity、API Key
- **Credential 动态获取**:从 k8s Secret 读取,支持轮转(internal/controller/rotators/)
- **Per-route 认证覆盖**:同一 backend 不同 route 可用不同 credential

**joysafeter 类比:**
- joysafeter 的**出站目标认证**不在 gateway 管(sandbox 自己带 credential),gateway 只管**是否允许访问**
- 但可借鉴的是:**策略参数的动态查询**
  - 当前:`proxy_auth_token` 硬编码在 policy payload
  - 未来:可能从 Vault/k8s Secret 动态查(避免 token 明文存 Redis/PostgreSQL)

**借鉴场景(如果需要):**
```rust
// 当前 apply_policy 收到的 proxy_auth_token 是明文
// 改为:收到 secret reference,gateway 去 Vault 查真实 token,注入 Envoy listener filter
pub struct PolicyRequest {
    pub proxy_auth_token_ref: Option<SecretRef>,  // "vault://secret/sandbox/sbx_xxx/egress-token"
}

impl Gateway {
    async fn resolve_secret(&self, secret_ref: &SecretRef) -> Result<String> {
        self.vault_client.read(secret_ref.path).await
    }
}
```

**优先级:** ⭐ **观望** — 当前不是痛点;如果未来 security review 要求 token 不落盘,再评估。

---

#### 6. **Rate Limiting 翻译器**(internal/ratelimit/)

**ai-gateway 做了什么:**
- 将高级 `QuotaPolicy` CRD(如 "100 req/min per user")翻译成 Envoy Rate Limit Service 的 descriptor
- 支持**多维限流**:per-user、per-route、per-model、global

**joysafeter 对应场景:**
- **沙箱出站限流**:orchestrator 可能想限制某 sandbox 的 egress QPS(防滥用)
- 当前:无限流能力
- 实现路径:
  1. 在 `EgressPolicy` 加 `rate_limit: Option<RateLimit>` 字段
  2. gateway 翻译成 Envoy `local_rate_limit` filter(不需要外部 RLS)
  3. xDS 下发给该 sandbox 的 Envoy

**借鉴代码模式:**
```rust
// src/domain/egress_policy.rs
pub struct EgressPolicy {
    // ... 现有字段
    pub rate_limit: Option<RateLimit>,
}

pub struct RateLimit {
    pub requests_per_second: u32,
    pub burst: u32,
}

// src/xds/render/listener.rs
fn build_listener(policy: &EgressPolicy) -> Listener {
    let mut filters = vec![/* existing */];
    if let Some(rl) = &policy.rate_limit {
        filters.push(build_local_ratelimit_filter(rl));
    }
    // ...
}
```

**优先级:** ⭐⭐ **中期功能** — 不阻塞当前,但对多租户场景有价值。可作为下一个 sprint 特性。

---

### ⭐ Tier 3:可选参考,低优先级

#### 7. **扩展点架构**(internal/extensionserver/)

**ai-gateway 做了什么:**
- 实现 Envoy Gateway 的 **extension hooks**:
  - `PostTranslateModifyHook` — 在 Envoy Gateway 生成 xDS 后,修改 cluster/route
  - `PostRouteModifyHook` — 动态修改 route metadata
- 允许第三方扩展 ai-gateway 行为而不 fork 代码

**joysafeter 借鉴点:**
- joysafeter-agent-gateway 目前是**单体**,所有逻辑内置
- 如果未来有**插件化需求**(如第三方想注入自定义 Envoy filter),可参考这个 hook 架构
- **当前不需要** — joysafeter 的策略逻辑简单且封闭

**优先级:** ⭐ **不做** — 过度设计,当前场景无需插件化。

---

## 实施路线图

### Phase 1:立即做(Q4 2026)
1. ✅ **结构化指标**(Tier 1.1)— 2-3 天
   - 暴露 `/metrics` endpoint(Prometheus 格式)
   - 核心指标:xDS delivery 延迟、pending count、NACK、leader status、lane wait
   - 集成到现有 Prometheus/Grafana

2. ✅ **e2e 测试集成指标断言** — 1 天
   - 修改 `e2e_agent_gateway.sh`,在 failover 前后采样指标,断言:
     - `gateway_leader_status{instance="new-leader"} == 1`
     - `xds_pending_deliveries` 收敛到 0

### Phase 2:中期增强(Q1 2027)
3. **OpenTelemetry Tracing**(Tier 1.3)— 1 周
   - apply/remove/prune 全链路 trace
   - 与 sandbox 业务 trace 关联(通过 `x-joysafeter-sandbox-id` header)

4. **Rate Limiting**(Tier 2.6)— 2 周
   - `EgressPolicy` 支持 per-sandbox QPS 限制
   - Envoy `local_rate_limit` filter 渲染

### Phase 3:可选(按需)
5. **Reconcile Loop**(Tier 2.4)— 3 天
   - 定期从 orchestrator 对账 live sandbox set
6. **动态 Secret**(Tier 2.5)— 1 周
   - `proxy_auth_token` 支持 Vault reference

---

## 不借鉴的理由

| ai-gateway 能力 | 为什么不借鉴 |
|---|---|
| **CRD 控制器** | joysafeter 配置源是 orchestrator PostgreSQL,不是 k8s CRD |
| **ExtProc body mutation** | joysafeter 是 L4 策略(listener/cluster),不需要 L7 body 变换 |
| **多 AI provider 适配** | joysafeter 的 egress 目标是通用 HTTP/TCP,不是 LLM API |
| **Inference pool / endpoint picker** | joysafeter 不管负载均衡(Envoy 自己做),gateway 只管策略下发 |

---

## 总结

**高价值、立即可做:**
- ⭐⭐⭐ **结构化指标**(metrics)— 生产可观测的基础
- ⭐⭐ **Tracing** — 故障定位利器

**中期特性增强:**
- **Rate Limiting** — 多租户隔离
- **Reconcile Loop** — drift 修复保险

**不借鉴:**
- CRD 控制器(配置源不同)
- ExtProc(场景不需要)
- AI provider 适配(领域不同)

**行动项:**
1. **本周**:实现 Prometheus metrics endpoint + 核心指标
2. **下周**:e2e 测试集成指标断言
3. **Q1 2027**:加入 OpenTelemetry tracing
4. **按需**:评估 rate limiting 和 reconcile loop

---

## 附录:ai-gateway 架构图(供参考)

```
┌─────────────────────────────────────────────────────────────┐
│  ai-gateway Architecture (Tier Two Gateway 模式)             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Client → Envoy Gateway (Tier One)                         │
│            ↓ HTTPRoute(host, path)                         │
│            ↓                                                │
│  ┌─────────────────────────────────────────────────┐       │
│  │ AIGatewayRoute Controller (k8s operator)        │       │
│  │  - Watch AIGatewayRoute CRD                     │       │
│  │  - Generate HTTPRoute + ExtensionPolicy          │       │
│  │  - Configure ExtProc callback                   │       │
│  └──────────────┬──────────────────────────────────┘       │
│                 │ xDS                                       │
│                 ↓                                           │
│  ┌─────────────────────────────────────────────────┐       │
│  │ Envoy Proxy (data plane)                        │       │
│  │  - ext_proc filter → call back to extproc       │       │
│  │  - local_rate_limit filter                      │       │
│  │  - dynamic backend routing                      │       │
│  └──────────────┬──────────────────────────────────┘       │
│                 │ ExtProc gRPC                              │
│                 ↓                                           │
│  ┌─────────────────────────────────────────────────┐       │
│  │ ExtProc Server (aigw binary)                    │       │
│  │  - Request header mutation (auth injection)     │       │
│  │  - Body mutation (model rewrite, redaction)     │       │
│  │  - Response streaming (token count)             │       │
│  │  - Metrics export (OTel)                        │       │
│  └─────────────────────────────────────────────────┘       │
│                 │                                           │
│                 ↓ upstream                                  │
│  AI Backends (OpenAI, Anthropic, AWS Bedrock, etc.)        │
└─────────────────────────────────────────────────────────────┘
```

**对比 joysafeter-agent-gateway:**
- ai-gateway 是**入口网关**(南北流量),joysafeter 是 **sidecar 控制面**(东西流量)
- ai-gateway 的 ExtProc 做 L7 变换,joysafeter 只管 L4 策略(listener/cluster)
- ai-gateway 用 k8s CRD,joysafeter 用 gRPC + Redis stream
- **共同点**:都是 Envoy xDS 控制面,都需要 HA、metrics、tracing
