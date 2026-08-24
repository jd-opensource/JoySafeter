# JoySafeter Agent / Environment / Session 接口文档

本文档整理 JoySafeter v1 API 中 **Agent**、**Environment**、**Session** 三类核心接口，并给出 curl 调用示例。

## 0. 通用说明

### 0.1 环境地址

不同环境只需要替换 `BASE` 地址，接口路径保持一致：

| 环境 | BASE 地址 | 说明 |
|---|---|---|
| 本地开发 | `http://127.0.0.1:8000/api/v1` | 本地启动 API 服务时使用 |
| K8s 集群内 pre | `http://joysafeter-api.joysafeter-pre.svc.cluster.local:8000/api/v1` | 集群内 Pod 调用 pre 环境 |
| K8s 集群内 prod | `http://joysafeter-api.joysafeter-prod.svc.cluster.local:8000/api/v1` | 集群内 Pod 调用 prod 环境，按实际 namespace 调整 |
| 外部网关 pre | `https://<pre-api-domain>/api/v1` | 第三方系统从集群外调用 pre 环境 |
| 外部网关 prod | `https://<prod-api-domain>/api/v1` | 第三方系统从集群外调用 prod 环境 |

> 上表中的外部域名、namespace、端口以实际部署为准。第三方系统接入时，先确认使用的是 pre 还是 prod 的 `BASE` 地址。

### 0.2 Base URL

后续示例统一使用环境变量 `BASE`：

```bash
BASE="http://<joysafeter-api-host>/api/v1"
```

Kubernetes 集群内 pre 环境示例：

```bash
BASE="http://joysafeter-api.joysafeter-pre.svc.cluster.local:8000/api/v1"
```

### 0.3 鉴权

外部系统推荐使用 API Key：

```http
X-Api-Key: <raw_api_key>
```

运行、创建、修改 Agent/Environment/Session 需要写权限，API Key 角色至少需要 `editor`。

也支持用户态 Bearer Token：

```http
Authorization: Bearer <access_token>
```

如果用户有多个 project，可传：

```http
X-Project-Id: <project_id>
```

API Key 本身绑定 project，一般不需要 `X-Project-Id`。

### 0.4 响应格式

普通 JSON 接口会被统一包装：

```json
{
  "success": true,
  "code": 200,
  "message": "OK",
  "data": {}
}
```

分页接口格式：

```json
{
  "success": true,
  "code": 200,
  "message": "OK",
  "data": [],
  "has_more": false,
  "first_id": null,
  "last_id": null
}
```

SSE 流接口不包装，直接返回 `text/event-stream`。

### 0.5 ID 前缀

返回 ID 通常带前缀：

| 对象 | 示例 |
|---|---|
| Agent | `agent_<uuid>` |
| Environment | `env_<uuid>` |
| Session | `sess_<uuid>` |
| Event | `evt_<uuid>` |
| Task | `task_<uuid>` |

路径参数一般支持带前缀的 ID，例如：

```http
GET /api/v1/agents/agent_xxx
GET /api/v1/environments/env_xxx
GET /api/v1/sessions/sess_xxx
```

### 0.6 第三方系统最简调用

第三方系统运行 Agent 只需要记住 3 步：

```text
1. 创建 Session
2. 发送 user.message
3. 通过 SSE 或 events 查询结果
```

推荐第三方只使用一种 Agent 指定方式：

```json
{
  "agent": "agent_4a8d0d69-3b8b-4ad1-ae3d-0f6d50a1a111"
}
```

最小示例：

```bash
BASE="http://<joysafeter-api-host>/api/v1"
API_KEY="<your-api-key>"
AGENT_ID="agent_4a8d0d69-3b8b-4ad1-ae3d-0f6d50a1a111"

# 1. 创建 Session
SESSION_ID=$(curl -sS -X POST "$BASE/sessions" \
  -H "X-Api-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"agent\": \"$AGENT_ID\",
    \"title\": \"third-party-run\",
    \"metadata\": {\"request_id\": \"req-10001\"}
  }" | jq -r '.data.id')

# 2. 发送消息，触发 Agent 运行
curl -sS -X POST "$BASE/sessions/$SESSION_ID/events" \
  -H "X-Api-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: req-10001" \
  -d '{
    "type": "user.message",
    "content": "请分析这个需求，并给出实现方案。"
  }' | jq

# 3. 流式获取结果
curl -N "$BASE/sessions/$SESSION_ID/events/stream?after_seq=0" \
  -H "X-Api-Key: $API_KEY"
```

> 简单理解：**Agent 提前创建好，第三方系统每次业务请求创建一个 Session，然后发一条 `user.message`。**

---

## 1. Agent 接口

Agent 是 JoySafeter 中可执行的智能体配置，包含模型、系统提示词、工具、MCP、技能、环境引用等。

### 1.1 Agent 数据结构

#### 创建 Agent 请求

```json
{
  "name": "claude-code",
  "engine_kind": "claude",
  "model": {
    "id": "claude-sonnet-4-20250514",
    "speed": "standard"
  },
  "system_prompt": "你是一个代码分析助手",
  "description": "用于分析代码仓库的 Agent",
  "metadata": {
    "team": "security"
  },
  "env": {
    "FOO": "bar"
  },
  "mcp_servers": [],
  "skills": [],
  "agents": [],
  "commands": [],
  "tools": [
    {
      "type": "agent_toolset_20260401",
      "default_config": {
        "enabled": true,
        "permission_policy": {
          "type": "always_allow"
        }
      },
      "configs": []
    }
  ],
  "multiagent": null,
  "environment_ref": "ubuntu24-dev",
  "secret_ref": "claude-secret"
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `name` | string | 是 | Agent 名称，同 project 下应唯一 |
| `engine_kind` | string | 否 | `claude` / `codex` / `native`，默认 `claude` |
| `model` | string/object/null | 否 | 模型配置，也可直接传字符串 |
| `system_prompt` | string | 否 | 系统提示词，返回字段为 `system` |
| `description` | string | 否 | 描述 |
| `metadata` | object | 否 | 自定义元数据 |
| `env` | object | 否 | 注入到运行环境的环境变量 |
| `mcp_servers` | array | 否 | MCP server 配置 |
| `skills` | array | 否 | Skill 引用或内联包 |
| `agents` | array | 否 | 子 Agent 包 |
| `commands` | array | 否 | 自定义命令包 |
| `tools` | array | 否 | 工具配置 |
| `multiagent` | object/null | 否 | 多 Agent 配置 |
| `environment_ref` | string | 否 | 绑定的 Environment 名称或 ID |
| `secret_ref` | string | 否 | LLM 密钥引用 |

`engine_kind` 和 `secret_ref` 要兼容：

- `claude`：需要 Anthropic/Claude 类 secret
- `codex`：需要 OpenAI/Codex 类 secret
- `native`：按 native runtime 配置

---

### 1.2 创建 Agent

```http
POST /api/v1/agents
```

示例：

```bash
curl -sS -X POST "$BASE/agents" \
  -H "X-Api-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "claude-code",
    "engine_kind": "claude",
    "model": "claude-sonnet-4-20250514",
    "system_prompt": "你是一个专业的代码分析助手，回答要简洁准确。",
    "description": "代码分析 Agent",
    "environment_ref": "ubuntu24-dev",
    "secret_ref": "claude-secret",
    "tools": [
      {
        "type": "agent_toolset_20260401",
        "default_config": {
          "enabled": true,
          "permission_policy": {"type": "always_allow"}
        },
        "configs": []
      }
    ]
  }' | jq
```

响应示例：

```json
{
  "success": true,
  "code": 201,
  "message": "OK",
  "data": {
    "id": "agent_4a8d0d69-3b8b-4ad1-ae3d-0f6d50a1a111",
    "type": "agent",
    "name": "claude-code",
    "engine_kind": "claude",
    "model": {
      "id": "claude-sonnet-4-20250514",
      "speed": "standard"
    },
    "system": "你是一个专业的代码分析助手，回答要简洁准确。",
    "description": "代码分析 Agent",
    "metadata": {},
    "env": {},
    "mcp_servers": [],
    "skills": [],
    "agents": [],
    "commands": [],
    "tools": [],
    "multiagent": null,
    "version": 1,
    "environment_ref": "ubuntu24-dev",
    "secret_ref": "claude-secret",
    "created_at": "2026-08-11T10:00:00Z",
    "updated_at": "2026-08-11T10:00:00Z",
    "archived_at": null
  }
}
```

---

### 1.3 查询 Agent 列表

```http
GET /api/v1/agents?limit=20&after_id=<uuid>&include_archived=false
```

参数：

| 参数 | 类型 | 默认 | 说明 |
|---|---|---:|---|
| `limit` | int | 20 | 每页数量，1-100 |
| `after_id` | uuid | - | 游标分页，从该 ID 后继续 |
| `include_archived` | bool | false | 是否包含已归档 Agent |

示例：

```bash
curl -sS "$BASE/agents?limit=20" \
  -H "X-Api-Key: $API_KEY" | jq
```

---

### 1.4 查询 Agent 详情

```http
GET /api/v1/agents/{agent_id}
```

示例：

```bash
AGENT_ID="agent_4a8d0d69-3b8b-4ad1-ae3d-0f6d50a1a111"

curl -sS "$BASE/agents/$AGENT_ID" \
  -H "X-Api-Key: $API_KEY" | jq
```

---

### 1.5 更新 Agent

```http
POST /api/v1/agents/{agent_id}
```

> 更新 Agent 会产生新版本。建议带上当前 `version` 做乐观锁，避免并发覆盖。

示例：

```bash
curl -sS -X POST "$BASE/agents/$AGENT_ID" \
  -H "X-Api-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "version": 1,
    "description": "更新后的代码分析 Agent",
    "system_prompt": "你是资深代码审计助手，重点关注安全风险和部署问题。",
    "model": {
      "id": "claude-sonnet-4-20250514",
      "speed": "standard"
    }
  }' | jq
```

常见错误：

| code | 说明 |
|---|---|
| `AGENT_VERSION_CONFLICT` | version 不一致，刷新后重试 |
| `AGENT_ARCHIVED` | Agent 已归档，不能更新 |
| `AGENT_NOT_FOUND` | Agent 不存在 |

---

### 1.6 删除 Agent

```http
DELETE /api/v1/agents/{agent_id}?force=false
```

参数：

| 参数 | 类型 | 默认 | 说明 |
|---|---|---:|---|
| `force` | bool | false | 是否强制清理关联 active task / sandbox |

示例：

```bash
curl -sS -X DELETE "$BASE/agents/$AGENT_ID?force=false" \
  -H "X-Api-Key: $API_KEY" -i
```

成功时 HTTP 204，无响应体。

---

### 1.7 归档 Agent

```http
POST /api/v1/agents/{agent_id}/archive
```

示例：

```bash
curl -sS -X POST "$BASE/agents/$AGENT_ID/archive" \
  -H "X-Api-Key: $API_KEY" | jq
```

响应：

```json
{
  "success": true,
  "data": {
    "status": "archived",
    "archived_sessions": 3
  }
}
```

---

### 1.8 查询 Agent 的任务

```http
GET /api/v1/agents/{agent_id}/tasks
```

示例：

```bash
curl -sS "$BASE/agents/$AGENT_ID/tasks" \
  -H "X-Api-Key: $API_KEY" | jq
```

---

### 1.9 查询 Agent 的 Session

```http
GET /api/v1/agents/{agent_id}/sessions?limit=20&include_archived=false
```

示例：

```bash
curl -sS "$BASE/agents/$AGENT_ID/sessions?limit=20" \
  -H "X-Api-Key: $API_KEY" | jq
```

---

### 1.10 查询 Agent 版本列表

```http
GET /api/v1/agents/{agent_id}/versions?limit=20&before_version=<version>
```

示例：

```bash
curl -sS "$BASE/agents/$AGENT_ID/versions?limit=20" \
  -H "X-Api-Key: $API_KEY" | jq
```

---

## 2. Environment 接口

Environment 定义 Agent 运行时环境，包括包安装、网络策略、环境变量、Secret、外部 egress service、存储挂载等。

### 2.1 Environment 数据结构

创建请求：

```json
{
  "name": "ubuntu24-dev",
  "description": "Ubuntu 24 development environment",
  "metadata": {
    "owner": "platform"
  },
  "config": {
    "type": "cloud",
    "packages": {
      "apt": ["git", "curl", "jq"],
      "pip": [],
      "npm": [],
      "cargo": [],
      "gem": [],
      "go": []
    },
    "networking": {
      "type": "limited",
      "allowed_hosts": ["github.com", "api.github.com"],
      "allow_package_managers": true
    },
    "env_vars": {
      "TZ": "Asia/Shanghai"
    },
    "secret_refs": ["claude-secret"],
    "egress_services": [],
    "mount_resources": []
  }
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `name` | string | 是 | Environment 名称 |
| `description` | string | 否 | 描述 |
| `metadata` | object | 否 | 元数据 |
| `config.type` | string | 否 | 默认 `cloud` |
| `config.packages.apt` | array | 否 | apt 包列表 |
| `config.packages.pip` | array | 否 | pip 包列表 |
| `config.packages.npm` | array | 否 | npm 全局包列表 |
| `config.packages.cargo` | array | 否 | cargo 安装列表 |
| `config.packages.gem` | array | 否 | gem 包列表 |
| `config.packages.go` | array | 否 | go install 包列表 |
| `config.networking.type` | string | 否 | 默认 `limited` |
| `config.networking.allowed_hosts` | array | 否 | 允许访问的域名 |
| `config.networking.allow_package_managers` | bool | 否 | 是否允许包管理器联网 |
| `config.env_vars` | object | 否 | 环境变量 |
| `config.secret_refs` | array | 否 | 引用的 secret 名称 |
| `config.egress_services` | array | 否 | 外部服务凭证注入配置 |
| `config.mount_resources` | array | 否 | 存储挂载配置 |

#### mount_resources 结构

```json
{
  "type": "storage",
  "name": "workspace-data",
  "volume_ref": "cubefs-volume",
  "sub_path": "joysafeter/projects/demo",
  "mount_path": "/workspace/data",
  "access": "read_write",
  "required": true
}
```

约束：

- `type` 当前只支持 `storage`
- `access` 支持 `read_only` / `read_write`
- `mount_path` 必须是绝对路径，且不能挂载到 `/`、`/workspace`、`/etc`、`/root`、`/proc`、`/sys`、`/dev`、`/var`、`/sockets` 等保留路径
- `sub_path` 不能包含路径穿越
- 同一个 Environment 内 `mount_path` 不能重叠

#### egress_services 结构

```json
{
  "name": "github-api",
  "kind": "external",
  "exposure": "placeholder",
  "base_url": "https://api.github.com",
  "credential_ref": "github-token",
  "inject": {
    "type": "bearer",
    "secret_key": "GITHUB_TOKEN",
    "header": "Authorization"
  }
}
```

`inject.type` 支持：

| 类型 | 说明 |
|---|---|
| `bearer` | 注入 Bearer Token |
| `api_key` | 注入 API Key header |
| `raw_header` | 注入原始 header |
| `cookie` | 注入 Cookie header |

---

### 2.2 查询存储挂载目录

```http
GET /api/v1/environments/mount-catalog/storage
```

用于查看当前 project 可挂载的 storage volume。

示例：

```bash
curl -sS "$BASE/environments/mount-catalog/storage" \
  -H "X-Api-Key: $API_KEY" | jq
```

---

### 2.3 创建 Environment

```http
POST /api/v1/environments
```

示例：

```bash
curl -sS -X POST "$BASE/environments" \
  -H "X-Api-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "ubuntu24-dev",
    "description": "Ubuntu 24 开发环境",
    "metadata": {"team": "platform"},
    "config": {
      "type": "cloud",
      "packages": {
        "apt": ["git", "curl", "jq"],
        "pip": [],
        "npm": [],
        "cargo": [],
        "gem": [],
        "go": []
      },
      "networking": {
        "type": "limited",
        "allowed_hosts": ["github.com", "api.github.com"],
        "allow_package_managers": true
      },
      "env_vars": {
        "TZ": "Asia/Shanghai"
      },
      "secret_refs": ["claude-secret"],
      "egress_services": [],
      "mount_resources": []
    }
  }' | jq
```

响应示例：

```json
{
  "success": true,
  "code": 201,
  "message": "OK",
  "data": {
    "id": "env_7fd3c991-4707-4909-9259-c245cc2f2222",
    "type": "environment",
    "name": "ubuntu24-dev",
    "description": "Ubuntu 24 开发环境",
    "metadata": {"team": "platform"},
    "config": {
      "type": "cloud",
      "packages": {
        "apt": ["git", "curl", "jq"],
        "pip": [],
        "npm": [],
        "cargo": [],
        "gem": [],
        "go": []
      },
      "networking": {
        "type": "limited",
        "allowed_hosts": ["github.com", "api.github.com"],
        "allow_package_managers": true
      },
      "env_vars": {"TZ": "Asia/Shanghai"},
      "secret_refs": ["claude-secret"],
      "egress_services": [],
      "mount_resources": []
    },
    "image_tag": "...",
    "image_version": 1,
    "created_at": "2026-08-11T10:00:00Z",
    "updated_at": "2026-08-11T10:00:00Z",
    "archived_at": null,
    "deleted_at": null
  }
}
```

说明：创建或更新 `config` 时，会同步构建/校验环境镜像；构建失败则请求失败。

---

### 2.4 查询 Environment 列表

```http
GET /api/v1/environments?limit=20&after_id=<uuid>&include_archived=false
```

示例：

```bash
curl -sS "$BASE/environments?limit=20" \
  -H "X-Api-Key: $API_KEY" | jq
```

---

### 2.5 查询 Environment 详情

```http
GET /api/v1/environments/{env_id}
```

示例：

```bash
ENV_ID="env_7fd3c991-4707-4909-9259-c245cc2f2222"

curl -sS "$BASE/environments/$ENV_ID" \
  -H "X-Api-Key: $API_KEY" | jq
```

---

### 2.6 更新 Environment

```http
POST /api/v1/environments/{env_id}
```

示例：

```bash
curl -sS -X POST "$BASE/environments/$ENV_ID" \
  -H "X-Api-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "description": "增加 nodejs 依赖",
    "config": {
      "type": "cloud",
      "packages": {
        "apt": ["git", "curl", "jq", "nodejs", "npm"],
        "pip": [],
        "npm": ["typescript"],
        "cargo": [],
        "gem": [],
        "go": []
      },
      "networking": {
        "type": "limited",
        "allowed_hosts": ["github.com", "api.github.com", "registry.npmjs.org"],
        "allow_package_managers": true
      },
      "env_vars": {
        "TZ": "Asia/Shanghai"
      },
      "secret_refs": ["claude-secret"],
      "egress_services": [],
      "mount_resources": []
    }
  }' | jq
```

---

### 2.7 删除 Environment

```http
DELETE /api/v1/environments/{env_id}
```

示例：

```bash
curl -sS -X DELETE "$BASE/environments/$ENV_ID" \
  -H "X-Api-Key: $API_KEY" -i
```

成功时 HTTP 204。若 Environment 被 active session 引用，会返回冲突错误。

---

### 2.8 归档 Environment

```http
POST /api/v1/environments/{env_id}/archive
```

示例：

```bash
curl -sS -X POST "$BASE/environments/$ENV_ID/archive" \
  -H "X-Api-Key: $API_KEY" | jq
```

响应：

```json
{
  "success": true,
  "data": {
    "status": "archived"
  }
}
```

---

## 3. Session 接口

Session 是一次或多轮 Agent 对话/执行上下文。一个 Session 绑定一个 Agent，可以持有资源、仓库、存储挂载，并通过 event 驱动 Agent 运行。

### 3.1 Session 数据结构

创建请求：

```json
{
  "agent": "agent_4a8d0d69-3b8b-4ad1-ae3d-0f6d50a1a111",
  "title": "代码分析会话",
  "metadata": {
    "source": "api"
  },
  "vault_ids": [],
  "environment_id": "ubuntu24-dev",
  "resources": [],
  "file_resources": [],
  "repo_resources": [
    {
      "type": "github_repository",
      "url": "https://github.com/example/repo.git",
      "branch": "main",
      "mount_path": "/workspace/repo",
      "mount_name": "repo",
      "authorization_token": null
    }
  ],
  "storage_mounts": []
}
```

Agent 指定方式任选一种，其中第三方系统推荐只用 `agent` 字符串：

```json
{"agent": "agent_4a8d0d69-3b8b-4ad1-ae3d-0f6d50a1a111"}
```

其它兼容写法：

```json
{"agent_id": "4a8d0d69-3b8b-4ad1-ae3d-0f6d50a1a111"}
```

```json
{"agent_name": "claude-code"}
```

```json
{
  "agent": {
    "type": "agent",
    "id": "4a8d0d69-3b8b-4ad1-ae3d-0f6d50a1a111",
    "version": 2
  }
}
```

> 注意：`agent` / `agent_id` / `agent_name` 三类字段虽然在 JSON schema 里都是可选，但创建成功时**必须至少提供一种 Agent 指定方式**。如果一个都不传，会返回 `SESSION_AGENT_NOT_FOUND`。

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `agent` | string/object | 条件必填 | Agent 引用，第三方系统推荐使用；可指定版本 |
| `agent_id` | uuid | 条件必填 | Agent UUID，和 `agent` / `agent_name` 三选一 |
| `agent_name` | string | 条件必填 | Agent 名称，和 `agent` / `agent_id` 三选一 |
| `title` | string | 否 | Session 标题 |
| `metadata` | object | 否 | 元数据 |
| `vault_ids` | array | 否 | 挂载 vault |
| `environment_id` | string | 否 | 覆盖 Agent 默认 environment |
| `resources` | array | 否 | memory store 资源 |
| `file_resources` | array | 否 | 文件资源 |
| `repo_resources` | array | 否 | Git 仓库资源 |
| `storage_mounts` | array | 否 | 存储挂载资源 |

---

### 3.2 创建 Session

```http
POST /api/v1/sessions
```

第三方系统推荐只用 `agent` 字符串：

```bash
SESSION_RESP=$(curl -sS -X POST "$BASE/sessions" \
  -H "X-Api-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "agent": "agent_4a8d0d69-3b8b-4ad1-ae3d-0f6d50a1a111",
    "title": "API 调用测试",
    "metadata": {
      "source": "api",
      "request_id": "req-10001"
    }
  }')

echo "$SESSION_RESP" | jq
SESSION_ID=$(echo "$SESSION_RESP" | jq -r '.data.id')
echo "$SESSION_ID"
```

可选字段：

```json
{
  "environment_id": "env_xxx 或 environment-name",
  "repo_resources": [
    {
      "type": "github_repository",
      "url": "https://github.com/example/repo.git",
      "branch": "main",
      "mount_path": "/workspace/repo",
      "mount_name": "repo"
    }
  ]
}
```

Agent 其它兼容写法：

| 写法 | 是否推荐 | 说明 |
|---|---:|---|
| `{"agent":"agent_xxx"}` | 推荐 | 第三方系统首选 |
| `{"agent_id":"uuid"}` | 可用 | 传纯 UUID |
| `{"agent_name":"claude-code"}` | 可用 | 名称变化会影响调用 |
| `{"agent":{"type":"agent","id":"uuid","version":2}}` | 特殊场景 | 固定 Agent 版本 |


响应示例：

```json
{
  "success": true,
  "code": 201,
  "message": "OK",
  "data": {
    "id": "sess_6d97a573-8efa-4ef5-a32f-6f6d3d333333",
    "type": "session",
    "agent": {
      "type": "agent",
      "id": "agent_4a8d0d69-3b8b-4ad1-ae3d-0f6d50a1a111",
      "version": 1,
      "name": "claude-code",
      "engine_kind": "claude"
    },
    "environment_id": "ubuntu24-dev",
    "status": "idle",
    "stop_reason": null,
    "title": "API 调用测试",
    "metadata": {"source": "api"},
    "vault_ids": [],
    "resources": [],
    "repo_resources": [],
    "storage_mounts": [],
    "usage": {
      "input_tokens": 0,
      "output_tokens": 0,
      "cache_creation_input_tokens": 0,
      "cache_read_input_tokens": 0,
      "by_model": {}
    },
    "stats": {
      "active_seconds": null,
      "duration_seconds": null
    },
    "created_at": "2026-08-11T10:00:00Z",
    "updated_at": "2026-08-11T10:00:00Z",
    "archived_at": null
  }
}
```

---

### 3.3 查询 Session 列表

```http
GET /api/v1/sessions?limit=20&after_id=<uuid>&agent_id=<uuid>&include_archived=false
```

参数：

| 参数 | 类型 | 默认 | 说明 |
|---|---|---:|---|
| `limit` | int | 20 | 每页数量，1-100 |
| `after_id` | uuid | - | 游标分页 |
| `agent_id` | uuid | - | 只查某个 Agent 的 sessions |
| `include_archived` | bool | false | 是否包含归档 session |

示例：

```bash
curl -sS "$BASE/sessions?limit=20" \
  -H "X-Api-Key: $API_KEY" | jq
```

---

### 3.4 查询 Session 详情

```http
GET /api/v1/sessions/{session_id}
```

示例：

```bash
curl -sS "$BASE/sessions/$SESSION_ID" \
  -H "X-Api-Key: $API_KEY" | jq
```

---

### 3.5 向 Session 发送消息并运行 Agent

```http
POST /api/v1/sessions/{session_id}/events
```

发送 `user.message` 会创建 task 并调度 Agent 运行。

示例：

```bash
curl -sS -X POST "$BASE/sessions/$SESSION_ID/events" \
  -H "X-Api-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{
    "type": "user.message",
    "content": "请分析 /workspace/repo 这个项目的架构，并给出核心模块说明。"
  }' | jq
```

响应示例：

```json
{
  "success": true,
  "code": 201,
  "message": "OK",
  "data": {
    "events": [
      {
        "id": "evt_14fd5b39-5c7f-40f0-8b1e-aaaaaaaaaaaa",
        "type": "user.message",
        "seq": 1,
        "content": "请分析 /workspace/repo 这个项目的架构，并给出核心模块说明。",
        "created_at": "2026-08-11T10:00:00Z"
      }
    ]
  }
}
```

注意：

- 同一个 Session 同时只能有一个 active task。
- 如果 Session 状态是 `running`，再次发送 `user.message` 会返回 409。
- 建议每次发送消息都带 `Idempotency-Key`，避免网络重试导致重复任务。

---

### 3.6 批量发送 events

```bash
curl -sS -X POST "$BASE/sessions/$SESSION_ID/events" \
  -H "X-Api-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{
    "events": [
      {
        "type": "user.message",
        "content": "先分析代码结构"
      }
    ]
  }' | jq
```

---

### 3.7 工具审批 / 自定义工具结果

如果 Agent 运行中产生需要人工确认的工具调用，可以通过 event 回传确认结果。

允许：

```bash
curl -sS -X POST "$BASE/sessions/$SESSION_ID/events" \
  -H "X-Api-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "user.custom_tool_result",
    "tool_use_id": "toolu_xxx",
    "approved": true
  }' | jq
```

拒绝：

```bash
curl -sS -X POST "$BASE/sessions/$SESSION_ID/events" \
  -H "X-Api-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "user.custom_tool_result",
    "tool_use_id": "toolu_xxx",
    "approved": false,
    "deny_message": "该命令风险较高，不允许执行"
  }' | jq
```

---

### 3.8 中断运行中的 Session

```http
POST /api/v1/sessions/{session_id}/events
```

发送 `user.interrupt`：

```bash
curl -sS -X POST "$BASE/sessions/$SESSION_ID/events" \
  -H "X-Api-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "user.interrupt",
    "payload": {
      "reason": "用户主动停止"
    }
  }' | jq
```

也可以使用 stop 接口：

```http
POST /api/v1/sessions/{session_id}/stop
```

```bash
curl -sS -X POST "$BASE/sessions/$SESSION_ID/stop" \
  -H "X-Api-Key: $API_KEY" | jq
```

---

### 3.9 查询 Session Events

```http
GET /api/v1/sessions/{session_id}/events?limit=50&after_seq=<seq>&before_seq=<seq>&order=asc
```

参数：

| 参数 | 类型 | 默认 | 说明 |
|---|---|---:|---|
| `limit` | int | 50 | 每页数量，1-200 |
| `after_seq` | int | - | 查询 seq 大于该值的事件 |
| `before_seq` | int | - | 查询 seq 小于该值的事件 |
| `order` | string | `asc` | `asc` / `desc` |

`after_seq` 和 `before_seq` 不能同时传。

示例：

```bash
curl -sS "$BASE/sessions/$SESSION_ID/events?limit=50&order=asc" \
  -H "X-Api-Key: $API_KEY" | jq
```

加载最新 50 条：

```bash
curl -sS "$BASE/sessions/$SESSION_ID/events?limit=50&order=desc" \
  -H "X-Api-Key: $API_KEY" | jq
```

增量加载：

```bash
curl -sS "$BASE/sessions/$SESSION_ID/events?after_seq=120&limit=100&order=asc" \
  -H "X-Api-Key: $API_KEY" | jq
```

---

### 3.10 SSE 流式订阅 Session Events

```http
GET /api/v1/sessions/{session_id}/events/stream?after_seq=<seq>
```

示例：

```bash
curl -N "$BASE/sessions/$SESSION_ID/events/stream?after_seq=0" \
  -H "X-Api-Key: $API_KEY"
```

返回示例：

```text
id: evt_14fd5b39-5c7f-40f0-8b1e-aaaaaaaaaaaa
data: {"id":"evt_14fd5b39-5c7f-40f0-8b1e-aaaaaaaaaaaa","type":"user.message","seq":1,"content":"..."}

id: evt_2d4b6d82-c1a9-45fa-b7e4-bbbbbbbbbbbb
data: {"id":"evt_2d4b6d82-c1a9-45fa-b7e4-bbbbbbbbbbbb","type":"agent.message","seq":2,"content":[{"type":"text","text":"Agent 输出内容"}]}
```

断线重连时，客户端保存最后收到的 `seq`，然后：

```bash
curl -N "$BASE/sessions/$SESSION_ID/events/stream?after_seq=$LAST_SEQ" \
  -H "X-Api-Key: $API_KEY"
```

---

### 3.11 查询 Session 资源

```http
GET /api/v1/sessions/{session_id}/resources
```

示例：

```bash
curl -sS "$BASE/sessions/$SESSION_ID/resources" \
  -H "X-Api-Key: $API_KEY" | jq
```

---

### 3.12 添加 Session 资源

```http
POST /api/v1/sessions/{session_id}/resources
```

#### 添加文件资源

```bash
curl -sS -X POST "$BASE/sessions/$SESSION_ID/resources" \
  -H "X-Api-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "file",
    "file_id": "file_aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "mount_path": "/workspace/input/config.yaml"
  }' | jq
```

#### 添加 Git 仓库资源

```bash
curl -sS -X POST "$BASE/sessions/$SESSION_ID/resources" \
  -H "X-Api-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "github_repository",
    "url": "https://github.com/example/repo.git",
    "branch": "main",
    "mount_path": "/workspace/repo",
    "mount_name": "repo",
    "authorization_token": null
  }' | jq
```

---

### 3.13 删除 Session 资源

```http
DELETE /api/v1/sessions/{session_id}/resources/{resource_id}
```

示例：

```bash
RESOURCE_ID="sesrsc_xxx"

curl -sS -X DELETE "$BASE/sessions/$SESSION_ID/resources/$RESOURCE_ID" \
  -H "X-Api-Key: $API_KEY" | jq
```

---

### 3.14 更新 Git 资源 token

```http
PATCH /api/v1/sessions/{session_id}/resources/{resource_id}
```

仅用于更新 `github_repository` 资源的 `authorization_token`。

示例：

```bash
curl -sS -X PATCH "$BASE/sessions/$SESSION_ID/resources/$RESOURCE_ID" \
  -H "X-Api-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "authorization_token": "ghp_xxx"
  }' | jq
```

响应不会回显 token。

---

### 3.15 查询 Session 沙箱文件

这些接口用于查看运行后 sandbox 内的文件。

#### 列出文件

```http
GET /api/v1/sessions/{session_id}/sandbox/files?path=/workspace
```

```bash
curl -sS "$BASE/sessions/$SESSION_ID/sandbox/files?path=/workspace" \
  -H "X-Api-Key: $API_KEY" | jq
```

#### 查看文本内容

```http
GET /api/v1/sessions/{session_id}/sandbox/files/content?path=/workspace/README.md
```

```bash
curl -sS "$BASE/sessions/$SESSION_ID/sandbox/files/content?path=/workspace/README.md" \
  -H "X-Api-Key: $API_KEY" | jq
```

#### 下载原始文件

```http
GET /api/v1/sessions/{session_id}/sandbox/files/raw?path=/workspace/result.txt
```

```bash
curl -L "$BASE/sessions/$SESSION_ID/sandbox/files/raw?path=/workspace/result.txt" \
  -H "X-Api-Key: $API_KEY" \
  -o result.txt
```

#### 下载目录归档

```http
GET /api/v1/sessions/{session_id}/sandbox/files/archive?path=/workspace
```

```bash
curl -L "$BASE/sessions/$SESSION_ID/sandbox/files/archive?path=/workspace" \
  -H "X-Api-Key: $API_KEY" \
  -o workspace.tar.gz
```

---

### 3.16 归档 Session

```http
POST /api/v1/sessions/{session_id}/archive
```

示例：

```bash
curl -sS -X POST "$BASE/sessions/$SESSION_ID/archive" \
  -H "X-Api-Key: $API_KEY" | jq
```

---

### 3.17 删除 Session

```http
DELETE /api/v1/sessions/{session_id}
```

示例：

```bash
curl -sS -X DELETE "$BASE/sessions/$SESSION_ID" \
  -H "X-Api-Key: $API_KEY" | jq
```

限制：

- running 状态不能直接删除，需先 interrupt/stop。
- 存在 active task 时不能删除。

---

## 4. 第三方系统完整调用示例

第三方系统通常不需要每次创建 Environment / Agent。推荐提前在 JoySafeter 中配置好 Agent，然后第三方只调用 Session。

```bash
#!/usr/bin/env bash
set -euo pipefail

BASE="http://<joysafeter-api-host>/api/v1"
API_KEY="<your-api-key>"
AGENT_ID="agent_4a8d0d69-3b8b-4ad1-ae3d-0f6d50a1a111"
REQUEST_ID="req-10001"

# 1. 创建 Session
SESSION_ID=$(curl -sS -X POST "$BASE/sessions" \
  -H "X-Api-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"agent\": \"$AGENT_ID\",
    \"title\": \"third-party-run-$REQUEST_ID\",
    \"metadata\": {
      \"source\": \"third-party\",
      \"request_id\": \"$REQUEST_ID\"
    }
  }" | jq -r '.data.id')

echo "SESSION_ID=$SESSION_ID"

# 2. 发送消息触发 Agent
curl -sS -X POST "$BASE/sessions/$SESSION_ID/events" \
  -H "X-Api-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $REQUEST_ID" \
  -d '{
    "type": "user.message",
    "content": "请分析这个需求，并输出实现方案。"
  }' | jq

# 3. 流式接收结果
curl -N "$BASE/sessions/$SESSION_ID/events/stream?after_seq=0" \
  -H "X-Api-Key: $API_KEY"
```

如果不能使用 SSE，就轮询 events：

```bash
LAST_SEQ=0
curl -sS "$BASE/sessions/$SESSION_ID/events?after_seq=$LAST_SEQ&limit=100&order=asc" \
  -H "X-Api-Key: $API_KEY" | jq
```

---

## 5. Python 脚本示例

仓库中提供了两个第三方系统调用示例脚本：

| 脚本 | 获取结果方式 | 适用场景 |
|---|---|---|
| `docs/examples/joysafeter_run_agent_sse.py` | SSE 流式 | 推荐，适合支持长连接的系统 |
| `docs/examples/joysafeter_run_agent_polling.py` | HTTP 轮询 | 适合不能使用 SSE 的系统 |

两个脚本的流程都是：

```text
1. 创建 Session
2. 发送 user.message 触发 Agent
3. 获取 agent.message 输出
4. 收到 session.status_idle 后结束
```

### 5.1 使用 SSE 流式脚本

安装依赖：

```bash
pip install requests
```

设置环境变量：

```bash
export JOYSAFETER_BASE="http://<joysafeter-api-host>/api/v1"
export JOYSAFETER_API_KEY="<your-api-key>"
export JOYSAFETER_AGENT_ID="agent_xxx"
```

运行：

```bash
python docs/examples/joysafeter_run_agent_sse.py "请分析这个需求，并给出实现方案。"
```

这个脚本会请求：

```http
GET /api/v1/sessions/{session_id}/events/stream?after_seq=0
```

默认情况下脚本只把 `agent.message` 正文打印到 stdout，文本字段来自 `content[].text`；`request_id/session_id/last_seq` 等日志打印到 stderr。收到 `session.status_idle` 后退出。

如果需要查看每个事件、工具调用日志，打开：

```bash
export JOYSAFETER_VERBOSE_EVENTS=1
```

如果看到 `agent.message` 事件但没有打印正文，可以临时打开调试：

```bash
export JOYSAFETER_DEBUG_EVENTS=1
```

### 5.2 使用轮询脚本

安装依赖：

```bash
pip install requests
```

设置环境变量：

```bash
export JOYSAFETER_BASE="http://<joysafeter-api-host>/api/v1"
export JOYSAFETER_API_KEY="<your-api-key>"
export JOYSAFETER_AGENT_ID="agent_xxx"
```

运行：

```bash
python docs/examples/joysafeter_run_agent_polling.py "请分析这个需求，并给出实现方案。"
```

这个脚本会循环请求：

```http
GET /api/v1/sessions/{session_id}/events?after_seq=<last_seq>&limit=100&order=asc
```

默认每 2 秒轮询一次，可以通过环境变量调整：

```bash
export JOYSAFETER_POLL_INTERVAL_SEC=2
export JOYSAFETER_RUN_TIMEOUT_SEC=600
# 查看每个事件/工具调用日志
export JOYSAFETER_VERBOSE_EVENTS=1
# 如果看到 agent.message 但没有打印正文，用它查看原始事件
export JOYSAFETER_DEBUG_EVENTS=1
```

### 5.3 两种脚本如何选择

| 场景 | 推荐脚本 |
|---|---|
| 需要实时输出 | `joysafeter_run_agent_sse.py` |
| Web 后端、网关支持长连接 | `joysafeter_run_agent_sse.py` |
| 第三方系统只能发普通 HTTP 请求 | `joysafeter_run_agent_polling.py` |
| 对实时性要求不高 | `joysafeter_run_agent_polling.py` |

---

## 6. 常见状态和事件

### 6.1 Session 状态

| 状态 | 说明 |
|---|---|
| `idle` | 空闲，可发送新 `user.message` |
| `running` | Agent 正在运行 |
| `rescheduling` | 正在重新调度 |
| `terminated` | 已终止 |

### 6.2 常见 Event 类型

| Event 类型 | 方向 | 说明 |
|---|---|---|
| `user.message` | client -> server | 用户消息，触发 task |
| `user.interrupt` | client -> server | 中断当前运行 |
| `user.custom_tool_result` | client -> server | 工具审批/工具结果 |
| `session.status_running` | server -> client | session 进入 running |
| `session.status_idle` | server -> client | session 回到 idle，本轮结束 |
| `session.status_rescheduling` | server -> client | 正在重调度 runner/sandbox |
| `session.status_rescheduled` | server -> client | 已完成重调度 |
| `session.status_terminated` | server -> client | session 已终止 |
| `session.error` | server -> client | 运行失败，错误信息在 `error.message` |
| `agent.message` | server -> client | Agent 输出消息，第三方主要读取这个事件；文本在 `content[].text` |
| `agent.thinking` | server -> client | Agent 思考中 |
| `agent.tool_use` | server -> client | 普通工具调用，工具名在 `name`，参数在 `input` |
| `agent.mcp_tool_use` | server -> client | MCP 工具调用 |
| `agent.custom_tool_use` | server -> client | 自定义/HITL 工具调用，可能需要第三方回传结果 |
| `agent.tool_result` | server -> client | 普通工具结果 |
| `agent.mcp_tool_result` | server -> client | MCP 工具结果 |
| `span.model_request_start` | server -> client | 模型请求开始 |
| `span.model_request_end` | server -> client | 模型请求结束，token 用量在 `usage` |
| `agent.bg_task_started` | server -> client | 后台子任务开始 |
| `agent.bg_task_progress` | server -> client | 后台子任务进度 |
| `agent.bg_task_finished` | server -> client | 后台子任务结束 |

---

## 7. 推荐前端/调用方实践

1. **列表页**：调用 `GET /agents`、`GET /environments`、`GET /sessions`。
2. **详情页**：调用 `GET /sessions/{id}` + `GET /sessions/{id}/events?order=desc&limit=50` 加载最新事件。
3. **实时输出**：连接 `GET /sessions/{id}/events/stream?after_seq=<last_seq>`。
4. **断线重连**：保存最后收到的 `seq`，重连时用 `after_seq` 续接。
5. **发消息**：`POST /sessions/{id}/events`，带 `Idempotency-Key`。
6. **并发控制**：同一个 session 只允许一个 running task，发送下一条消息前应等待 session 回到 `idle`。
7. **外部系统一次性任务**：如果不需要手动管理 session，也可以直接用 `POST /api/v1/tasks`，后端会自动创建 session。
