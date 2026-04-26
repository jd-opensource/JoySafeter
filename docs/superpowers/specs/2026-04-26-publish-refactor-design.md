# Agent 发布流程重构设计

## 问题

当前 Agent 平台有两个独立的「发布」入口，用户不知道该用哪个：

1. **Build Wizard 第 4 步「发布阶段」** — `AgentReleaseStage`，自动 freeze 后 publish
2. **Settings Tab 第 4 section「发布管理」** — `ReleaseManager` dialog，要求手动选 frozen version + runtimeKind

两者调用同一个后端，但行为不一致。更深层的问题是职责错位：前端在编排后端的事务逻辑（freeze → publish → unfreeze rollback），后端只暴露原子操作，没有提供「发布」这个业务语义。

### 约束

- 用户群体以非技术用户为主
- 单一环境，无 staging/production 区分
- freeze/unfreeze、runtimeKind、version vs release 等概念不应暴露给用户

## 方案

**Wizard 主导，Settings 退化为历史记录。**

- 发布只在 Build Wizard 里触发（唯一入口）
- Settings 展示发布历史 + 回滚/退役操作（只读管理）
- 后端新增高层语义端点，前端不再编排事务

## 后端设计

### 核心原则：sub-service 不 commit，编排层统一 commit

当前 `AgentVersionService.freeze_version()` 和 `AgentReleaseService.publish_release()` 各自在方法末尾调用 `self.commit()`。多步操作被拆成多个独立事务，freeze 成功但 publish 失败会导致脏状态。

改造后：sub-service 方法只做 validate + repo 操作 + flush，永远不 commit。commit 权统一在编排层（`AgentPublishService`）或 API route handler。

### 新建：AgentPublishService

文件：`backend/app/services/agent_publish_service.py`

```python
class AgentPublishService(BaseService):
    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.version_svc = AgentVersionService(db)
        self.release_svc = AgentReleaseService(db)
        self.agent_repo = AgentRepository(db)

    async def publish(self, agent_id: str, user_id: str) -> dict:
        agent = await self.agent_repo.get(agent_id)
        if not agent:
            raise NotFoundException(f"Agent {agent_id} not found")

        version = await self._resolve_current_draft(agent)

        if version.status == "draft":
            await self.version_svc.freeze_version(version.id)

        runtime_kind = self._infer_runtime_kind(version.definition_kind)
        release = await self.release_svc.publish_release(
            agent_id, user_id,
            {"agent_version_id": version.id, "runtime_kind": runtime_kind},
        )

        await self.release_svc.activate_release(agent_id, release.id)

        await self.safe_commit()
        return {"agent": agent, "release": release}

    async def rollback(self, agent_id: str, release_id: str) -> dict:
        await self.release_svc.activate_release(agent_id, release_id)
        await self.safe_commit()
        agent = await self.agent_repo.get(agent_id)
        return {"agent": agent}

    async def retire(self, agent_id: str, release_id: str) -> dict:
        release = await self.release_svc.retire_release(agent_id, release_id)
        await self.safe_commit()
        return {"release": release}

    async def _resolve_current_draft(self, agent) -> AgentVersion:
        if not agent.current_draft_version_id:
            raise BadRequestException("Agent has no draft version")
        version = await AgentVersionRepository(self.db).get(agent.current_draft_version_id)
        if not version:
            raise NotFoundException("Draft version not found")
        return version

    @staticmethod
    def _infer_runtime_kind(definition_kind: str) -> str:
        if definition_kind in ("graph", "hybrid"):
            return "graph"
        if definition_kind == "code":
            return "sandbox"
        return "graph"
```

### 改造：子 Service 去掉 commit

**AgentVersionService：**
- `freeze_version()` — 删除末尾的 `await self.commit()`
- `unfreeze_version()` — 整个方法删除（只为前端 rollback hack 存在）

**AgentReleaseService：**
- `publish_release()` — 删除末尾的 `await self.commit()`
- `activate_release()` — 删除末尾的 `await self.commit()`
- `retire_release()` — 删除末尾的 `await self.commit()`
- `list_releases()` — 只读，不受影响
- `get_release()` — 只读，不受影响

### 涟漪影响

| 调用者 | 调用了什么 | 处理 |
|--------|-----------|------|
| AgentPublishService | freeze + create + activate | safe_commit() |
| AgentService.create_agent() | version_repo.create()（直接调 repo） | 已有自己的 commit，不受影响 |
| orchestrator.py | 读取 active_release_id | 只读，不受影响 |
| delete_agent() | raw SQL cascade | 不走 service，不受影响 |

### API 端点变更

**新增：**

| 方法 | 路径 | Handler | 权限 |
|------|------|---------|------|
| POST | `/{agent_id}/publish` | `publish_agent` | admin |
| POST | `/{agent_id}/rollback` | `rollback_agent` | admin |

**删除：**

| 方法 | 路径 | 原因 |
|------|------|------|
| POST | `/{agent_id}/versions/{version_id}/freeze` | 内化到 publish 流程 |
| POST | `/{agent_id}/versions/{version_id}/unfreeze` | 不再需要（无前端 rollback hack） |
| POST | `/{agent_id}/releases` (create) | 替换为 /publish |
| POST | `/{agent_id}/releases/{release_id}/activate` | 替换为 /rollback |

**保留：**

| 方法 | 路径 | 原因 |
|------|------|------|
| GET | `/{agent_id}/releases` | 发布历史列表 |
| GET | `/{agent_id}/releases/{release_id}` | 查看单个 release |
| POST | `/{agent_id}/releases/{release_id}/retire` | 退役（走 PublishService.retire()） |

### Request/Response

```
POST /agents/{agent_id}/publish
Request: {} (无参数 — 自动取 current draft + 推断 runtimeKind)
Response: { agent: Agent, release: AgentRelease }

POST /agents/{agent_id}/rollback
Request: { release_id: string }
Response: { agent: Agent }
```

### 事务保证

`AgentPublishService.publish()` 内的所有操作共享同一个 `AsyncSession`（FastAPI `Depends(get_db)` 保证每个 request 一个 session）。所有 repo 操作只 flush 不 commit，`safe_commit()` 是唯一的 commit 点。如果任何一步失败，`safe_commit()` 的 catch 会 rollback 整个事务，加上 `get_db` 的 exception handler 兜底。

### 状态机流转

一次 publish 调用触发三个实体的状态变更，全在一个事务里：

```
AgentVersion:  draft → frozen
AgentRelease:  (不存在) → ready
Agent:         draft → active (active_release_id = new release)
```

状态机定义（`definitions.py`）不变。

## 前端设计

### 目标：从 5 层嵌套到 3 层扁平

```
现在：UI → adapter → adapter → hooks → service → HTTP (5层，3条路径)
目标：UI → hooks → service → HTTP                   (3层，1条路径)
```

### 新建文件

**`services/agentPublishService.ts`**

纯 HTTP 客户端，1:1 映射后端端点：

```typescript
const agentPublishService = {
  publish(agentId: string, workspaceId: string) {
    return api.post(`/agents/${agentId}/publish`, { params: { workspace_id: workspaceId } })
  },
  rollback(agentId: string, releaseId: string, workspaceId: string) {
    return api.post(`/agents/${agentId}/rollback`, {
      data: { release_id: releaseId },
      params: { workspace_id: workspaceId },
    })
  },
  retire(agentId: string, releaseId: string, workspaceId: string) {
    return api.post(`/agents/${agentId}/releases/${releaseId}/retire`, {
      params: { workspace_id: workspaceId },
    })
  },
  list(agentId: string, workspaceId: string) {
    return api.get(`/agents/${agentId}/releases`, { params: { workspace_id: workspaceId } })
  },
}
```

**`hooks/queries/agentPublish.ts`**

```typescript
export const publishKeys = {
  releases: (agentId: string) => ['agents', agentId, 'releases'] as const,
}

export function useReleaseHistory(agentId: string, workspaceId: string) {
  return useQuery({
    queryKey: publishKeys.releases(agentId),
    queryFn: () => agentPublishService.list(agentId, workspaceId),
  })
}

export function usePublishAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ agentId, workspaceId }) =>
      agentPublishService.publish(agentId, workspaceId),
    onSuccess: (_, { agentId }) => {
      qc.invalidateQueries({ queryKey: publishKeys.releases(agentId) })
      qc.invalidateQueries({ queryKey: agentKeys.detail(agentId) })
    },
  })
}

export function useRollbackAgent() {
  // 同上模式，调用 agentPublishService.rollback
}

export function useRetireRelease() {
  // 同上模式，调用 agentPublishService.retire
}
```

### 删除文件

| 文件 | 类型 |
|------|------|
| `components/agents/agent-build/agent-release-adapter.ts` | 整个文件删除 |
| `components/agents/release-manager.tsx` | 整个文件删除 |
| `components/editors/graph-builder/services/deploymentAdapter.ts` | 整个文件删除 |

### 删除导出

| 文件 | 删除的导出 |
|------|-----------|
| `hooks/queries/agentReleases.ts` | `usePublishRelease`, `useActivateRelease` |
| `hooks/queries/agentVersions.ts` | `useFreezeVersion`, `useUnfreezeVersion` |
| `services/agentReleaseService.ts` | `.publish()`, `.activate()` |
| `services/agentVersionService.ts` | `.freeze()`, `.unfreeze()` |

如果 `agentReleases.ts` 中只剩 `useReleases` 和 `useRetireRelease`，且 `useRetireRelease` 已移到 `agentPublish.ts`，则整个文件可评估删除或仅保留 `releaseKeys`（如果其他模块还在引用）。同理 `agentVersionService.ts` 中 freeze/unfreeze 删除后如果 `list`/`get`/`create`/`update` 仍被使用则保留。

### 重写文件（8个）

**1. `agent-release-stage.tsx`**

简化为三态 UI：
- **未发布态**：居中大按钮「发布」，说明文案
- **已发布态**：顶部绿色状态卡（当前版本 + 发布时间）+ 「发布新版本」链接 + 折叠历史列表
- **发布中态**：按钮 loading

操作：
- 「发布」→ `usePublishAgent().mutate()`
- 「回滚到此版本」→ `useRollbackAgent().mutate()`
- 「退役」→ `useRetireRelease().mutate()`（放在 `···` 溢出菜单）

用户面向语言替换：
| Before | After |
|--------|-------|
| "Publish Draft" | "发布" |
| "Release lifecycle" | 去掉 |
| "#3 ready graph Active" | "版本 3 · 发布于 12月20日" |
| "Activate" | "回滚到此版本" |
| "Retire" | 放在 ··· 菜单 |

**2. `agent-settings-tab.tsx`**

- 删除 Section 3（版本管理）
- Section 4 改名：「发布管理」→「发布历史」
- 删除 Publish 按钮和 ReleaseManager dialog
- 保留只读列表（版本号 + 时间 + 状态）
- 添加「回滚到此版本」按钮
- 添加「前往发布阶段」导航链接
- 删除所有 freeze/unfreeze/activate hook 引用

**3. `useDeploymentHistory.ts`**

保留此 hook（Graph Builder 特有的画布预览逻辑需要它），但内部重写：
- 删除 `deploymentAdapter` 引用
- 用 `usePublishAgent()`, `useRollbackAgent()`, `useRetireRelease()`, `useReleaseHistory()` 替代
- 画布预览/diff 逻辑保留（通过 `agentVersionService.get()` 加载 definition_payload）

**4. `DeploymentHistoryPanel.tsx`**

适配 `useDeploymentHistory` 的新 API 形状。主要是 props 类型可能变化。

**5. `CodeEditorPage.tsx`**

- `deploymentAdapter.deploy(...)` → `usePublishAgent().mutate()`
- 删除对 `saveStore.deployedAt` 的读写

**6. `saveStore.ts`**

删除 `deployedAt` 和 `setDeployedAt` 字段。

**7. `DeploymentVersionsList.tsx`**

更新从 `useDeploymentHistory` 导入的类型引用。

**8. `agent-build-stages.test.tsx`**

更新所有 mocks：`agentReleases` → `agentPublish`，删除 `agent-release-adapter` mock。

### i18n 变更

删除的 key：
- `agents.build.release.kicker` ("Release lifecycle")
- `agents.build.release.publishDraft` ("Publish Draft")
- `agents.detail.releaseManagement` ("发布管理")
- `agents.detail.publishReleaseTitle/Description`
- `agents.detail.noFrozenVersions`
- `agents.detail.selectFrozenVersion`
- `agents.detail.runtimeKind`
- `agents.detail.runtimeKindOptions.*`
- `agents.detail.runtimeBinding`
- `agents.detail.publishRelease/publishingRelease`
- `agents.detail.versionManagement` (如果存在)
- `workspace.deploy` / `workspace.undeploy`

新增/修改的 key：
- `agents.build.release.title` → "发布你的 Agent" / "Publish your Agent"
- `agents.build.release.subtitle` → "发布后即可通过对话、任务和 API 使用"
- `agents.build.release.publish` → "发布" / "Publish"
- `agents.build.release.publishNew` → "发布新版本" / "Publish new version"
- `agents.build.release.currentActive` → "当前已发布" / "Currently published"
- `agents.build.release.history` → "历史版本" / "Version history"
- `agents.build.release.rollback` → "回滚到此版本" / "Roll back to this version"
- `agents.detail.releaseHistory` → "发布历史" / "Release History"
- `agents.detail.goToPublish` → "前往发布阶段" / "Go to publish"

## 不变的部分

- **数据库模型**：`agents`, `agent_versions`, `agent_releases` 三张表不变
- **状态机定义**：`definitions.py` 不变
- **Repository 层**：所有 repository 不变（它们本来就只 flush 不 commit）
- **orchestrator.py**：只读 `active_release_id`，不受影响
- **AgentService**：`create_agent`, `delete_agent` 不受影响（直接操作 repo 或 raw SQL）
- **`get_db`**：session 管理不变
