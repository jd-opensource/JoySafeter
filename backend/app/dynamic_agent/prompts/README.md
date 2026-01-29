# Prompt Management - seclens Agent

本目录包含 seclens Agent 系统的所有提示词。

## 📚 完整文档

详细文档请查看：[`docs/backend/agent/prompts/README.md`](../../../../docs/backend/agent/prompts/README.md)

## 📁 目录结构

```
prompts/
├── base/              # 通用基础 prompts
│   ├── main_agent.md
│   └── sub_agent.md
├── scenes/            # 场景 prompts (可插拔)
│   └── ctf/
├── tools/             # 工具相关 prompts
└── internal/          # 内部使用
    └── scene_classifier.md
```

## 🎯 核心概念

- **基础提示词** (`base/`) - 通用安全领域提示词，100% 静态
- **场景提示词** (`scenes/`) - 按模式追加的特定提示词（CTF、Pentest 等）
- **工具提示词** (`tools/`) - 工具使用说明
- **内部提示词** (`internal/`) - 场景分类器等

## 🔧 提示词组合方式

```
基础提示词 (base/main_agent.md)
  ↓
+ 场景提示词 (scenes/{mode}/)  ← 按模式追加
  ↓
= 最终系统提示词
```

## 📝 相关文档

- [Pentest 模式提示词问题分析](../../../../docs/backend/agent/prompts/PENTEST_MODE_PROMPT_ISSUE.md)
