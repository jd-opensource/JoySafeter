# JoySafeter Graph OpenAPI

通过 API Token 远程触发 Graph 执行，查询状态，中止运行，获取结果。

---

## 认证

所有 OpenAPI 端点使用 API Key 认证（通过工作空间设置页面生成）：

```
Authorization: Bearer YOUR_API_KEY
```

API Key 分两种类型：
- **personal** — 个人 key，可访问个人 Graph
- **workspace** — 工作空间 key，只能访问该工作空间下的 Graph

---

## 端点

### POST /api/v1/openapi/graph/{graphId}/run

**启动 Graph 执行**

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|------|------|
| graphId | path | UUID | 是 | Graph ID |
| variables | body | object | 否 | 运行时变量（`message` 或 `query` 作为用户消息，其余作为 context） |

**请求示例**

```bash
curl -X POST https://your-domain/api/v1/openapi/graph/{graphId}/run \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"variables": {"message": "分析这个APK", "apk_url": "https://example.com/app.apk"}}'
```

**响应**

```json
{
  "success": true,
  "data": {
    "executionId": "550e8400-e29b-41d4-a716-446655440000",
    "status": "init"
  }
}
```

---

### GET /api/v1/openapi/graph/{executionId}/status

**查询执行状态**

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|------|------|
| executionId | path | UUID | 是 | 执行 ID |

**请求示例**

```bash
curl https://your-domain/api/v1/openapi/graph/{executionId}/status \
  -H "Authorization: Bearer YOUR_API_KEY"
```

**响应**

```json
{
  "success": true,
  "data": {
    "executionId": "550e8400-e29b-41d4-a716-446655440000",
    "status": "executing",
    "startedAt": "2026-03-10T12:00:00+00:00",
    "finishedAt": null,
    "errorMessage": null
  }
}
```

**状态枚举**

| 状态 | 说明 |
|------|------|
| `init` | 初始化中 |
| `executing` | 执行中 |
| `finish` | 执行完成 |
| `failed` | 执行失败或被中止 |

---

### POST /api/v1/openapi/graph/{executionId}/abort

**中止执行**

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|------|------|
| executionId | path | UUID | 是 | 执行 ID |

**请求示例**

```bash
curl -X POST https://your-domain/api/v1/openapi/graph/{executionId}/abort \
  -H "Authorization: Bearer YOUR_API_KEY"
```

**响应**

```json
{
  "success": true,
  "data": {
    "executionId": "550e8400-e29b-41d4-a716-446655440000",
    "status": "failed"
  }
}
```

---

### GET /api/v1/openapi/graph/{executionId}/result

**获取执行结果**

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|------|------|
| executionId | path | UUID | 是 | 执行 ID |

**请求示例**

```bash
curl https://your-domain/api/v1/openapi/graph/{executionId}/result \
  -H "Authorization: Bearer YOUR_API_KEY"
```

**响应（完成状态）**

```json
{
  "success": true,
  "data": {
    "executionId": "550e8400-e29b-41d4-a716-446655440000",
    "status": "finish",
    "output": {
      "content": "分析结果：该APK安全风险等级为低...",
      "tool_calls": [
        {"name": "apk_analyzer", "args": {"url": "https://example.com/app.apk"}}
      ]
    },
    "errorMessage": null,
    "startedAt": "2026-03-10T12:00:00+00:00",
    "finishedAt": "2026-03-10T12:01:30+00:00"
  }
}
```

---

## 错误响应

```json
{
  "detail": "Graph not found"
}
```

| HTTP 状态码 | 说明 |
|-------------|------|
| 401 | API Key 缺失、无效或过期 |
| 403 | 权限不足（Graph 不属于工作空间） |
| 404 | Graph 或执行记录不存在 |
| 400 | 请求参数错误（如中止非运行状态的执行） |
| 500 | 服务器内部错误 |

---

## API Key 管理

通过工作空间设置页面创建 API Key，或使用以下接口：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/v1/api-keys?workspaceId={id} | 列出 API Key |
| POST | /api/v1/api-keys | 创建 API Key |
| DELETE | /api/v1/api-keys/{keyId} | 删除 API Key |

**创建 Workspace API Key 示例**

```bash
curl -X POST https://your-domain/api/v1/api-keys \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "Production Key", "type": "workspace", "workspaceId": "your-workspace-id"}'
```
