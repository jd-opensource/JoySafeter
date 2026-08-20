# 教程 03：Skills（技能包）的导入、安全扫描、投递与沙箱消费

> **适合人群**：希望让 Agent 拥有执行本地 Python/Shell 脚本能力的高阶用户，或为团队维护通用能力库的开发者。
> **目标**：理解 Skills 的完整生命周期（存储 → 安全扫描 → 打包投递 → 沙箱消费），并掌握合规导入与验证。

---

## 0. Skills 与 MCP 的区别

- **MCP 工具**：远端 HTTP/RPC 接口，代码跑在远端（见[教程 02](./02-mcp-service-setup.md)）。
- **JoySafeter Skills**：一组**真实的物理文件**（一个 `SKILL.md` 描述文件 + 若干 `.py` / `.sh` / `.json`）。
  平台需要在系统底层**安全地打包并投递这些文件**进沙箱，Agent 才能读取 / 执行。

---

## 1. 核心管线（Under the Hood）

技能管线横跨三层，并包含独立的安全扫描服务：

### 1.1 校验与存储（`joysafeter_shared/skill/` + `SkillService`）
上传 ZIP / 导入目录时：
- **解析 SKILL.md**：提取 YAML frontmatter（`name` / `description` / `allowed-tools` / `compatibility`…），
  以文件内声明为**唯一真相来源**。
- **防爆与清洗**：拦截系统文件（`.DS_Store` 等）与二进制 / 非 UTF-8 内容；enforce 尺寸上限
  （压缩包 / 文件数 / 单文件 / 解压总量）。
- 通过后，技能落库 PostgreSQL（`joysafeter_skills` + `joysafeter_skill_files`），尚未触及任何执行环境。

### 1.2 安全扫描（skillspector + 可选发布闸门）
- 写入 / 更新时，`SkillSecurityService` 把技能内容发给独立的 **skillspector** 服务扫描
  （`SKILL_SECURITY_*` 环境变量控制）。
- 扫描器故障会记录 `failed` / `scanning` 状态；草稿写入始终可继续保存。
- 默认 `SKILL_SECURITY_SCAN_ENFORCEMENT_ENABLED=false`，扫描结果只用于风险提示。
- 切为 `true` 后，发布版本会对实际快照执行一次新的 fail-closed 扫描；扫描失败或阻断则发布失败。
- 已发布版本不会因后续扫描、草稿修改或父 Skill 状态变化而失效。

### 1.3 生命周期与已发布版本
- 技能有生命周期 FSM：`draft → pending_review → {approved, rejected}`，`approved → archived`。
- 发布动作要求当前 Skill 已 `approved`。同项目 Agent 可关联任意明确已发布版本，`latest` 指最高 SemVer；
  同组织跨项目只能关联 organization/public 指针版本，跨组织只能关联 public 指针版本。
- 任务启动时 Rust orchestrator 只解析并打包已发布版本；父 Skill 后续扫描和生命周期不参与运行判断。

### 1.4 打包投递（Rust orchestrator → gRPC → 沙箱 runner）
- 任务启动时，Rust `HarnessInputBuilder` 按项目/组织层级解析 Agent 引用；跨项目不会越过已批准的
  organization/public 版本指针。解析完成后从
  `joysafeter_skill_version_files` 读取文件并现场打包为 `tar.gz`（proto `SkillArchive`），同时记录用量日志。
- orchestrator 经 gRPC `SetupSandbox` / `StartTask` 把 `SkillArchive` 下发给沙箱内的 Rust runner。
- runner 的 `unpack_skills` 把每个归档解压到沙箱工作目录下的技能目录（按引擎/`target` 决定具体子路径）。
- **至此，数据库里的技能记录变成了沙箱内一份份真实文件。** 沙箱是隔离的，脚本再高危也困在沙箱内。

---

## 2. 端到端验证闭环

### 2.1 准备一个合规的技能包

`my_test_skill/SKILL.md`（YAML 头部是灵魂）：
```markdown
---
name: verify-disk-writer
description: 验证系统能否把内容安全写入沙箱工作目录。
allowed-tools: Bash
---

# Verify Disk Writer

提供一个 python 脚本 `verify.py`，向工作目录写一行日志。
```

`my_test_skill/verify.py`：
```python
import datetime

def write_test_log():
    with open("verification.log", "a") as f:
        f.write(f"Verified at: {datetime.datetime.now()}\n")
    print("Success! wrote verification.log")
```

> 命名约束：新建 / 导入技能的 `name` 应使用小写字母数字连字符、≤64 字符，并与技能目录名一致。

### 2.2 导入（UI）
1. 左侧导航进入 **资源 → 技能**（`/managed/skills`）。
2. 点 **导入 ZIP**（`POST /api/v1/skills/import-zip`），拖入 `my_test_skill.zip`。
3. 后端解析 + 校验 + 触发 skillspector 扫描（较大的包走后台任务）。

### 2.3 验证存储与扫描
- 在技能详情页核对名称 / 描述 / 标签是否读自你的 `SKILL.md` YAML。
- 查看 **安全扫描（Security Scans）** 状态：`GET /api/v1/skills/{id}/security-scans/latest`。
- 若技能要被 Agent 使用，需推进生命周期到 `approved`
  （`POST /api/v1/skills/{id}/submit-review` → `.../approve`）。

### 2.4 挂到 Agent 并运行验证
1. 打开一个 Agent 的编辑器，在 **技能** 区选中 `verify-disk-writer`（可选特定版本）。保存。
   *（技能引用写进 Agent 的 `skills` JSONB。）*
2. 用该 Agent 开一个 Session，发消息：
   > “运行你技能包里的 `verify.py`，调用 `write_test_log()`，只输出脚本返回值。”
3. 在会话事件流里观察 `agent.tool_use` / `agent.tool_use`（Bash）与文本输出 `Success! wrote verification.log`。
   看到即闭环——技能已被打包投递进沙箱并被消费。

> **验证进沙箱了吗？** 若你用本地 Docker provider，可 `docker ps | grep joysafeter` 找到会话沙箱，
> `docker exec -it <id> sh` 进去查看工作目录下的技能目录是否已解压出 `verify-disk-writer/`。

---

## 3. Web 编辑器、版本化与协作

**资源 → 技能**（`/managed/skills`）提供完整的 UI 生命周期管理：

- **Web 代码编辑器**：直接在浏览器改 `SKILL.md` / 脚本并保存。
  > ⚠️ 保存只更新数据库存根。**沙箱内运行的是会话启动时打包的快照**——改完技能后重开 / 新建 Session
  > 才会拿到最新版本（且需重新通过安全扫描与 `approved` 闸门）。
- **版本化**：`POST /api/v1/skills/{id}/versions` 把当前文件快照为不可变版本（SemVer）；可从历史版本恢复
  （`restore`）。已发布版本带独立的安全扫描记录。
- **协作者**：按角色分级（viewer < editor < admin），支持转移所有权。
- **可见性**：四级 —— `private` / `project` / `organization` / `public`。设为 `public` 后出现在
  公共技能大厅；他人使用时，代码会被打包进**他自己**的隔离沙箱执行。

---

## 4. 高级排障

- **导入报 Invalid File Type**：压缩包含 `.DS_Store` / 二进制文件。校验只放行纯文本（`.py/.md/.json/.yaml` 等）。
- **技能没被 Agent 使用**：确认已发布至少一个版本，Agent 引用的明确版本仍存在；旧 Session 仍使用
  启动时快照时，需要重开 Session 才会采用新的版本引用。
- **改了 `SKILL.md` 名称 / 描述没更新**：YAML frontmatter 是权威源，改元数据要改 `SKILL.md` 顶部 YAML。

---

## 下一步

- [教程 04](./04-agent-build-and-run.md)：把模型 / 工具 / MCP / 技能组装成一个 Agent 并运行
