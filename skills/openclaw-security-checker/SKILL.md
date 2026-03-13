---
name: openclaw-security-checker
description: OpenClaw 安全检测工具，基于安全实践指南验证配置和操作安全性
version: 1.0.0
author: security-audit
homepage: https://docs.openclaw.ai/security
metadata: {
  "category": "security",
  "risk": "safe",
  "requires": {
    "bins": ["node"]
  }
}
---

# OpenClaw 安全检测器

基于《OpenClaw 极简安全实践指南》和《安全验证与攻防演练手册》的安全检测工具。

## 快速开始

\`\`\`bash
# 执行完整安全检查
node {baseDir}/scripts/security-check.mjs
\`\`\`

## 检查项目

### 1. 配置安全检查
- API Key 暴露检测
- Gateway 绑定范围检查
- 工具权限配置验证
- 认证模式安全性

### 2. 权限检查
- 文件权限验证
- 核心目录保护检查
- 可执行文件完整性

### 3. 隔离区检查
- _quarantine 目录扫描
- 被隔离技能列表
- 隔离原因分析

### 4. 日志审计
- 最近操作日志检查
- 可疑操作识别
- 红线触发记录

## 输出格式

检测输出包含：
- **安全评分**: A/B/C/D/F
- **严重问题数**: 需要立即处理的问题
- **警告数**: 建议关注的项目
- **详细报告**: JSON 格式的完整报告

## 安全评分标准

- **A (90-100)**: 安全状态良好
- **B (80-89)**: 有少量警告
- **C (70-79)**: 存在中等风险
- **D (60-69)**: 存在较大风险
- **F (0-59)**: 严重安全问题

## 示例输出

\`\`\`
 OpenClaw 安全检测 

C 配置安全检查
  ! Tools profile 设置为 full，权限较宽泛

C 权限检查
  OK 权限正常

 检测总结 
安全评分: A (94/100)
严重问题: 0 | 警告: 1
\`\`\`

## 基于的安全原则

事前：行为层黑名单 + 安全审计
事中：权限收窄 + 哈希基线
事后：每晚自动巡检 + 显性化汇报

## 相关文档

- [OpenClaw 极简安全实践指南](https://docs.openclaw.ai/security/guide)
- [安全验证与攻防演练手册](https://docs.openclaw.ai/security/validation)
