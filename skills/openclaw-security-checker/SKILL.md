---
name: openclaw-security-checker
description: OpenClaw 安全检测工具，基于安全实践指南验证配置安全、权限隔离、网络策略、日志审计和运行时完整性
version: 1.0.0
author: security-audit
homepage: https://docs.openclaw.ai/security
metadata: {
  "category": "security",
  "risk": "safe",
  "requires": {
    "bins": ["node", "jq", "grep", "openssl"]
  }
}
---

# OpenClaw 安全检测器

基于《OpenClaw 极简安全实践指南》和《安全验证与攻防演练手册》的全面安全检测工具。对 OpenClaw 实例的配置、权限、隔离、网络、日志进行系统化审查，输出可量化的安全评分和修复建议。

## Purpose

OpenClaw 实例运行在 Docker 容器中，每用户独占一个容器（JoySafeter 架构）。该技能负责对实例的安全面进行系统化检测，覆盖部署前配置审查、运行时权限验证、隔离区合规检查三个阶段。

## Prerequisites

### 环境要求
- OpenClaw 实例已部署并可访问（本地或容器内）
- 对 `~/.openclaw/` 目录有读取权限
- `openclaw.json` 配置文件可读

### 目标实例信息
- OpenClaw 版本号（`openclaw --version`）
- 部署模式：local / docker / kubernetes
- Gateway 端口和绑定范围

## Core Workflow

1. **配置文件扫描**: 解析 `openclaw.json`，检查 gateway 认证、绑定范围、工具权限、模型配置中的安全隐患。
2. **凭证暴露检测**: 扫描配置文件、环境变量、日志中是否存在明文 API Key、Token、密码。
3. **Gateway 安全审计**: 验证 gateway 绑定地址、认证方式、CORS 白名单、trusted proxies 配置。
4. **工具权限验证**: 检查 `tools.profile` 设置，验证文件系统访问范围、命令执行权限、网络访问策略。
5. **文件权限检查**: 验证 `~/.openclaw/` 目录及关键文件的权限位，确保配置文件不可被其他用户读取。
6. **隔离区合规检查**: 扫描 `_quarantine` 目录，列出被隔离的技能及原因，验证隔离机制是否正常运作。
7. **运行时完整性验证**: 通过 SHA-256 哈希校验核心文件完整性，对比安装时的基线值。
8. **日志审计分析**: 检查最近操作日志中的可疑模式（大量失败请求、敏感操作、红线触发记录）。
9. **网络策略检查**: 验证出站网络请求白名单、DNS 解析范围、容器网络隔离状态。

## 检查项目详情

### 1. 配置安全检查

| 检查项 | 风险等级 | 检测规则 | 扣分 |
|--------|---------|---------|------|
| API Key 明文暴露 | CRITICAL | 正则匹配 `sk-*`, `key-*`, `token:` 等模式 | -20 |
| Gateway 绑定 0.0.0.0 | HIGH | 检查 `gateway.bind` 是否为 `0.0.0.0` 或 `lan` | -10 |
| 工具权限设为 full | MEDIUM | `tools.profile === "full"` | -5 |
| CORS 白名单过宽 | MEDIUM | `allowedOrigins` 包含 `*` | -5 |
| 认证 Token 弱强度 | HIGH | Token 长度 < 32 或 entropy < 4.0 | -10 |
| 禁用设备认证 | HIGH | `dangerouslyDisableDeviceAuth: true` | -10 |
| 模型 context 过大 | LOW | `contextWindow > 200000` | -2 |
| 未配置 TLS | MEDIUM | Gateway 未启用 HTTPS | -5 |
| 自动更新已禁用 | LOW | `update.checkOnStart: false` | -3 |

### 2. 权限与隔离检查

| 检查项 | 风险等级 | 检测规则 | 扣分 |
|--------|---------|---------|------|
| 配置文件权限过宽 | HIGH | `openclaw.json` 权限非 600/640 | -10 |
| 工作区目录权限 | MEDIUM | `/workspace/` 权限非 700/750 | -5 |
| 以 root 运行 | CRITICAL | 当前进程 UID == 0 | -20 |
| 文件系统未限制 | HIGH | `tools.fs.workspaceOnly: false` | -10 |
| 隔离区异常 | MEDIUM | `_quarantine` 中存在未审查的技能 | -5 |

### 3. 网络安全检查

| 检查项 | 风险等级 | 检测规则 | 扣分 |
|--------|---------|---------|------|
| trusted proxies 过宽 | MEDIUM | 包含 `/8` 大段网络 | -5 |
| 出站无白名单 | HIGH | 未配置出站网络限制 | -10 |
| Gateway 暴露在公网 | CRITICAL | 端口可从容器外访问 | -15 |

### 4. 日志审计检查

| 检查项 | 风险等级 | 检测规则 | 扣分 |
|--------|---------|---------|------|
| 敏感操作无日志 | HIGH | 关键操作缺少审计记录 | -10 |
| 可疑操作模式 | MEDIUM | 短时间内大量异常请求 | -5 |
| 红线触发记录 | CRITICAL | 检测到已触发的安全红线 | -15 |
| 日志文件可写 | MEDIUM | 日志文件权限允许修改 | -5 |

## 安全评分体系

### 评分公式

基础分 100 分，每项检查根据风险等级扣分：

```
最终分 = max(0, 100 - Σ 扣分)
```

### 安全等级

| 等级 | 分数范围 | 含义 | 建议操作 |
|------|---------|------|---------|
| **A** | 90-100 | 安全状态良好 | 保持现有配置，定期复检 |
| **B** | 80-89 | 有少量警告 | 建议在下次维护窗口修复 |
| **C** | 70-79 | 存在中等风险 | 应在一周内修复 |
| **D** | 60-69 | 存在较大风险 | 需要立即关注并修复 |
| **F** | 0-59 | 严重安全问题 | 必须立即停止服务并修复 |

## 示例输出

```
╔══════════════════════════════════════╗
║      OpenClaw 安全检测报告          ║
╠══════════════════════════════════════╣
║ 实例: openclaw-a1b2c3d4             ║
║ 版本: 2026.3.11                     ║
║ 部署: Docker 容器                   ║
║ 检测时间: 2026-03-13 10:30:00 UTC   ║
╚══════════════════════════════════════╝

▶ 配置安全检查
  ✗ [HIGH] Gateway 绑定范围为 lan，建议收窄为 localhost
  ✗ [MEDIUM] tools.profile 设置为 full，建议使用 restricted
  ✗ [HIGH] dangerouslyDisableDeviceAuth 已启用
  ✓ API Key 未暴露
  ✓ 认证 Token 强度合格

▶ 权限与隔离检查
  ✓ 以 node 用户运行 (非 root)
  ✓ 配置文件权限正常 (600)
  ✗ [MEDIUM] /workspace/skills 目录权限为 755，建议 750

▶ 网络安全检查
  ✗ [MEDIUM] trusted proxies 包含 10.0.0.0/8 大段
  ✓ Gateway 仅容器内可达

▶ 日志审计检查
  ✓ 最近 24h 无可疑操作
  ✓ 无红线触发记录

╔══════════════════════════════════════╗
║ 安全评分: B (82/100)                ║
║ 严重问题: 0 | 高危: 2 | 警告: 3    ║
╠══════════════════════════════════════╣
║ 修复建议:                           ║
║ 1. 将 gateway.bind 改为 localhost   ║
║ 2. 启用设备认证                      ║
║ 3. 将 tools.profile 改为 restricted ║
╚══════════════════════════════════════╝
```

## Tool Categories

| Category | Tools | Purpose |
|----------|-------|---------|
| 配置解析 | jq, node (JSON parser) | 解析 openclaw.json 配置文件 |
| 凭证扫描 | grep, TruffleHog patterns | 检测明文密钥和 Token |
| 权限检查 | stat, ls, id | 验证文件权限和运行用户 |
| 完整性校验 | sha256sum, openssl dgst | 核心文件哈希验证 |
| 网络检测 | ss, netstat, iptables | 端口绑定和网络策略检查 |
| 日志分析 | grep, jq, awk | 审计日志模式匹配 |

## 安全原则

- **事前**: 行为层黑名单 + 安全审计 + 配置基线
- **事中**: 权限收窄 + 哈希基线 + 运行时监控
- **事后**: 每晚自动巡检 + 显性化汇报 + 修复追踪

## References

- `references/tools.md` - 工具函数签名和参数说明
- `references/workflows.md` - 检测流程定义和判定规则
