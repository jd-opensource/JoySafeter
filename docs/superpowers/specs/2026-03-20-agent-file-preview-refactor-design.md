# Agent 文件 Preview 全流程重构设计

**日期:** 2026-03-20
**状态:** Draft
**分支:** skill_add

## 问题

当前 Agent 执行过程中文件 preview 实现过于复杂：

1. **两套数据路径** — 执行中用 `liveFiles`（从 `tool_end` SSE 的 `files_changed` 提取）+ sandbox live read；执行完用 artifact API（list + download）
2. **依赖工具名匹配** — `_extract_files_changed()` 硬编码了 `save_file`、`write`、`edit` 等工具名，新增工具需手动维护
3. **非增量** — `ArtifactCollector` 在运行结束后扫描整个目录写 manifest，与实时 preview 割裂

## 目标

1. **增量事件驱动** — 每个文件操作（create/edit/delete）作为独立 SSE `file_event` 推送，前端实时更新文件树
2. **统一数据源** — 只使用 sandbox live read，消除 live/artifact 双路径
3. **零工具名耦合** — 通过 Proxy 模式拦截所有 `SandboxBackendProtocol` 写操作，自动发事件

## 架构

### 数据流

```
Sandbox write/edit
       │
       ▼
FileTrackingProxy (拦截写操作)
       │
       ▼
FileEventEmitter (线程安全队列)
       │
       ▼
chat.py SSE 循环 drain()
       │
       ▼
SSE file_event 推送
       │
       ▼
前端 useBackendChatStream 更新 fileTree
       │
       ▼
ArtifactPanel 展示文件树 + sandbox live read 预览
```

### 组件设计

#### 1. `FileEventEmitter`

位置: `backend/app/utils/file_event_emitter.py`（新文件）

```python
@dataclass
class FileEvent:
    action: str   # "create" | "edit" | "delete"
    path: str     # 文件相对路径
    size: int | None = None

class FileEventEmitter:
    """线程安全的文件事件收集器。Proxy 写入，SSE 循环消费。"""

    def __init__(self):
        self._queue: collections.deque[FileEvent] = collections.deque()

    def emit(self, action: str, path: str, size: int | None = None):
        self._queue.append(FileEvent(action=action, path=path, size=size))

    def drain(self) -> list[FileEvent]:
        """取出所有待发送事件，供 SSE 循环调用。"""
        events = list(self._queue)
        self._queue.clear()
        return events
```

#### 2. `FileTrackingProxy`

位置: `backend/app/core/agent/backends/file_tracking_proxy.py`（新文件）

```python
class FileTrackingProxy(SandboxBackendProtocol):
    """包装任何 SandboxBackendProtocol，拦截写操作发出文件事件。"""

    def __init__(self, backend: SandboxBackendProtocol, emitter: FileEventEmitter):
        self._backend = backend
        self._emitter = emitter

    def write(self, file_path, content) -> WriteResult:
        result = self._backend.write(file_path, content)
        if not result.error:
            self._emitter.emit("create", file_path, len(content.encode("utf-8")))
        return result

    def write_overwrite(self, file_path, content) -> WriteResult:
        result = self._backend.write_overwrite(file_path, content)
        if not result.error:
            self._emitter.emit("edit", file_path, len(content.encode("utf-8")))
        return result

    def edit(self, file_path, old_string, new_string, replace_all=False) -> EditResult:
        result = self._backend.edit(file_path, old_string, new_string, replace_all)
        if not result.error:
            self._emitter.emit("edit", file_path, None)
        return result

    # 其余方法全部 delegate 到 self._backend
    def read(self, file_path, offset=0, limit=2000): return self._backend.read(file_path, offset, limit)
    def ls_info(self, path): return self._backend.ls_info(path)
    def execute(self, command): return self._backend.execute(command)
    def grep_raw(self, pattern, path=None, glob=None): return self._backend.grep_raw(pattern, path, glob)
    def glob_info(self, pattern, path="/"): return self._backend.glob_info(pattern, path)
    def download_files(self, paths): return self._backend.download_files(paths)
    def upload_files(self, files): return self._backend.upload_files(files)
    # 透传生命周期和属性
    @property
    def id(self): return self._backend.id
    def is_started(self): return self._backend.is_started()
    def start(self): return self._backend.start()
    def stop(self): return self._backend.stop()
    def cleanup(self): return self._backend.cleanup()
```

设计原则：
- **零侵入** — 不修改 `PydanticSandboxAdapter` 或 `FileTools` 任何代码
- **透明代理** — 所有非写操作直接 delegate
- **只拦截成功的写操作** — error 时不发事件

#### 3. SSE 集成（`chat.py` 改动）

在 graph 构建后、事件流循环中注入：

```python
# 构建时
emitter = FileEventEmitter()
# 包装 sandbox backend
original_backend = ...  # 现有 sandbox adapter
tracked_backend = FileTrackingProxy(original_backend, emitter)

# SSE 循环中
async for event in graph.astream_events(...):
    yield handler.handle_xxx(event, state, ...)

    # 消费文件事件
    for file_evt in emitter.drain():
        yield handler.format_sse("file_event", {
            "action": file_evt.action,
            "path": file_evt.path,
            "size": file_evt.size,
        }, state.thread_id, state)
```

#### 4. 前端 `useBackendChatStream.ts` 改动

新增 `file_event` 处理：

```typescript
if (type === 'file_event') {
  const { action, path, size } = data as { action: string; path: string; size?: number }
  safeSetMessages(prev => prev.map(m => {
    if (m.id !== aiMsgId) return m
    const tree = { ...(m.metadata?.fileTree as Record<string, any> || {}) }
    if (action === 'delete') {
      delete tree[path]
    } else {
      tree[path] = { action, size, timestamp }
    }
    return { ...m, metadata: { ...m.metadata, fileTree: tree } }
  }))
  return
}
```

删除 `tool_end` 中的 `liveFiles` 累积逻辑。

#### 5. `ArtifactPanel.tsx` 简化

Props 变更：

```typescript
interface ArtifactPanelProps {
  threadId: string
  fileTree?: Record<string, { action: string; size?: number; timestamp?: number }>
  className?: string
}
```

核心逻辑：
- 从 `fileTree` 构建 `FileNode[]`（替代 `liveFilesToNodes`）
- 文件内容始终通过 `artifactService.liveReadFile(threadId, path)` 获取
- 删除 `runId`、`liveFiles` props
- 删除 `isLiveMode` 判断和 artifact API 调用（`listRunFiles`、`downloadFile`）
- 删除 `fileInfoToNode` 函数

### 删除的代码

| 文件 | 删除内容 |
|------|---------|
| `stream_event_handler.py` | `_FILE_WRITE_TOOLS`、`_extract_files_changed()` 函数、`handle_tool_end` 中的 `files_changed` 字段 |
| `useBackendChatStream.ts` | `tool_end` 中 `liveFiles` 累积逻辑、`artifacts_ready` 处理 |
| `ArtifactPanel.tsx` | `runId` / `liveFiles` props、`isLiveMode` 分支、artifact API 调用、`liveFilesToNodes`、`fileInfoToNode` |

### 保留的代码

| 文件 | 保留原因 |
|------|---------|
| `ArtifactCollector` / `ArtifactResolver` | 可能被其他功能使用（如历史回看），本次不删 |
| `artifacts.py` 的 `live_read_file` API | 仍然是文件内容预览的唯一来源 |
| `artifactService.liveReadFile` | 前端唯一的文件读取方法 |

## FileTools 覆盖

`FileTools`（`backend/app/core/tools/buildin/file.py`）是另一条文件写入路径，用于非 sandbox 场景。需要同样的 Proxy 包装：

- 如果 `FileTools` 作为 tool 注册到 agent，其 `save_file` / `replace_file_chunk` 写入的是本地文件系统
- 在构建 graph 时，对 FileTools 实例也包装 Proxy（需要适配其接口，因为 `save_file` 签名不同于 `SandboxBackendProtocol.write`）
- 或者：在 `_extract_files_changed` 删除后，如果 FileTools 写入的文件不需要前端 preview（非 sandbox 容器），可以不覆盖

**决策：** 本次只覆盖 `SandboxBackendProtocol`（容器方案），`FileTools` 后续按需处理。

## 测试策略

1. **单元测试 `FileTrackingProxy`** — 验证写操作成功时 emit、失败时不 emit、读操作透传
2. **单元测试 `FileEventEmitter`** — 验证 emit/drain 线程安全和幂等
3. **集成测试** — 发送 chat 消息触发文件写入，验证 SSE 流中包含 `file_event`
4. **前端测试** — 验证 `file_event` 正确更新 fileTree，ArtifactPanel 正确渲染
