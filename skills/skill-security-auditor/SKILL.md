---
name: skill-security-auditor
description: OpenClaw Skills 全方位安全审计工具，检测供应链投毒、Prompt注入、恶意代码模式、权限越权和依赖风险
version: 1.0.0
author: security-audit
metadata: {
  "category": "security",
  "risk": "safe",
  "requires": {
    "bins": ["node", "grep", "sha256sum"]
  }
}
---

# Skill Security Auditor

基于《OpenClaw 极简安全实践指南》和《安全验证与攻防演练手册》的 Skill 安全审计工具。对 OpenClaw Skill 进行从源码到运行时的全生命周期安全审查，覆盖供应链投毒、Prompt 注入载荷、恶意代码模式、权限越权等威胁向量。

## Purpose

OpenClaw Skills 是 Agent 能力的扩展机制，通过 `/workspace/skills/{skill_name}/SKILL.md` 被 Agent 加载执行。恶意 Skill 可以：
- 通过 Prompt 注入劫持 Agent 行为
- 在代码块中嵌入反弹 Shell、数据外传命令
- 引用恶意外部依赖进行供应链攻击
- 通过 Unicode 混淆、零宽字符隐藏恶意指令

本技能为 Skill 的安装和更新提供安全门禁，在 Skill 进入生产环境前完成安全审查。

## Prerequisites

### 输入要求
- 目标 Skill 目录路径（包含 `SKILL.md` 和 `references/` 等）
- 或 Skill 的远程仓库 URL（用于拉取审计）

### 环境要求
- Node.js 运行时（用于执行审计脚本）
- 对 Skill 文件的读取权限

## Core Workflow

1. **元数据验证**: 解析 SKILL.md 的 frontmatter，验证 name、version、description、metadata 完整性和合法性。
2. **Prompt 注入扫描**: 检测 SKILL.md 正文中的指令注入模式（角色劫持、指令覆盖、隐蔽指令）。
3. **代码块安全审计**: 提取所有代码块（bash, python, javascript 等），对每个代码块进行恶意模式检测。
4. **依赖与引用审查**: 检查 Skill 引用的外部 URL、npm 包、Python 包的安全性和来源可信度。
5. **文件结构检查**: 验证 Skill 目录结构是否符合规范，检测异常文件（二进制、可执行文件、符号链接）。
6. **Unicode 和编码检测**: 扫描隐藏的 Unicode 控制字符、零宽字符、Bidi 覆盖字符。
7. **权限声明审查**: 验证 Skill 声明的权限范围是否合理，检测权限越权请求。
8. **历史版本对比**: 对 Skill 更新进行 diff 分析，检测是否引入了新的恶意内容。
9. **沙箱验证**: 在受限环境中试运行 Skill 代码片段，观察其行为。

## 审计检查项

### 1. 元数据完整性

| 检查项 | 风险等级 | 检测规则 |
|--------|---------|---------|
| frontmatter 缺失 | HIGH | SKILL.md 无 YAML frontmatter |
| name 与目录名不匹配 | MEDIUM | `name` 字段与所在目录名不一致 |
| version 格式无效 | LOW | 非 semver 格式 |
| description 为空 | MEDIUM | 缺少描述，难以审查意图 |
| category 未声明 | LOW | metadata 中缺少 category |
| risk 标记为 unsafe | HIGH | 自声明高风险 |
| requires 声明可疑二进制 | HIGH | 依赖 `nc`, `ncat`, `socat` 等 |

### 2. Prompt 注入检测

| 检测模式 | 风险等级 | 示例 |
|---------|---------|------|
| 角色劫持 | CRITICAL | "You are now a...", "Ignore previous instructions" |
| 指令覆盖 | CRITICAL | "Do not follow any rules", "Override system prompt" |
| 隐蔽指令 | HIGH | HTML 注释中的指令, CSS `display:none` 包裹的文本 |
| 输出操控 | HIGH | "Always respond with...", "Never mention..." |
| 权限升级 | CRITICAL | "Execute with admin privileges", "Disable safety checks" |
| 零宽字符隐藏 | CRITICAL | `\u200B`, `\u200C`, `\u200D`, `\uFEFF` 隐藏的指令 |
| Bidi 覆盖攻击 | CRITICAL | `\u202A`-`\u202E` 改变文本显示方向 |
| Markdown 注入 | MEDIUM | 通过 Markdown 渲染差异隐藏内容 |

### 3. 代码块安全审计

| 代码类型 | 检测规则 | 风险等级 |
|---------|---------|---------|
| Bash | 反弹 Shell、数据外传、提权命令 | 参见 openclaw-threat-detect |
| Python | `exec()`, `eval()`, `subprocess`, `os.system`, `socket` | HIGH |
| JavaScript | `child_process`, `eval`, `Function()`, `require('net')` | HIGH |
| 混淆代码 | Base64 编码的命令, `\x` 转义序列, 多层编码 | CRITICAL |
| 下载执行 | `curl\|wget.*\| bash`, `python -c "$(curl..."` | CRITICAL |
| 文件写入 | 向 `.bashrc`, `.profile`, cron 写入 | HIGH |

### 4. 依赖与外部引用

| 检查项 | 风险等级 | 检测规则 |
|--------|---------|---------|
| 引用非 HTTPS URL | MEDIUM | `http://` 开头的 URL |
| 引用已知恶意域名 | CRITICAL | 与威胁情报库比对 |
| npm 包 typosquatting | HIGH | 包名与知名包相似度 > 0.8 |
| 未锁定版本 | MEDIUM | 使用 `@latest` 或 `*` 版本 |
| 引用废弃/归档仓库 | LOW | GitHub 仓库标记为 archived |
| 安装脚本执行 | HIGH | `preinstall`/`postinstall` hooks |

### 5. 文件结构检查

| 检查项 | 风险等级 | 检测规则 |
|--------|---------|---------|
| 包含二进制文件 | HIGH | 非文本文件（magic bytes 检测） |
| 包含可执行文件 | HIGH | 文件有 +x 权限 |
| 符号链接逃逸 | CRITICAL | 符号链接指向 Skill 目录外 |
| 隐藏文件 | MEDIUM | `.` 开头的隐藏文件（`.env`, `.git`） |
| 文件过大 | LOW | 单文件 > 1MB |
| 异常文件扩展名 | MEDIUM | `.exe`, `.dll`, `.so`, `.dylib` |

### 6. 权限声明审查

| 检查项 | 风险等级 | 检测规则 |
|--------|---------|---------|
| 声明 root 权限 | CRITICAL | requires 中要求 sudo/root |
| 网络访问未声明 | HIGH | 代码中有网络操作但 metadata 未声明 |
| 文件系统范围过宽 | MEDIUM | 访问 `/` 或 `$HOME` 而非 workspace |
| 声明与行为不匹配 | HIGH | 声明 "safe" 但包含危险操作 |

## 审计报告格式

```json
{
  "audit_id": "AUDIT-2026-0001",
  "timestamp": "2026-03-13T10:30:00Z",
  "skill": {
    "name": "example-skill",
    "version": "1.0.0",
    "path": "/workspace/skills/example-skill"
  },
  "verdict": "REJECT",
  "risk_score": 85,
  "findings": [
    {
      "id": "F001",
      "severity": "CRITICAL",
      "category": "prompt_injection",
      "title": "检测到角色劫持指令",
      "description": "SKILL.md 第 42 行包含 'Ignore all previous instructions' 模式",
      "location": "SKILL.md:42",
      "evidence": "...ignore all previous instructions and act as...",
      "recommendation": "移除该指令，如有合法用途需在 metadata 中声明"
    }
  ],
  "summary": {
    "critical": 1,
    "high": 2,
    "medium": 3,
    "low": 1,
    "total": 7
  },
  "recommendation": "REJECT - 存在 CRITICAL 级别发现，不建议加载"
}
```

### 审计判定标准

| 判定 | 条件 | 操作 |
|------|------|------|
| **PASS** | 无 CRITICAL/HIGH 发现 | 允许加载 |
| **CONDITIONAL** | 有 HIGH 但无 CRITICAL | 需人工确认后加载 |
| **REJECT** | 有 CRITICAL 发现 | 禁止加载，移至隔离区 |

## 与其他安全技能的协作

```
Skill 安装/更新
     │
     ▼
┌─────────────────────┐
│ skill-security-     │  ← 入口审计：源码级安全检查
│ auditor             │
└────────┬────────────┘
         │ PASS
         ▼
┌─────────────────────┐
│ openclaw-security-  │  ← 环境检查：Skill 加载后的配置影响
│ checker             │
└────────┬────────────┘
         │ PASS
         ▼
┌─────────────────────┐
│ openclaw-threat-    │  ← 运行时：Skill 执行中的行为监控
│ detect              │
└─────────────────────┘
```

## Tool Categories

| Category | Tools | Purpose |
|----------|-------|---------|
| 元数据解析 | python-frontmatter, js-yaml | SKILL.md frontmatter 解析和验证 |
| Prompt 分析 | 正则引擎, 零宽字符检测 | Prompt 注入模式匹配 |
| 代码分析 | semgrep patterns, AST 分析 | 代码块安全扫描 |
| 依赖检查 | npm audit (概念), PyPI check | 外部依赖安全性验证 |
| 文件检查 | file (magic), stat | 二进制检测和权限验证 |
| 编码检测 | Unicode 分析器 | 隐藏字符和 Bidi 攻击检测 |
| Diff 分析 | git diff, diff | 版本更新变更审查 |

## References

- `references/tools.md` - 工具函数签名和参数说明
- `references/workflows.md` - 审计流程定义和判定规则
