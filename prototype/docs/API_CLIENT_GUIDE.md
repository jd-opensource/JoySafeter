# 统一 API 客户端指南

## 概述

所有前端 API 请求都应使用 `@/lib/api-client` 中的统一方法，确保：
- 统一的 URL 构建规则（所有端点都在 `/api/v1` 下）
- 统一的 CSRF Token 处理
- 统一的 401 自动刷新
- 统一的错误处理

## 基本使用

```ts
import { apiGet, apiPost, apiPut, apiDelete, apiPatch } from '@/lib/api-client'

// GET 请求
const users = await apiGet<User[]>('users')

// POST 请求
const user = await apiPost<User>('users', { name: 'John' })

// PUT 请求
await apiPut('users/123', { name: 'John Updated' })

// DELETE 请求
await apiDelete('users/123')

// PATCH 请求
await apiPatch('users/123', { name: 'John Updated' })
```

## URL 规则

**相对路径**会自动添加 `/api/v1` 前缀：

| 调用 | 实际请求 URL |
|------|-------------|
| `apiGet('users')` | `/api/v1/users` |
| `apiGet('graphs/123')` | `/api/v1/graphs/123` |
| `apiPost('auth/login', {...})` | `/api/v1/auth/login` |

## 流式请求 (SSE)

使用 `apiStream` 处理 Server-Sent Events：

```ts
import { apiStream } from '@/lib/api-client'

const response = await apiStream('chat/stream', { message: 'Hello' })
const reader = response.body?.getReader()

// 处理流式数据
while (true) {
  const { value, done } = await reader.read()
  if (done) break
  // 处理 value...
}
```

## 认证相关

认证相关的 API 使用 `@/lib/auth` 模块：

```ts
import { signIn, signOut, authApi } from '@/lib/auth'

// 登录
const result = await signIn.email({ email, password })

// 登出
await signOut()

// 获取当前会话
const session = await authApi.getSession()
```

### CSRF Token 管理

CSRF Token 由 `@/lib/auth/csrf` 模块集中管理：

```ts
import { setCsrfToken, getCsrfToken, clearCsrfToken } from '@/lib/auth/csrf'

// 登录成功后自动设置
// 登出时自动清除
// API 请求自动携带
```

## 错误处理

所有 API 错误都会抛出 `ApiError`：

```ts
import { apiGet, ApiError } from '@/lib/api-client'

try {
  const data = await apiGet('some-endpoint')
} catch (error) {
  if (error instanceof ApiError) {
    console.log(error.status)     // HTTP 状态码
    console.log(error.statusText) // 状态文本
    console.log(error.detail)     // 详细错误信息
  }
}
```

## 文件上传

```ts
import { apiUpload } from '@/lib/api-client'

const file = new File(['content'], 'test.txt')
const result = await apiUpload<UploadResult>('upload', file)
```

## 架构说明

```
@/lib/api-client.ts       - 统一 API 客户端（核心）
@/lib/auth/csrf.ts        - CSRF Token 管理（独立模块）
@/lib/auth/api-client.ts  - 认证 API（使用统一客户端）
@/lib/auth/auth-client.ts - React 集成（useSession hook）
@/lib/auth/index.ts       - 统一导出
```

## 迁移指南

### 从旧代码迁移

旧代码：
```ts
// ❌ 直接使用 fetch
const response = await fetch('/api/v1/users')

// ❌ 使用废弃的 apiClient
import { api } from './services/apiClient'
const data = await api.get('/v1/users')
```

新代码：
```ts
// ✅ 使用统一 API 客户端
import { apiGet } from '@/lib/api-client'
const data = await apiGet('users')
```
