# JoySafeter 渠道接入（Channel Integration）完整设计方案

## 1. 概述

渠道接入功能允许用户将企业即时通讯平台（企微 AIBot、飞书、钉钉、QQ 机器人）的 Bot 绑定到一个 JoySafeter Session。IM 用户发送的消息通过 Webhook 进入 JoySafeter，经 Agent 处理后自动回复到 IM 渠道。

### 核心概念

- **Channel（渠道）**：一条 Bot ↔ Session 的绑定关系
- **入方向**：IM 平台 Webhook → JoySafeter API → 创建 Task
- **出方向**：Session Event（agent.message）→ 平台 API → 回复消息

---

## 2. 系统架构

```
                          ┌─────────────────────────────────┐
                          │  企微 / 飞书 / 钉钉 / QQ         │
                          │  (配置回调 URL → JoySafeter)     │
                          └────────────┬────────────────────┘
                                       │
              ┌────────────────────────┼────────────────────────┐
              │                        │                        │
              │  收到用户消息            │  验证 Webhook URL       │
              │  POST callback_body     │  GET ?echostr=xxx      │
              ▼                        ▼                        │
┌─────────────────────────────────────────────────────────────────────┐
│  JoySafeter API Service                                             │
│                                                                     │
│  /api/v1/channels/webhook/{channel_id}                              │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                    Webhook Endpoint (无认证)                    │  │
│  │                                                               │  │
│  │  1. 根据 channel_id 查询 joysafeter_channels 表                │  │
│  │  2. 获取 channel.provider + 加密配置 (token/aes_key)           │  │
│  │  3. 委派给对应的 Platform Adapter 解密验签                      │  │
│  └───────────────────────┬───────────────────────────────────────┘  │
│                          │                                          │
│  ┌───────────────────────▼───────────────────────────────────────┐  │
│  │              Platform Adapters (策略模式)                       │  │
│  │                                                               │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐     │  │
│  │  │  WeCom   │  │  Feishu  │  │ DingTalk │  │    QQ    │     │  │
│  │  │ Adapter  │  │ Adapter  │  │ Adapter  │  │ Adapter  │     │  │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘     │  │
│  │                                                               │  │
│  │  职责：                                                        │  │
│  │  • verify_webhook() — URL 验证回调 (echostr)                   │  │
│  │  • parse_message() — 解密/解析消息体，提取文本+发送者            │  │
│  │  • reply_message() — 调用平台 API 发送回复                     │  │
│  └───────────────────────┬───────────────────────────────────────┘  │
│                          │                                          │
│  ┌───────────────────────▼───────────────────────────────────────┐  │
│  │              Channel Service (业务逻辑层)                       │  │
│  │                                                               │  │
│  │  handle_incoming_message():                                    │  │
│  │    1. 解析消息 → MessagePayload { text, sender_id, msg_id }   │  │
│  │    2. 去重 (msg_id 幂等检查)                                   │  │
│  │    3. 创建 Task:                                              │  │
│  │       - agent_id = channel.agent_id                           │  │
│  │       - chat_session_id = channel.session_id                  │  │
│  │       - prompt = message.text                                 │  │
│  │    4. 返回 task_id                                            │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │              Channel CRUD API (需认证)                          │  │
│  │                                                               │  │
│  │  POST   /api/v1/channels          创建渠道                     │  │
│  │  GET    /api/v1/channels          列表                         │  │
│  │  GET    /api/v1/channels/{id}     详情                         │  │
│  │  PATCH  /api/v1/channels/{id}     更新绑定/配置                 │  │
│  │  DELETE /api/v1/channels/{id}     删除渠道                     │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
              │                                            ▲
              │ 创建 Task                                   │ 读 Channel 配置
              ▼                                            │
┌─────────────────────────────────────────────────────────────────────┐
│  Orchestrator-rs → Sandbox → Agent 执行                              │
│                                                                      │
│  Task prompt = IM 消息文本                                            │
│  Session = 绑定的长期 Session (保留上下文)                              │
│                                                                      │
│  执行完成 → 发布 session_event:                                       │
│    event_type: "agent.message"                                       │
│    payload: { content: "回复内容", task_id: "..." }                    │
└───────────────────────────┬──────────────────────────────────────────┘
                            │ Redis pub/sub: joysafeter:session_events:{session_id}
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Channel Reply Worker (新增后台任务，运行在 Worker 进程)               │
│                                                                      │
│  ┌───────────────────────────────────────────────────────────────┐   │
│  │  SessionReplySubscriber                                       │   │
│  │                                                               │   │
│  │  启动时：                                                      │   │
│  │    1. 查询所有 enabled channel，收集 session_id 列表            │   │
│  │    2. 订阅 Redis pub/sub: joysafeter:session_events:{sid}     │   │
│  │                                                               │   │
│  │  收到 event：                                                  │   │
│  │    1. 过滤 event_type == "agent.message"                      │   │
│  │    2. 查询 channel (by session_id) → 获取 adapter + 凭据      │   │
│  │    3. adapter.reply_message(content) → 调用平台 API             │   │
│  │    4. 记录 delivery log                                        │   │
│  │                                                               │   │
│  │  动态刷新：                                                    │   │
│  │    监听 Redis channel "joysafeter:channel_config_changed"      │   │
│  │    → 重新加载 channel 列表，更新订阅                             │   │
│  └───────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. 数据模型

### 3.1 `joysafeter_channels` 表

```sql
CREATE TABLE joysafeter_channels (
    -- 主键 (UUID v7)
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- 所属项目
    project_id      VARCHAR(255) NOT NULL REFERENCES joysafeter_organization_projects(id),

    -- 渠道名称 (用户自定义，如 "客服Bot-企微")
    name            VARCHAR(255) NOT NULL,

    -- 平台类型: wecom | feishu | dingtalk | qq
    provider        VARCHAR(50) NOT NULL,

    -- 绑定的 Session (消息路由目标)
    session_id      UUID NOT NULL REFERENCES joysafeter_sessions(id),

    -- 绑定的 Agent (用于创建 Task)
    agent_id        UUID NOT NULL REFERENCES joysafeter_agents(id),

    -- 平台配置 (加密存储，结构因 provider 而异)
    -- wecom:    { "token": "...", "encoding_aes_key": "...", "corp_id": "...", "agent_id": "..." }
    -- feishu:   { "app_id": "...", "app_secret": "...", "verification_token": "...", "encrypt_key": "..." }
    -- dingtalk: { "app_key": "...", "app_secret": "...", "sign_token": "..." }
    -- qq:       { "app_id": "...", "token": "...", "app_secret": "..." }
    credentials     TEXT NOT NULL,  -- AES-256-GCM 加密 JSON (复用 VaultCipher)

    -- Webhook URL 中的唯一标识 (channel_id 本身或短 hash)
    webhook_secret  VARCHAR(64) NOT NULL UNIQUE,

    -- 启用/禁用
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,

    -- 时间戳
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- 索引
    CONSTRAINT uq_channel_project_name UNIQUE (project_id, name)
);

CREATE INDEX idx_channels_project ON joysafeter_channels(project_id);
CREATE INDEX idx_channels_session ON joysafeter_channels(session_id);
CREATE INDEX idx_channels_webhook_secret ON joysafeter_channels(webhook_secret);
```

### 3.2 `joysafeter_channel_messages` 表（消息日志/去重）

```sql
CREATE TABLE joysafeter_channel_messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    channel_id      UUID NOT NULL REFERENCES joysafeter_channels(id) ON DELETE CASCADE,

    -- 方向: inbound (IM→JoySafeter) | outbound (JoySafeter→IM)
    direction       VARCHAR(10) NOT NULL,

    -- 平台原始消息 ID (用于幂等去重)
    platform_msg_id VARCHAR(255),

    -- 发送者标识 (IM 用户 ID)
    sender_id       VARCHAR(255),

    -- 消息内容
    content         TEXT,

    -- 关联的 Task ID (inbound 消息创建的 task)
    task_id         UUID,

    -- 投递状态: pending | delivered | failed
    delivery_status VARCHAR(20) NOT NULL DEFAULT 'delivered',
    delivery_error  TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- 幂等约束: 同一个 channel + 同一条平台消息只处理一次
    CONSTRAINT uq_channel_platform_msg UNIQUE (channel_id, platform_msg_id)
);

CREATE INDEX idx_channel_msgs_channel ON joysafeter_channel_messages(channel_id, created_at DESC);
```

---

## 4. API 设计

### 4.1 管理接口（需认证，项目级权限）

| 方法 | 路径 | 描述 |
|------|------|------|
| `POST` | `/api/v1/channels` | 创建渠道 |
| `GET` | `/api/v1/channels` | 列表（分页） |
| `GET` | `/api/v1/channels/{channel_id}` | 详情 |
| `PATCH` | `/api/v1/channels/{channel_id}` | 更新 |
| `DELETE` | `/api/v1/channels/{channel_id}` | 删除 |
| `GET` | `/api/v1/channels/{channel_id}/messages` | 消息日志 |

#### 创建渠道 Request

```json
POST /api/v1/channels
{
  "name": "客服助手-企微",
  "provider": "wecom",
  "session_id": "sess_01abc...",
  "agent_id": "agent_01xyz...",
  "credentials": {
    "token": "xxxxxxx",
    "encoding_aes_key": "yyyyyyy",
    "corp_id": "ww12345678"
  }
}
```

#### 创建渠道 Response

```json
{
  "id": "chan_01def...",
  "name": "客服助手-企微",
  "provider": "wecom",
  "session_id": "sess_01abc...",
  "agent_id": "agent_01xyz...",
  "enabled": true,
  "webhook_url": "https://your-domain.com/api/v1/channels/webhook/a8f3k2m9",
  "created_at": "2026-07-20T10:00:00Z"
}
```

### 4.2 Webhook 接口（无认证，平台回调）

| 方法 | 路径 | 描述 |
|------|------|------|
| `GET` | `/api/v1/channels/webhook/{webhook_secret}` | URL 验证（企微/飞书的 echostr 机制） |
| `POST` | `/api/v1/channels/webhook/{webhook_secret}` | 接收消息 |

Webhook endpoint **不走 JoySafeter 认证中间件**（平台回调不携带 JWT），安全性通过平台自身的签名验证机制保证。

---

## 5. Platform Adapter 接口设计

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from fastapi import Request, Response


@dataclass
class IncomingMessage:
    """从 IM 平台解析出的标准化消息"""
    text: str                      # 消息文本内容
    sender_id: str                 # 发送者在平台的 ID
    platform_msg_id: str           # 平台消息唯一 ID (用于幂等)
    msg_type: str = "text"         # text / image / file (v1 只处理 text)
    sender_name: Optional[str] = None
    raw: Optional[dict] = None     # 原始数据，用于调试


@dataclass
class ChannelCredentials:
    """解密后的平台凭据"""
    data: dict  # provider-specific fields


class PlatformAdapter(ABC):
    """IM 平台适配器抽象基类"""

    @abstractmethod
    async def verify_webhook(
        self, request: Request, credentials: ChannelCredentials
    ) -> Response:
        """处理平台 URL 验证回调 (GET echostr / challenge)"""
        ...

    @abstractmethod
    async def parse_message(
        self, request: Request, credentials: ChannelCredentials
    ) -> Optional[IncomingMessage]:
        """
        解密并解析收到的回调消息体。
        返回 None 表示非文本消息或非需要处理的事件（如 event 通知）。
        """
        ...

    @abstractmethod
    async def reply_message(
        self, credentials: ChannelCredentials, sender_id: str, content: str
    ) -> bool:
        """调用平台 API 主动发送消息给指定用户。返回是否成功。"""
        ...
```

### 各平台适配器实现要点

| 平台 | 验签方式 | 消息加密 | 回复方式 |
|------|---------|---------|---------|
| **企微 AIBot** | SHA1(token + timestamp + nonce + ciphertext) | AES-256-CBC (EncodingAESKey) | 企微 API `POST /cgi-bin/message/send` |
| **飞书** | HMAC-SHA256(timestamp + nonce, encrypt_key) | AES-256-CBC (encrypt_key) | 飞书 API `POST /open-apis/im/v1/messages` |
| **钉钉** | HMAC-SHA256(timestamp + "\n" + app_secret) | 无加密（HTTPS 足够） | 钉钉 API `POST /v1.0/robot/oToMessages/batchSend` |
| **QQ 机器人** | Ed25519 签名验证 | 无 | QQ API `POST /channels/{channel_id}/messages` |

---

## 6. 消息入方向流程（详细）

```
IM 平台 POST → /api/v1/channels/webhook/{webhook_secret}
│
├─ Step 1: 根据 webhook_secret 查 joysafeter_channels 表
│   └─ 未找到 → 404 (不泄露信息)
│   └─ found but enabled=false → 200 OK (静默丢弃)
│
├─ Step 2: 解密 credentials → ChannelCredentials
│
├─ Step 3: adapter.parse_message(request, credentials)
│   └─ 返回 None (非文本/非消息事件) → 200 OK
│   └─ 签名验证失败 → 403
│   └─ 解析成功 → IncomingMessage
│
├─ Step 4: 幂等检查
│   └─ SELECT 1 FROM joysafeter_channel_messages
│        WHERE channel_id=$1 AND platform_msg_id=$2
│   └─ 已存在 → 200 OK (跳过)
│
├─ Step 5: 创建 Task (内部复用 TaskService)
│   task = await TaskService(db).create_task(
│       agent_id = channel.agent_id,
│       chat_session_id = channel.session_id,
│       prompt = message.text,
│       project_id = channel.project_id,
│       timeout_sec = 300,
│       idempotency_key = f"chan:{channel.id}:{message.platform_msg_id}",
│   )
│
├─ Step 6: 记录 inbound message log
│   INSERT INTO joysafeter_channel_messages (
│     channel_id, direction='inbound', platform_msg_id,
│     sender_id, content, task_id
│   )
│
└─ Step 7: 返回 200 OK (平台要求快速响应，不等 Agent 执行完)
```

---

## 7. 消息出方向流程（Reply Worker）

```
SessionReplySubscriber (Worker 进程启动时初始化)
│
├─ 启动:
│   1. SELECT id, session_id, provider, credentials
│      FROM joysafeter_channels WHERE enabled = true
│   2. 对每个 session_id 订阅 Redis:
│      SUBSCRIBE joysafeter:session_events:{session_id}
│
├─ 收到 Redis 消息:
│   event = json.loads(message)
│   │
│   ├─ event_type != "agent.message" → 跳过
│   │
│   ├─ 提取 content = event.payload.content
│   │   (agent.message 的 payload 中包含 Agent 回复文本)
│   │
│   ├─ 查找该 session_id 绑定的所有 enabled channels
│   │
│   └─ 对每个 channel:
│       1. 解密 credentials
│       2. adapter = get_adapter(channel.provider)
│       3. 确定 sender_id:
│          - 从最近的 inbound message 获取 sender_id
│          - 或从 task → channel_message 反查
│       4. success = await adapter.reply_message(creds, sender_id, content)
│       5. INSERT INTO joysafeter_channel_messages (
│            channel_id, direction='outbound', content,
│            delivery_status='delivered'/'failed',
│            task_id=event.payload.task_id
│          )
│
├─ 动态刷新 (渠道增删改时):
│   API 层 create/update/delete channel 后 →
│   PUBLISH joysafeter:channel_config_changed {action, channel_id}
│   Worker 收到后重新加载 channel 列表，调整订阅
│
└─ 容错:
    - reply 失败 → 记录 delivery_error，3 次指数退避重试
    - Redis 断连 → 自动重连 + 从 DB 重放未投递的 outbound events
```

---

## 8. 安全设计

### 8.1 凭据存储
- 复用现有 `VaultCipher` (AES-256-GCM)，同 Secret 管理模块
- `credentials` 字段存密文，API 返回时 **永不** 返回原始凭据
- GET 接口只返回 `credentials_configured: true/false` + 部分脱敏字段

### 8.2 Webhook 安全
- 每个 channel 生成独立的 `webhook_secret`（32 字符随机 URL-safe token）
- 平台消息签名验证（每个 Adapter 实现各平台的验签逻辑）
- Webhook endpoint 设置独立的 rate limit（per webhook_secret 100 req/min）

### 8.3 权限模型
- 管理接口复用项目权限：创建/更新/删除需要 `write`，查看需要 `read`
- Webhook 回调无鉴权（依赖平台签名 + webhook_secret 不可猜测性）

---

## 9. 文件结构

```
backend/app/
├── joysafeter_api/api/v1/
│   └── channels.py                    # CRUD + Webhook endpoints
│
├── joysafeter_domain/
│   ├── models/
│   │   └── joysafeter_channel.py      # ORM model
│   ├── schemas/
│   │   └── joysafeter_channel.py      # Pydantic schemas
│   └── services/
│       └── joysafeter_channel_service.py  # 业务逻辑
│
├── joysafeter_shared/
│   └── channels/
│       ├── __init__.py
│       ├── adapter.py                 # PlatformAdapter ABC
│       ├── registry.py                # adapter 注册表
│       ├── wecom.py                   # 企微适配器
│       ├── feishu.py                  # 飞书适配器
│       ├── dingtalk.py                # 钉钉适配器
│       └── qq.py                      # QQ 适配器
│
├── joysafeter_worker/
│   └── channel_reply_subscriber.py    # 出方向 Reply Worker
│
└── alembic/versions/
    └── 2026MMDD_000001_add_channels.py  # 数据库迁移

frontend/app/managed/channels/
├── page.tsx                           # 渠道列表页
└── components/
    ├── create-channel-dialog.tsx       # 创建渠道弹窗
    └── channel-detail-panel.tsx        # 渠道详情/编辑面板
```

---

## 10. 前端交互流程

```
┌─────────────────────────────────────────────────────────────────┐
│  渠道管理页 /managed/channels                                     │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ [+ 创建渠道]                                                 │ │
│  │                                                             │ │
│  │  名称          平台      绑定Session    状态    操作          │ │
│  │  ─────────────────────────────────────────────────────────  │ │
│  │  客服Bot       企微      sess_01a...   ✅启用   编辑 删除    │ │
│  │  技术支持      飞书      sess_02b...   ✅启用   编辑 删除    │ │
│  │  内部问答      钉钉      sess_03c...   ⏸禁用   编辑 删除    │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘

创建流程 (步骤式弹窗):

  Step 1: 选择平台类型
  ┌───────────────────────────────────────┐
  │  [企微 AIBot]  [飞书]  [钉钉]  [QQ]   │
  └───────────────────────────────────────┘

  Step 2: 填写平台配置
  ┌───────────────────────────────────────┐
  │  名称: [__客服助手-企微__]             │
  │                                       │
  │  Token:          [__随机获取__|🔄]     │
  │  EncodingAESKey: [__随机获取__|🔄]     │
  │  CorpID:         [__ww12345678__]     │
  └───────────────────────────────────────┘

  Step 3: 绑定 Session
  ┌───────────────────────────────────────┐
  │  选择 Agent:  [▼ 客服Agent (claude)]  │
  │  选择 Session: [▼ sess_01abc...]      │
  │                                       │
  │  (或: [+ 自动创建新 Session])          │
  └───────────────────────────────────────┘

  Step 4: 完成 — 显示 Webhook URL
  ┌───────────────────────────────────────┐
  │  ✅ 渠道创建成功！                     │
  │                                       │
  │  Webhook URL:                         │
  │  ┌─────────────────────────────────┐  │
  │  │ https://your.domain/api/v1/     │  │
  │  │ channels/webhook/a8f3k2m9  [📋] │  │
  │  └─────────────────────────────────┘  │
  │                                       │
  │  请将此 URL 填入企微 AIBot 的          │
  │  "URL 回调" 连接方式中。               │
  └───────────────────────────────────────┘
```

---

## 11. 配置项（env）

```bash
# 渠道功能开关
JOYSAFETER_CHANNELS_ENABLED=true

# Webhook URL 对外暴露的 base (用于拼接完整 webhook_url 返回给用户)
# 默认使用 FRONTEND_URL。如果 API 和前端域名不同，需要显式设置。
JOYSAFETER_CHANNELS_WEBHOOK_BASE_URL=https://api.your-domain.com

# 单渠道 webhook rate limit (requests per minute)
JOYSAFETER_CHANNELS_WEBHOOK_RATE_LIMIT=100

# Reply worker 重试配置
JOYSAFETER_CHANNELS_REPLY_MAX_RETRIES=3
JOYSAFETER_CHANNELS_REPLY_RETRY_BASE_MS=2000
```

---

## 12. 实施节奏（建议分 3 期）

### Phase 1：核心骨架 + 企微
- 数据模型 + 迁移
- Channel CRUD API
- Webhook endpoint 框架
- 企微 AIBot Adapter（入方向 + 出方向）
- Reply Worker
- 前端管理页

### Phase 2：飞书 + 钉钉
- 飞书 Adapter
- 钉钉 Adapter
- 消息日志页面

### Phase 3：QQ + 增强
- QQ 机器人 Adapter
- 富媒体消息支持（图片/文件/卡片）
- 渠道监控/告警（投递失败率 Dashboard）

---

## 13. 关键设计决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| Webhook 路由 key | `webhook_secret` (随机 token) | 比 channel_id (UUID) 更安全，不可被枚举 |
| 凭据存储 | 加密字段 (VaultCipher) | 复用现有加密基础设施，运维成本低 |
| 出方向实现 | Redis pub/sub 订阅 session events | 实时性最好，且 JoySafeter 已有 session broadcaster 机制 |
| Task 创建 | 内部调用 TaskService | 复用现有 Task 流水线（排队、调度、sandbox），无需重写 |
| 消息去重 | platform_msg_id + DB unique constraint | 平台回调可能重试，必须幂等 |
| Session 绑定 | 固定绑定一个已有 Session | 方案 1（你选择的），简单直接 |
| 回复路由 | 从最近 inbound 消息获取 sender_id | 企微/飞书需要指定接收者 |
