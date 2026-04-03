# 沙箱体系整体改造设计

## 问题背景

沙箱体系存在四个维度的问题：

1. **引用计数泄漏**：`_get_user_sandbox` 通过 `ensure_sandbox_running` 获取 adapter（`active_count+1`），但 `_cleanup_backend` 只调 `adapter.cleanup()`，不调 `pool.release()`。`active_count` 永远不归零，空闲回收永远不触发，Docker 容器堆积。

2. **上传路径绕过 adapter 抽象**：当前方案 B 直接写宿主机挂载目录，绕过了 `PydanticSandboxAdapter`。应该通过 adapter API 写入，保持抽象层完整。

3. **多 worker 并发不安全**：`SandboxPool` 是进程内单例，`asyncio.Lock` 只在单进程有效。多 worker 部署时，worker A 的 pool 不知道 worker B 的容器状态，可能重复创建或连接失败。

4. **execute 安全边界缺失**：Agent 可在容器内执行任意 shell 命令，无 pids-limit、无网络隔离、无危险命令过滤。

## 改造范围

### Part 1：SandboxHandle — 引用计数 RAII 封装

**新建 `backend/app/services/sandbox_handle.py`：**

```python
class SandboxHandle:
    """RAII wrapper — acquire on create, release on exit/release().

    不使用 __del__ 作为安全网：Python 的 __del__ 在 async 上下文中不可靠，
    且无法调用 async release()。改用定期审计检测泄漏。
    """

    def __init__(self, adapter, sandbox_id: str, pool):
        self.adapter = adapter
        self._sandbox_id = sandbox_id
        self._pool = pool
        self._released = False

    @property
    def released(self) -> bool:
        return self._released

    async def release(self):
        if not self._released:
            self._released = True
            await self._pool.release(self._sandbox_id)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.release()
```

**泄漏检测：** 不依赖 `__del__`（Python async 上下文中不可靠），改为在 `SandboxPool.cleanup_idle()` 中增加审计日志：如果某个 entry 的 `active_count > 0` 超过 30 分钟，记录 warning。

**改造点：**

| 文件 | 改动 |
|------|------|
| `sandbox_manager.py` | `ensure_sandbox_running()` 返回 `SandboxHandle` 而非裸 adapter |
| `sandbox_manager.py` | 新增 `warm_up_sandbox(user_id)` 方法，只确保容器运行，不增减 `active_count` |
| `builder.py` | `_get_user_sandbox()` 返回 handle，保存在 graph 生命周期内 |
| `builder.py` | `_cleanup_backend()` 改为 `handle.release()`（不再直接 `adapter.cleanup()`） |
| `chat_turn_executor.py` | finally 块调用 `handle.release()` |
| `auth.py` | `_warm_up_sandbox` 改用 `warm_up_sandbox()` 而非 `ensure_sandbox_running()` |

**`warm_up_sandbox` vs `ensure_sandbox_running`：**
- `warm_up_sandbox(user_id)` — 确保容器运行，不增 `active_count`，用于登录预热
- `ensure_sandbox_running(user_id)` — 确保容器运行 + 返回 `SandboxHandle`（`active_count+1`），用于需要操作沙箱的场景

**关键语义：** `release()` ≠ `cleanup()`。release 只减引用计数，容器继续运行供后续请求复用。只有 pool 的 idle cleanup 才真正销毁容器。

### Part 2：PydanticSandboxAdapter 能力补全

上游 `DockerSandbox.write()` 签名是 `content: str | bytes`，原生支持二进制（通过 Docker `put_archive` API）。但 `PydanticSandboxAdapter.write()` 把参数类型限制成了 `content: str`。

**改造 `backend/app/core/agent/backends/pydantic_adapter.py`：**

| 方法 | 改动 |
|------|------|
| `write(path, content)` | 参数类型 `str` → `str \| bytes`，透传给上游 |
| `write_overwrite(path, content)` | 参数类型 `str` → `str \| bytes`，透传给上游 |
| 新增 `delete(path)` | 封装 `execute(f"rm {shlex.quote(path)}")`，返回 bool |
| 新增 `mkdir(path)` | 封装 `execute(f"mkdir -p {shlex.quote(path)}")`，返回 bool |

**同步更新 `backend/app/core/agent/backends/file_tracking_proxy.py`：**

`FileTrackingProxy` 的 `write` 和 `write_overwrite` 方法中 `content.encode("utf-8")` 会在 `bytes` 输入时崩溃。改为：

```python
size = len(content) if isinstance(content, bytes) else len(content.encode("utf-8"))
```

同时为 `delete` 和 `mkdir` 新方法添加透传。

**关于 adapter 调用是同步阻塞的：** `PydanticSandboxAdapter` 的所有方法（write、read、execute 等）都是同步的，会阻塞事件循环。对于大文件上传（最大 50MB），应在 Files API 中用 `asyncio.to_thread()` 包装：

```python
result = await asyncio.to_thread(handle.adapter.write_overwrite, container_path, content)
```

### Part 3：上传改 adapter API（回退方案 B，改为方案 A）

**依赖 Part 1 的 SandboxHandle 和 Part 2 的 adapter 能力补全。**

**前置操作：** 回退之前的 commit（方案 B 的宿主机直写改动），`files.py` 重新基于 adapter API 实现。保留 `constants.py` 中的共享常量和 `sandbox_paths.py` 中的 `get_user_sandbox_host_dir`（`sandbox_manager.py` 仍需要宿主机路径来设置 Docker volume）。

**改造 `backend/app/api/v1/files.py`：**

```python
import asyncio
from app.services.sandbox_manager import SandboxManagerService
from app.core.database import AsyncSessionLocal

async def _get_sandbox_handle(user_id: str) -> SandboxHandle:
    """获取用户沙箱 handle，用于文件操作。"""
    async with AsyncSessionLocal() as db:
        service = SandboxManagerService(db)
        return await service.ensure_sandbox_running(user_id)

@router.post("/upload")
async def upload_file(request, current_user, file):
    async with await _get_sandbox_handle(str(current_user.id)) as handle:
        content = await file.read()
        safe_filename, err = validate_file_upload(filename, content, content_type, handle.adapter)
        if err:
            raise err
        container_path = f"/workspace/uploads/{safe_filename}"
        await asyncio.to_thread(handle.adapter.mkdir, "/workspace/uploads")
        result = await asyncio.to_thread(handle.adapter.write_overwrite, container_path, content)
        if result.error:
            raise HTTPException(500, detail=result.error)
        return UploadResponse(path=container_path, ...)
```

| 接口 | adapter 方法 | 包装 |
|------|-------------|------|
| `POST /upload` | `mkdir()` + `write_overwrite(path, bytes)` | `asyncio.to_thread` |
| `GET /list` | `ls_info("/workspace/uploads/")` | `asyncio.to_thread` |
| `GET /read/{filename}` | `raw_read(path)` | `asyncio.to_thread` |
| `DELETE /{filename}` | `delete(path)` | `asyncio.to_thread` |
| `DELETE /` (clear) | `execute("rm -rf /workspace/uploads/*")` + `mkdir(...)` | `asyncio.to_thread` |

**存储配额检查：** 当前 `_get_upload_dir_size()` 用 `os.scandir` 扫描宿主机目录。改为通过 adapter：

```python
def _get_upload_dir_size(adapter) -> int:
    result = adapter.execute("du -sb /workspace/uploads 2>/dev/null || echo 0")
    # 解析 du 输出，返回字节数
```

**路径统一：** 上传返回 `/workspace/uploads/{filename}`，Agent 用同路径 `read_file`。全链路零转换。

**沙箱未就绪时：** `ensure_sandbox_running()` 按需创建沙箱（幂等），上传时自动触发。

### Part 4：多 worker 并发安全加强

不改 pool 架构，加强 reconnect 路径健壮性。

**改造 `backend/app/services/sandbox_manager.py`：**

1. **reconnect 路径加强：**
   - pool miss 时先查 DB `container_id`
   - reconnect 失败时 `docker inspect` 确认容器状态
   - 容器存在但停止 → restart
   - 容器不存在 → 清理 DB 记录（置 `container_id=None`, `status=pending`），重新创建
   - 加重试（最多 2 次）

2. **Pool cleanup 前检查 DB：**
   - `cleanup_idle` 在清理前查 DB 记录 `status`
   - 如果 DB 显示 `running` 但本 worker 的 pool 里 `active_count == 0`，跳过清理（可能其他 worker 在用）
   - 只清理 DB 状态也是 `idle` 或 `stopped` 的容器

3. **Stale entry 检测：**
   - Pool entry 加 `created_at: float` 字段
   - 超过 2 小时未使用且 `active_count == 0` 时，主动 `docker inspect` 验证容器存活
   - 容器已死 → 从 pool 移除，清理 DB 记录

4. **container_id 过期检测：**
   - DB 中 `container_id` 可能指向已被 Docker 自动清理的容器
   - reconnect 时如果 `docker inspect` 返回 404，清理 DB 记录并重新创建

**改造 `backend/app/services/sandbox_pool.py`：**

- `PoolEntry` 新增 `created_at: float` 字段
- `cleanup_idle` 增加可选的 DB 状态检查回调参数

### Part 5：execute 安全边界

**改造 `backend/app/services/sandbox_manager.py`（容器创建时）：**

1. **`pids_limit=256`** — 传入 Docker 容器创建参数，防止 fork bomb
2. **网络隔离** — `network_mode="none"`（默认）。如果 Agent 需要网络访问（如 tavily_search），通过配置开启受限网络

**改造 `backend/app/core/agent/backends/pydantic_adapter.py`（execute 方法）：**

3. **命令黑名单（纵深防御，非唯一防线）：**

```python
DANGEROUS_PATTERNS = [
    r"rm\s+-rf\s+/\s*$",       # rm -rf /
    r"mkfs\.",                   # format disk
    r"dd\s+.*of=/dev/",         # write to device
    r":\(\)\s*\{",              # fork bomb
]
```

注意：命令黑名单可被绕过（base64 编码、变量替换等），仅作为纵深防御层。真正的安全边界是 Docker 隔离 + pids-limit + 网络隔离。

4. **磁盘配额** — Docker `--storage-opt size=2G`（需要 overlay2 + xfs，可选，视部署环境决定）

## 实施顺序

```
Part 1 (SandboxHandle)           ← 基础设施，最先修
  ↓
Part 2 (adapter 能力补全)         ← Part 3 的前置依赖
  ↓
Part 3 (上传改 adapter API)       ← 依赖 Part 1 + Part 2
  ↓
Part 4 (多 worker 安全)           ← 独立，但建议在 Part 1 之后
  ↓
Part 5 (execute 安全)             ← 独立
```

## 需要回退的改动

之前的 commit `0623c20a`（方案 B 宿主机直写）需要部分回退：
- `files.py` — 完全重写为 adapter API 方式
- `sandbox_paths.py` — 保留（`sandbox_manager.py` 仍需要宿主机路径设置 Docker volume）
- `constants.py` — 保留共享常量
- `chat.py` `_enrich_message` — 保留（路径提示 + read_file 引导不变）
- `sandbox_manager.py` — 保留共享常量引用
- `node_tools.py` — 保留共享常量引用 + sanitize 修复

## 验证方式

**Part 1：**
- 单元测试：SandboxHandle 的 acquire/release/context-manager 语义
- 集成测试：Agent turn 完成后 active_count 归零
- 审计日志：active_count > 0 超过 30 分钟时记录 warning

**Part 2：**
- 单元测试：write_overwrite 接受 bytes，delete/mkdir 正常工作
- 单元测试：FileTrackingProxy 正确处理 bytes 输入
- 集成测试：50MB 二进制文件通过 write_overwrite 写入成功

**Part 3：**
- 端到端：上传文件 → Agent read_file 成功读取
- API 测试：list/read/delete 通过 adapter 正常工作
- 配额测试：存储配额检查通过 adapter execute 正常工作

**Part 4：**
- 模拟测试：worker A 创建容器，worker B 能 reconnect
- 模拟测试：pool cleanup 不清理其他 worker 正在使用的容器
- 模拟测试：container_id 指向已删除容器时能正确重建

**Part 5：**
- 安全测试：fork bomb 命令被 pids-limit 阻止
- 安全测试：危险命令被黑名单拦截（纵深防御验证）
- 安全测试：容器无法访问外部网络（network_mode=none 时）
