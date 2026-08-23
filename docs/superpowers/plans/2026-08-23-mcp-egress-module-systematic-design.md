# MCP Egress 模块系统化设计 (P0–P4)

日期: 2026-08-23
状态: 待实现 (设计待批准)
范围: 凭据 + 网络策略 + 域契约 —— 按 CLAUDE.md 需显式批准

## 1. 背景与根因(已实锤)

`e2e-local-mcp`(`http://host.docker.internal:8765/mcp`,`static_bearer`,已绑组)端到端不通。
运行系统实测:

- 凭据绑定正常:`normalized_mcp_server_url = http://host.docker.internal:8765/mcp`,归一化与 agent 端一致,Bearer 可取。
- MCP 服务存活:宿主 `GET :8765/mcp → 405`(streamable 端点对 GET 正常)。
- 上游对 Envoy 可达:容器内 `host.docker.internal → 192.168.5.2`,`ExtraHosts=[host.docker.internal:host-gateway]`。
- 唯一断点:**沙箱按真实 host 发,Envoy 路由只认占位 host**。

### 根因(单点)

同一条凭据型 MCP 链路被两个函数按两套互相矛盾的架构实现:

- `sandbox_resolver.rs::build_mcp_egress`(~1816):Envoy 路由 `match_host = MCP_EGRESS_HOST ("mcp-egress.internal")`、`match_prefix = /mcp/<name>/`、注入 `Authorization: Bearer`。文档(1753-1759)明写「注入沙箱的 `.mcp.json` 应指向 `mcp-egress.internal/mcp/<name>/` 且不带 token」。
- `harness_input_builder.rs::resolve_mcp_group_credentials`(817-828):给沙箱的 `.mcp.json` **保留真实 host**,只做 `https→http` + 清 headers。

沙箱发出 `Host: host.docker.internal:8765` → 命不中 `mcp-egress.internal` vhost → catch-all `*` → `403 Host not in allowlist`。凭据即使正确也必然不通。

对照 git egress 是对的:`harness_input_builder.rs:975` 把 clone URL 改写成 `http://{GIT_EGRESS_HOST}/git/<slug>/`,与占位路由同构。MCP 缺了这一步。

现有测试 `harness_input_resolves_mcp_urls_without_revealing_tokens`(harness_input_builder.rs:2403)只断言「沙箱看到真实 host、不含 token」,从不校验「沙箱 URL 能否命中 Envoy 路由」,故 drift 漏网。

## 2. 目标架构:MCP Egress 规范契约

统一到 **占位式(placeholder)**,与 git egress 同构。核心不变量:

> **INVARIANT-MCP-EGRESS**: 沙箱 `.mcp.json` 中每个 MCP server 的 URL authority,必须等于该 server 对应 Envoy vhost 的 domain;其 path 前缀必须等于该路由的 `match_prefix`。

规范形态(每个凭据/非凭据 MCP 一致):

| 面 | 值 |
|---|---|
| 沙箱 `.mcp.json` url | `http://mcp-egress.internal/mcp/<name>/` |
| 沙箱 `.mcp.json` type | `sse` 或 `http`(保留原 transport) |
| Envoy vhost domain | `mcp-egress.internal` |
| Envoy 路由 match_prefix | `/mcp/<name>/` |
| Envoy 路由 upstream | 真实 host/port/path/tls(仅存于 orchestrator/Envoy 侧) |
| 注入头 | 由凭据 scheme 决定(见 P2);无凭据则不注入 |

优点:沙箱永不持有真实 host、token、CA;https/域名/IP/TLS 全由 Envoy TLS origination 承担;SSE 与 streamable 都只对占位 host 走 http。

## 3. 模块与所有权

| 层 | 文件 | 职责 |
|---|---|---|
| 沙箱面 URL 改写 | `harness_input_builder.rs` | 把所有 MCP url 改写成占位形态;transport/headers 传递 |
| Envoy 路由构建 | `sandbox_resolver.rs::build_mcp_egress` | 为所有 MCP(凭据/非凭据)建占位路由;凭据→注入 |
| 凭据解析 | `credentials/mcp.rs::resolve_mcp_members` | scheme→(header_name, value) 泛化 |
| Envoy 渲染 | `lds_backend.rs` | MCP 路由关闭缓冲(SSE/streamable);catch-all 403 带 host |
| `.mcp.json` 落盘 | `runner.rs::write_mcp_json` | 已支持 sse/http;仅补测 |
| 域契约 | `backend/contracts/credential_domain_contract.json` | 扩 auth_schemes |

## 4. 详细设计

### P0 · 沙箱面 URL 占位化(主修)

`resolve_mcp_group_credentials`(harness_input_builder.rs:817-828)当前只改写命中凭据者且保留真实 host。改为:**对该 agent 的每个 MCP server**(无论是否有凭据)改写为占位形态:

```rust
// 伪代码
for mcp in mcp_servers {
    // 凭据匹配仍用原始 url 归一化(必须在改写前)
    mcp.url = format!("http://{MCP_EGRESS_HOST}/mcp/{}/", mcp.name);
    mcp.headers.clear(); // 认证一律由 Envoy 注入,沙箱不持有
}
```

- 真实 host/port/path/scheme 只由 `build_mcp_egress` 从 DB 原始 url 解析进 Envoy 路由 upstream。
- 覆盖 https/http/域名/IP:占位面永远 http,`upstream_tls` 由原 scheme 决定,Envoy 做 TLS origination。
- 名称一致性:占位 path `/mcp/<name>/` 与 `build_mcp_egress` 的 `match_prefix` 同源(server name),由 P4 契约测试钉死。

失败行为:若 server name 为空或重名 → 构建期错误(不静默)。

### P1 · Transport(sse / http streamable)

- `parse_mcp_servers`(2866)已保留 `server_type`;`write_mcp_json`(913)已 `sse→"sse"`,其余→`"http"`。占位化后 type 不变,仅 url 变。
- 新增:`lds_backend.rs` 的 MCP 路由渲染关闭 response buffering(`per_filter_config` 或 route 级),保证 SSE 长连接与 streamable 分块不被缓冲。
- `.mcp.json` 示例:
  - streamable: `{"type":"http","url":"http://mcp-egress.internal/mcp/<name>/"}`
  - sse: `{"type":"sse","url":"http://mcp-egress.internal/mcp/<name>/"}`

### P2 · 认证多样性(Bearer / API-Key / 自定义头)

现状:`resolve_mcp_members`(mcp.rs:52)硬拒 `auth_scheme != "static_bearer"`;`build_mcp_egress`(1828)硬编码 `authorization: Bearer {token}`。

设计:引入 scheme→注入映射(单一真源),两处共用:

| auth_scheme | 注入头 | 值模板 |
|---|---|---|
| `static_bearer` | `Authorization` | `Bearer {token}` |
| `header_api_key` | 凭据的 `header_name`(默认 `X-Api-Key`) | `{token}` |
| `custom_header` | 凭据的 `header_name` | `{token}`(或 `{prefix}{token}`) |

改动:

1. `credential_domain_contract.json`:`auth_schemes` 增加 `header_api_key`、`custom_header`(保持 `oauth/mcp_oauth` 仍禁用)。
2. `McpCredentialRecord`/`ResolvedMcpCredential`:增加 `header_name: Option<String>`(static_bearer 时为 None → 用 Authorization)。
3. `resolve_mcp_members`:放开 scheme 白名单为上表三者,携带 header_name。
4. `build_mcp_egress`:`inject_headers` 与 `remove_headers` 由 scheme 映射生成,不再硬编码。external egress(1748)已是「按 header_name 注入」模式,抽公共函数复用。

失败行为:未知 scheme → `UnsupportedScheme`(保留),构建期显式报错。

### P3 · 无凭据 MCP(决策:占位路由不注入)

现状:`build_mcp_egress`(1811)对无凭据 server `continue`,静默丢弃 → 不可达。

**决策(取代原 a/b,更优的第三选项)**:为无凭据 MCP **同样建占位路由,但 `inject_headers` 为空**。理由:

- 无认证 MCP 可用(很多本地/内网 MCP 无鉴权);
- 仍走同一 Envoy 边界,真实 host/CA 不进沙箱 —— 兼具 (a) 的安全与 (b) 的灵活;
- 统一逻辑:凭据与否只影响是否注入头,路由一律建。

改动:`build_mcp_egress` 遍历所有 server;命中凭据→按 P2 注入;否则→占位路由 `inject_headers: []`、`remove_headers: [<所有认证头>]`(防沙箱伪造)。skip 分支删除,替换为 `warn!` 记录「无凭据 MCP,按无认证放行」。

(可选后续:环境策略加 `require_mcp_auth` 开关强制拒绝无凭据 MCP;本次不做,留 TODO。)

### P4 · 跨边界契约测试 + 可诊断性

必备契约测试(锁 INVARIANT-MCP-EGRESS):

1. **URL↔路由对齐**:构造 agent(含 https/http/IP/域名各一)+ 凭据,断言:
   - `input.mcp_servers[*].url == http://mcp-egress.internal/mcp/<name>/`
   - `build_mcp_egress` 产出的路由 `match_host == host(input url)`、`match_prefix == /<path of input url>`。
   即「沙箱 URL host == Envoy match_host、path == match_prefix」。
2. **认证矩阵**:static_bearer / header_api_key / custom_header 各断言注入头正确、沙箱不含 token。
3. **transport 矩阵**:sse / http 各断言 `.mcp.json` type 保留、url 占位化。
4. **无凭据**:断言仍建路由、无注入头、有 warn。
5. **回归**:改造既有 `harness_input_resolves_mcp_urls_without_revealing_tokens` 使其断言占位 url(而非真实 host)。

可诊断性:`lds_backend.rs` catch-all 403 body 附被拒 host;`build_mcp_egress` 无凭据分支 `warn!`。

## 5. 契约/数据变更清单

- `credential_domain_contract.json`:`auth_schemes` 扩三项;契约测试 `test_credential_domain_contract.py` 同步。
- 无 DB schema 迁移(`auth_scheme` 为自由文本列;`header_name` 可复用现有 material/json 字段或新增可空列 —— 若新增列则需一次 additive 迁移,待实现时确认最小化方案)。
- 无 `McpServerConfig`(agent.rs)入口类型变更(SSE/type 走 jsonb 直读路径)。

## 6. 回滚与风险

- P0 是纯改写,可用 feature-free 直接回退(git revert 单函数)。
- P3 把「静默拒绝」变「无认证放行」——语义变化,需在 PR 描述标注;如担心内网无鉴权 MCP 被滥用,配 `require_mcp_auth` 开关(后续)。
- P2 动凭据解析+域契约,风险最高;由契约测试与 `test_credential_domain_contract.py` 兜底。
- SSE 缓冲关闭需在真实 SSE MCP 上验证(本地无 SSE 源时用 streamable 验证分块)。

## 7. 实施顺序(TDD,一次性)

1. P4 契约测试(红):先写 URL↔路由对齐 + 认证/transport 矩阵,复现当前 drift 为失败。
2. P0:占位化改写 → 对齐测试转绿。
3. P3:统一建路由(含无凭据)→ 无凭据用例转绿。
4. P2:scheme 映射 + 域契约扩展 → 认证矩阵转绿。
5. P1:Envoy MCP 路由关缓冲 + transport 断言转绿。
6. 全量:`cargo test`(orchestrator)+ 相关 pytest 契约 + `cargo test`(runner write_mcp_json)。
7. 独立对抗验证(verification agent)后再报告完成。

## 8. 验证命令(DEVELOPMENT.md)

- orchestrator: `cd backend/app/joysafeter_orchestrator_rs && JOYSAFETER_TEST_DATABASE_URL=... cargo test kernel::`
- runner: `cd sandbox-runner && cargo test -p joysafeter-runner write_mcp_json`
- 域契约: `cd backend && .venv/bin/python -m pytest tests/test_credential_domain_contract.py -q`
- live 复现(可选):建含 `e2e-local-mcp` 的 native 会话,`docker exec <sandbox> cat <cwd>/.mcp.json` 应为占位 url;Envoy 访问日志应见对 `mcp-egress.internal` 的 200。
