# Sandbox Plane 生产部署 Checklist

本清单只覆盖 **k3s 沙箱执行面**。公司其他生产环境负责 Frontend、Backend API、Worker、PostgreSQL、Redis、对象存储、统一入口和业务监控。

k3s 集群只部署：

- `joysafeter-orchestrator`
- `joysafeter-egress-envoy`
- sandbox namespace / RBAC / quota / NetworkPolicy / egress PKI

旧独立 xDS 控制器已物理删除。生产控制面仅允许使用 orchestrator 内置 Rust ADS；
回滚通过上一版 Rust orchestrator / Envoy / NetworkPolicy 镜像与 manifests 完成。

不要在生产 k3s 沙箱集群部署 `api`、`worker`、`frontend`、`postgres`、`redis`、`joysafeter-db-init`、`skillspector`。

---

## 阶段 0 — 确认部署边界

- [ ] 公司生产环境已经部署并管理：Frontend、Backend API、Worker、PostgreSQL、Redis。
- [ ] k3s 集群只作为 sandbox execution plane。
- [ ] 生产入口使用 `deploy/k8s/overlays/sandbox-plane/`。
- [ ] `deploy/k8s/base/`、`deploy/k8s/overlays/local/` 只用于本地 smoke，不用于生产（`local` 即全栈 in-cluster 测试形态）。
- [ ] `deploy/k8s/overlays/sandbox-plane/` 是唯一的生产 overlay；不存在其它「全栈生产」overlay。

---

## 阶段 1 — 公司生产环境前置条件

### 1.1 数据与消息服务

- [ ] PostgreSQL 可从 k3s sandbox-plane 的 orchestrator 访问。
- [ ] Redis 可从 k3s sandbox-plane 的 orchestrator 访问。
- [ ] PostgreSQL / Redis 都启用 TLS 或通过公司内网专线/VPN 加密通道访问。
- [ ] 公司防火墙只允许 k3s 节点出口 IP、NAT IP 或 VPN 网段访问 PG/Redis。
- [ ] PostgreSQL 已执行到当前 Alembic head，包含 egress policy / apply-status 表。

### 1.2 公司 Backend API

- [ ] Backend API 使用同一个 PostgreSQL / Redis。
- [ ] Backend API 创建的 task/session/sandbox 状态能被 k3s 内的 `joysafeter-orchestrator` 读取。
- [ ] Backend API 的 `JOYSAFETER_LLM_EGRESS_ALLOWED_HOSTS` 与 k3s sandbox-plane 配置一致。
- [ ] 真实模型/provider 凭证不写入 k3s manifests；仍由公司生产环境的 Secret/Vault/JoySafeter vault 管理。

---

## 阶段 2 — k3s sandbox-plane 配置

### 2.1 Overlay

- [ ] 复制或直接维护 `deploy/k8s/overlays/sandbox-plane/kustomization.yaml`。
- [ ] 替换所有 `CHANGE_ME_*`。
- [ ] 镜像使用不可变 tag 或 digest，禁止 `:latest`。
- [ ] sandbox runtime 镜像 `JOYSAFETER_IMAGE_CLAUDE` / `JOYSAFETER_IMAGE_CODEX` / `JOYSAFETER_IMAGE_NATIVE` / `JOYSAFETER_SANDBOX_IMAGE` 已指向公司 registry。

### 2.2 Secret

基于 `deploy/k8s/overlays/sandbox-plane/secret.env.example` 创建 `joysafeter-secret`：

- [ ] `DATABASE_URL`
- [ ] `REDIS_URL`
- [ ] `POSTGRES_PASSWORD`
- [ ] `SECRET_KEY`
- [ ] `JWT_SECRET_KEY`
- [ ] `JOYSAFETER_VAULT_ENCRYPTION_KEY`

示例：

```bash
kubectl apply -f deploy/k8s/base/00-namespaces.yaml
kubectl -n joysafeter-control create secret generic joysafeter-secret \
  --from-env-file=deploy/k8s/overlays/sandbox-plane/secret.env \
  --dry-run=client -o yaml | kubectl apply -f -
```

### 2.3 Egress PKI

- [ ] 生产用 cert-manager 或公司 PKI 创建 xDS / authz / downstream 三个 trust domain。
- [ ] 验证集群可临时使用 `deploy/k8s/pki/bootstrap-egress-pki.sh`。
- [ ] 不把生产私钥提交到仓库。

---

## 阶段 3 — Render Gate

发布候选镜像先通过 Docker 四来源业务链路：

```bash
ISOLATED=true \
BRING_UP=true \
ORCHESTRATOR_RS_FULL_IMAGE=<candidate-orchestrator-image> \
BACKEND_FULL_IMAGE=<candidate-backend-image> \
JOYSAFETER_SANDBOX_IMAGE=<candidate-runtime-image> \
deploy/egress-compose-smoke.sh
```

- [ ] A：Envoy config/stats 中目标 LDS/RDS/CDS 已 ACK，且无 secret。
- [ ] B：canonical apply state 为 `applied`，逐节点 ACK 等于 required，NACK=0，Rust connection lease 有效。
- [ ] C：平台凭证已注入、sandbox token 已剥离、错误 token 返回 403。
- [ ] D：成功请求的 Envoy `x-request-id` 出现在 mock upstream 日志。

```bash
OVERLAY=deploy/k8s/overlays/sandbox-plane \
SMOKE_IMAGE=<internal-image-with-curl> \
deploy/k8s/validate-sandbox-plane-readiness.sh
```

必须满足：

- [ ] 渲染结果不含 `CHANGE_ME_*`。
- [ ] 渲染结果不含 `local-dev-secret` / 默认数据库密码。
- [ ] 渲染结果不含 `:latest`。
- [ ] 渲染结果不含 `api` / `worker` / `frontend` / `postgres` / `redis` / `joysafeter-db-init` / `skillspector`。
- [ ] 渲染结果包含 orchestrator、egress-envoy、sandbox NetworkPolicy。
- [ ] 渲染结果不含 `joysafeter-egress-controller` Deployment/Service。
- [ ] `JOYSAFETER_EGRESS_POLICY_AUTHORITY_ENABLED=true`。
- [ ] `JOYSAFETER_K8S_EGRESS_MANAGEMENT_ENABLED=true`。
- [ ] NetworkPolicy deny-all smoke 能阻断直连公网。

---

## 阶段 4 — Apply 和运行态验证

```bash
kubectl apply -k deploy/k8s/overlays/sandbox-plane
kubectl -n joysafeter-control rollout status deploy/joysafeter-orchestrator --timeout=300s
kubectl -n joysafeter-egress rollout status deploy/joysafeter-egress-envoy --timeout=300s
```

运行态检查：

```bash
kubectl -n joysafeter-control get deploy,svc
kubectl -n joysafeter-egress get deploy,svc
kubectl -n joysafeter-sandboxes get networkpolicy,resourcequota,limitrange
```

确认：

- [ ] `joysafeter-control` 里没有 `api` / `worker` / `frontend` / `postgres` / `redis` / `skillspector`。
- [ ] `joysafeter-control` 只有 orchestrator 相关服务，不含独立 xDS controller。
- [ ] `joysafeter-egress` 只有 Envoy 相关服务。
- [ ] `joysafeter-sandboxes` 有 default-deny 和 runner allow policy。

---

## 阶段 5 — 跨环境 smoke

公司 Backend API 在 k3s 外部，所以 smoke 必须显式传 `API_URL`：

```bash
API_URL=https://<company-api-host> deploy/k8s/k3s-task-smoke.sh
```

真实 secret-backed egress：

```bash
API_URL=https://<company-api-host> \
ANTHROPIC_API_KEY=... \
ANTHROPIC_BASE_URL=... \
ANTHROPIC_MODEL=... \
deploy/k8s/k3s-egress-smoke.sh
```

必须确认：

- [ ] API 能创建用户/agent/task。
- [ ] 公司 worker/orchestrator 协同后，k3s 创建 sandbox Pod。
- [ ] sandbox Pod env 不含真实模型 key。
- [ ] durable generation 到达 applied，无 NACK。
- [ ] wrong-token 403。
- [ ] sandbox 不能绕过 Envoy 直连上游。
- [ ] 模型任务完成并输出预期 smoke 标记。

---

## No-Go 条件

命中任一项就不要开放生产 sandbox 流量：

- [ ] k3s NetworkPolicy 不生效。
- [ ] k3s 渲染出 API / worker / frontend / PG / Redis / db-init / skillspector。
- [ ] k3s manifests 中出现真实模型/provider secret。
- [ ] sandbox 可直连公网、公司内网、PG、Redis 或 metadata IP。
- [ ] Rust xDS 指标出现 NACK，或 canonical generation state 为 `failed`。
- [ ] 隔离 Docker A/B/C/D smoke 任一来源未通过。
- [ ] 完整 secret-backed smoke 未通过。

---

## 回滚边界

- [ ] 常规回滚只回滚 orchestrator / Envoy / NetworkPolicy 相关 manifests。
- [ ] Rust ADS 无法恢复时，回滚到上一版已验证的 Rust orchestrator 与配套 Envoy manifests。
- [ ] 不在 k3s 回滚公司 Backend API、Frontend、Worker、PG、Redis。
- [ ] 不手工把 `failed` / `superseded` generation 改回 `published` / `applied`；创建新 generation 或回滚发版。
