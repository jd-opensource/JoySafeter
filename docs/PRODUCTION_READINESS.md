# JoySafeter 上线前门禁

> 当前状态：项目尚未正式上线。本文只维护可验证的发布条件，不记录历史实现过程。

所有门禁必须有负责人、验证日期和可复现证据。未满足的项目不得以“后续补充”替代发布判断。

## 0. 当前阻断状态（2026-08-05）

已完成的代码级门禁：

- [x] 密码由服务端使用随机盐 bcrypt 慢哈希；旧 SHA-256 开发数据仅允许用原始密码登录后自动升级，不再接受哈希重放。
- [x] 注册、重置和改密统一执行服务端密码强度校验；当前用户改密必须验证旧密码并撤销刷新会话。
- [x] 邮箱验证与密码重置令牌只存摘要，不在数据库保存可直接使用的明文令牌。
- [x] 部署预检自动生成并同步 JWT、Vault、全新 PostgreSQL 密钥；非法密钥、已有数据卷默认密码和缺失 Sandbox runtime 镜像均 fail-closed。
- [x] PostgreSQL 与 Redis 的 Compose 端口默认只绑定 `127.0.0.1`。
- [x] `sandbox-runner` 全 workspace 测试恢复通过，并消除测试构造器字段漂移与全局环境变量并发污染。
- [x] CI 已覆盖两个 Rust workspace 的 fmt、Clippy 和全量测试（sandbox 严格零告警，orchestrator 先报告历史告警），release tag 必须先通过可复用 CI。
- [x] Claude Code 与 Codex runtime 使用固定 CLI 版本、镜像内编译 runner，并进入 amd64/arm64 正式构建发布矩阵。
- [x] Native runtime 已明确为可选本地能力：缺失私有 tgz 时提前失败，且不进入默认池、`--all` 或正式发布矩阵。

仍然阻断正式发布：

- [ ] 发布镜像尚无阻断式漏洞扫描、SBOM、provenance、签名与 attestations。
- [ ] 备份恢复、指标告警、数据保留和真实回滚演练尚无可复现证据。

本轮验证证据：backend `863 passed`，frontend `206 passed`，orchestrator `149 passed`，sandbox-runner 在 macOS 与 Linux arm64 均 `51 passed`；Linux 严格 Clippy、pre-commit、TypeScript、Ruff、Prettier、Next.js production build、Compose 配置和部署脚本语法均通过；Claude Code `2.1.215` 与 Codex `0.146.0` arm64 runtime 镜像已完成真实构建和版本检查。

## 1. 发布与回滚

- [ ] backend、frontend、orchestrator-rs、SkillSpector 和 Agent runtime 使用不可变版本 tag。
- [ ] 每个镜像可追溯到 Git SHA、构建流水线和依赖锁文件。
- [ ] 在目标 CPU 架构上完成镜像拉取、迁移、启动和 Agent 任务冒烟测试。
- [ ] 已验证上一稳定版本的回滚流程，包含数据库兼容性判断。
- [ ] 发布、回滚和紧急停机命令已写入值班 Runbook。

## 2. 数据安全

- [ ] PostgreSQL 使用持久化或托管高可用方案，不依赖临时容器数据。
- [ ] 已完成自动备份，并从真实备份执行过恢复演练。
- [ ] Alembic 升级在生产副本数据上验证，耗时和锁影响可接受。
- [ ] Redis 数据丢失、重启和主从切换的行为已验证。
- [ ] 日志、事件和用户数据的保留期与清理策略已确定。

## 3. 密钥与网络

- [ ] `VAULT_ENCRYPTION_KEY`、数据库密码、模型密钥和第三方凭据不进入 Git 或镜像层。
- [ ] 所有默认密码和示例凭据已替换。
- [ ] frontend 与 API 仅通过 HTTPS 暴露。
- [ ] PostgreSQL、Redis、Docker socket 和 orchestrator gRPC 不暴露公网。
- [ ] Sandbox 出站策略按最小权限验证，凭据注入不会进入日志或非目标域名。
- [ ] 依赖镜像和第三方组件完成漏洞扫描与许可证复核。

## 4. 可靠性

- [ ] API、worker、orchestrator-rs、SkillSpector、PostgreSQL 和 Redis 的重启恢复已验证。
- [ ] 任务超时、取消、重试、重复请求和进程中断场景已验证。
- [ ] 单实例故障不会造成无法识别的永久运行任务或孤儿 Sandbox。
- [ ] 数据库、Redis、模型提供方和 SkillSpector 不可用时，系统行为符合预期。
- [ ] 容量上限、并发限制、队列积压和降级策略已确定。

## 5. 可观测性

- [ ] 关键服务具备健康检查、结构化日志、指标和告警。
- [ ] 能按组织、项目、会话、任务和 Sandbox 关联一次完整请求链路。
- [ ] 告警覆盖错误率、延迟、任务积压、重试、死信、数据库连接和磁盘容量。
- [ ] 日志已脱敏，且不会记录密钥、Authorization header 或完整用户凭据。
- [ ] 值班人员可以仅凭 Runbook 定位并恢复常见故障。

## 6. 性能与容量

- [ ] 使用接近生产的数据量完成 API、任务执行和事件流压测。
- [ ] 明确单实例安全容量和水平扩容触发条件。
- [ ] SkillSpector 与 Agent runtime 的 CPU、内存、磁盘限制已验证。
- [ ] 长任务、大事件流和高并发下不存在无界内存或磁盘增长。

## 7. 发布证据

建议每次候选发布保留以下最小证据：

```text
版本 / Git SHA:
镜像清单:
目标架构:
数据库迁移结果:
备份恢复演练:
部署冒烟结果:
安全扫描结果:
压测结果:
回滚演练:
发布负责人:
批准时间:
```

本地部署与镜像命令见 [`../deploy/README.md`](../deploy/README.md)，运行时边界见 [`ARCHITECTURE_CN.md`](./ARCHITECTURE_CN.md)，高可用约束见 [`../deploy/HA.md`](../deploy/HA.md)。
