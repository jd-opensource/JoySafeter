# JoySafeter 文档

这里仅保留与当前代码直接相关的活文档。代码与自动化测试是最终事实来源。

## 当前文档

- [安装入口](../INSTALL_CN.md) / [Installation](../INSTALL.md)：首次完整安装与日常启动。
- [开发指南](../DEVELOPMENT.md)：宿主机开发、测试与数据库迁移。
- [构建与部署](../deploy/README.md)：镜像构建、发布、拉取和 Compose 运维。
- [架构总览](./ARCHITECTURE_CN.md) / [Architecture](./ARCHITECTURE.md)：服务职责、运行时拓扑、数据流与隔离边界。
- [教程](./tutorials/README.md)：模型、MCP、Skills 与 Agent 使用流程。
- [API 说明](./api/openapi.md)：当前 API、响应结构和任务流程。
- [上线前门禁](./PRODUCTION_READINESS.md)：项目正式发布前必须完成的验证清单。
- [素材清单](./assets/README.md)：仓库内图片与演示素材维护说明。

## 文档原则

- 不在主分支长期保留已完成的实施计划、编码步骤、临时审计报告或代理执行指令。
- 未完成事项进入 Issue；稳定设计写入架构文档；可执行操作写入部署或开发 Runbook。
- 文档不复制脚本参数清单，命令细节以 `--help` 和自动化配置为准。
- 安装只写在 `INSTALL*`，开发只写在 `DEVELOPMENT.md`，构建部署只写在 `deploy/README.md`。
- 修改行为时同步更新对应活文档，避免用“状态追踪文档”二次记录。
