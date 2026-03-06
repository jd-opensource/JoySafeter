# 生产环境 & 指定前后端 IP/域名：最佳实践（JoySafeter）

这份文档专门解决两类问题：

- **生产环境怎么正确部署**（安全、可运维、可扩展）
- **如何把前端指向指定后端 IP/域名**（以及后端如何正确回填前端 URL / 跨域 / Cookie）

> 约定：这里的“前端 URL”指用户在浏览器里打开的地址；“后端 URL”指浏览器能访问到的 API 公网地址（不要写容器内域名）。

---

## 你需要理解的 3 个关键变量（最容易配错）

### `deploy/.env`（Docker Compose 解析用）

- **`FRONTEND_URL`**：用户在浏览器访问前端的**真实公网绝对 URL**（结尾不要 `/`）。
  - 用途：后端生成邮件链接 / OAuth 回调 / 分享链接拼接；生产 `docker-compose.prod.yml` 也会用它自动设置 `CORS_ORIGINS`。
- **`BACKEND_URL`**：浏览器访问后端 API 的**真实公网绝对 URL**（建议是 `https://api.xxx.com` 或 `https://xxx.com/api` 的“服务入口”，结尾不要 `/`）。
  - 用途：生产 `docker-compose.prod.yml` 会把它注入前端为 `NEXT_PUBLIC_API_URL`（前端请求 API 的 base）。

### `backend/.env`（后端应用读取用）

- **`CORS_ORIGINS`**：允许跨域的前端源列表（JSON 数组字符串）。
  - 生产 compose 下不必手动填：`docker-compose.prod.yml` 会默认用 `["${FRONTEND_URL}"]` 覆盖。
  - 需要多个前端源（比如主站 + 管理后台）时，才建议显式配置。

---

## 推荐拓扑 A：单机同宿主机（最省心，优先推荐）

适用：前后端、数据库、Redis 在同一台服务器上；你只需要一个公网域名或 IP。

### 1) 写 `deploy/.env`（核心）

在服务器上：

- `deploy/.env`（从 `deploy/.env.example` 复制）

示例（按你实际域名/IP改）：

```dotenv
# 前端对外访问地址（用户在浏览器打开的地址）
FRONTEND_URL=https://joysafeter.example.com

# 后端对外访问地址（浏览器能访问到的 API base）
BACKEND_URL=https://api.joysafeter.example.com

# 宿主机端口映射（如果你用反向代理，通常不需要暴露到公网，只要本机可访问即可）
FRONTEND_PORT_HOST=3000
BACKEND_PORT_HOST=8000
POSTGRES_PORT_HOST=5432
REDIS_PORT_HOST=6379

# 镜像仓库（可选，.env.example 中无此项；compose 有内置默认值，不配也能跑）
# DOCKER_REGISTRY=docker.io/jdopensource
# IMAGE_TAG=latest
```

### 2) 写 `backend/.env`（生产必改项）

生产至少要确认：

- `SECRET_KEY`：换成强随机值（不要保留示例里的 `CHANGE-THIS-IN-PRODUCTION`）
  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(32))"
  ```
- `CREDENTIAL_ENCRYPTION_KEY`：**必须配置**，否则每次重启后端会生成随机密钥，导致已存储的模型凭据全部无法解密
  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(32))"
  ```
- `POSTGRES_PASSWORD`：换成强密码（不要保留默认的 `postgres`），同时修改 `deploy/.env` 中对应的 `POSTGRES_PASSWORD` 保持一致
- `DEBUG=false`
- `ENVIRONMENT=production`

此外，如果你会用 HTTPS + Cookie 登录，通常还需要：

- `COOKIE_SECURE=true`
- `COOKIE_SAMESITE=lax`（同站点通常 OK；如果你做跨站点嵌入/第三方跳转再评估）
- `COOKIE_DOMAIN=.example.com`（只在你需要子域共享 Cookie 时设置）

### 3) 启动生产

> **前置步骤**：如果是首次部署，先运行安装脚本初始化配置文件：
>
> ```bash
> cd deploy
> ./install.sh --mode prod
> ```
>
> `install.sh` 会从 `.env.example` 生成 `.env` 文件（`deploy/.env` 和 `backend/.env`），并引导你填写关键配置。
> 如果你已经手动创建过 `.env` 文件，可以跳过此步。

```bash
cd deploy
./scripts/prod.sh
```

`prod.sh` 支持以下选项：

| 选项 | 说明 |
|---|---|
| `--skip-env` | 跳过 `.env` 文件初始化 |
| `--skip-db-init` | 跳过数据库初始化 |
| `--skip-pull` | 跳过镜像拉取（使用本地已有镜像） |
| `--skip-mcp` | 不启动 MCP 服务 |

### 4) 生产强烈建议：用 Nginx / Caddy 做 HTTPS 终止与反代

原因：

- 证书自动续期、HTTP/2、静态缓存、限流、防护
- 只暴露 80/443 到公网；3000/8000 留在内网/本机
- 统一同域名，减少跨域与 Cookie 复杂度

#### 方案 4.1：两个子域（推荐清晰）

- 前端：`https://joysafeter.example.com` → 反代到 `127.0.0.1:3000`
- 后端：`https://api.joysafeter.example.com` → 反代到 `127.0.0.1:8000`

此时你应设置：

- `FRONTEND_URL=https://joysafeter.example.com`
- `BACKEND_URL=https://api.joysafeter.example.com`

#### 方案 4.2：同域名路径反代（更少域名）

- 前端：`https://joysafeter.example.com` → `127.0.0.1:3000`
- 后端：`https://joysafeter.example.com/api` → `127.0.0.1:8000`

此时你应设置：

- `FRONTEND_URL=https://joysafeter.example.com`
- `BACKEND_URL=https://joysafeter.example.com`（因为前端代码会把 `NEXT_PUBLIC_API_URL` 去掉 `/api` 再拼 `/api/v1`）

> 注意：你们前端 `frontend/lib/api-client.ts` 会把 `NEXT_PUBLIC_API_URL` 做一次“去掉尾部 /api”的归一化，然后再拼 `${base}/api/v1/...`。因此：
>
> - 如果你想走“同域名路径反代”，建议把 `BACKEND_URL` 填成站点根（如 `https://joysafeter.example.com`），并在反代里把 `/api/` 转到后端 8000。

---

## 推荐拓扑 B：前后端分离（分别部署到不同 IP/机器）

适用：后端（含 db/redis）在 A 机，前端在 B 机；或者你只想把前端部署到 CDN/静态托管。

### 目标

- **前端**知道“该请求哪个后端 API” → `NEXT_PUBLIC_API_URL`
- **后端**知道“真实前端 URL” → `FRONTEND_URL`（用于邮件链接/OAuth 回调）+ `CORS_ORIGINS`

### 方式 B1：两台机器都用 Docker（最接近你们当前脚本）

#### 后端机（A）

1) `backend/.env`：

- `FRONTEND_URL=https://joysafeter.example.com`
- `CORS_ORIGINS=["https://joysafeter.example.com"]`（或多个）
- 生产安全项（`SECRET_KEY`、`DEBUG=false`、Cookie 等）

2) **不要把数据库端口/Redis 端口暴露公网**，只在 A 机内部使用（或者用 VPC/安全组限制）。

3) 启动后端相关容器（你们当前 `docker-compose.prod.yml` 同时含前端；如果你只部署后端，建议在后端机使用一个精简 compose，只起 `db/redis/backend/(mcp)`）。

> 如果你希望我顺便提供“后端-only”的 `docker-compose.prod.backend.yml`（最小可用），我可以直接按你们现有文件拆出一份，避免在后端机上启动前端容器。

#### 前端机（B）

你有两种常见做法：

- **B1-1：前端仍用 Docker 容器跑（Next.js server）**
- **B1-2：前端走静态托管/CDN（如果你们前端构建产物是纯静态；Next.js SSR/Route Handler 场景一般不适用）**

下面按“容器跑”的方式写（更贴合你们现状）。

1) 在前端机设置前端运行时环境变量（核心是 `NEXT_PUBLIC_API_URL`）：

- 如果你在前端机用 `docker-compose.prod.yml`（不推荐，因为它还会启动 backend/db/redis），那就需要改 compose 拆分。
- 更推荐：前端机直接运行前端镜像，并显式传入变量（或用你们 `frontend/.env`）。

关键值应指向后端机（A）的公网 API 地址：

```dotenv
NEXT_PUBLIC_API_URL=https://api.joysafeter.example.com
```

2) 如果你们前端开启了 CSP（生产默认启用），并且后端与一些 websocket / MCP 服务不在同一主机，需要额外放行：

- `NEXT_PUBLIC_CSP_CONNECT_SRC_EXTRA`：额外允许的 `connect-src` 域名（HTTP/S + WS/S）
- `NEXT_PUBLIC_CSP_FRAME_SRC_EXTRA`：额外允许的 `frame-src` 域名

示例：

```dotenv
NEXT_PUBLIC_CSP_CONNECT_SRC_EXTRA="https://api.joysafeter.example.com wss://api.joysafeter.example.com"
```

> 你们的 `frontend/middleware.ts` 会从 `NEXT_PUBLIC_API_URL` 自动推导后端域名并加入 CSP（含端口通配），因此**只要前端能正确拿到 `NEXT_PUBLIC_API_URL`，多数情况下不需要手动加 extra**。

3) 后端机（A）必须允许来自前端机（B）的跨域（除非你用同域名反代把跨域消掉）：

- 推荐：用 Nginx/Caddy 做同域名反代（前端与后端同源），跨域与 Cookie 最简单
- 如果必须跨域（`https://joysafeter.example.com` 调 `https://api.joysafeter.example.com`），确保：
  - 后端 `CORS_ORIGINS` 含前端源（如 `["https://joysafeter.example.com"]`）
  - Cookie 相关：如果浏览器把它视作跨站点 Cookie 场景，通常需要 `COOKIE_SAMESITE=none` 且 `COOKIE_SECURE=true`

---

### 方式 B2：只想“指定 IP”快速验证（临时/测试）

适用：你只是想快速把前端指到某个后端 IP（没有域名/HTTPS），用于内网或短期验收。

#### 仅改前端指向后端 IP

- 前端 `.env.local`（本地跑前端）：

```dotenv
NEXT_PUBLIC_API_URL=http://<后端IP>:8000
```

- 或生产 compose（同机）里 `deploy/.env`：

```dotenv
BACKEND_URL=http://<后端IP>:8000
```

#### 同时要让后端正确生成邮件链接/回调链接

后端（`backend/.env`）需要真实的前端地址：

```dotenv
FRONTEND_URL=http://<前端IP>:3000
```

并允许跨域（如果前后端不同源）：

```dotenv
CORS_ORIGINS=["http://<前端IP>:3000"]
```

> 生产不建议用裸 IP + HTTP：Cookie 安全、浏览器策略、以及中间人风险都会更麻烦。最好尽快切到 HTTPS + 域名 + 反向代理。

---

## 推荐的生产落地清单（照着做不容易踩坑）

- **域名与 HTTPS**
  - 前端与后端尽量做同域名（或同 eTLD+1）规划
  - 80/443 对公网，3000/8000/5432/6379/8001-8010 只对内
- **`.env` 责任划分**
  - `deploy/.env`：端口映射 + `FRONTEND_URL` + `BACKEND_URL` + 镜像仓库信息
  - `backend/.env`：应用配置（`SECRET_KEY`、`CREDENTIAL_ENCRYPTION_KEY`、`DEBUG`、邮件、Cookie、安全）
  - 前端运行时：`NEXT_PUBLIC_API_URL`（容器时由 `BACKEND_URL` 注入；本地/静态时由 `.env.local` 提供）
- **跨域与 Cookie**
  - 能同源就同源（`/api` 路径反代），能避免 80% 的跨域/Cookie 问题
  - 必须跨域时：`CORS_ORIGINS` 要准确，且 Cookie 可能需要 `SameSite=None; Secure`
- **安全**
  - 替换 `SECRET_KEY`（强随机值）
  - 配置 `CREDENTIAL_ENCRYPTION_KEY`（不配则重启后凭据丢失）
  - 替换 `POSTGRES_PASSWORD`（`deploy/.env` 和 `backend/.env` 保持一致）
  - 关闭 `DEBUG`
  - 配置防火墙/安全组（数据库、Redis、MCP 端口不暴露公网）
  - 日志与备份（Postgres volume、上传文件 volume）

---

## MCP Server 生产部署注意事项

`docker-compose.prod.yml` 中 MCP 服务使用了 `profiles: [mcpserver]`，`prod.sh` 默认会带 `--profile mcpserver` 启动它。

- **端口安全**：MCP 端口（默认 8001-8010）仅供内部 backend 容器访问，**不要暴露到公网**。通过防火墙/安全组限制仅允许宿主机或 Docker 内部网络访问。
- **不需要 MCP 时**：使用 `./scripts/prod.sh --skip-mcp` 跳过启动。
- **自定义端口**：在 `deploy/.env` 中修改 `DEMO_MCP_SERVER_PORT`、`SCANNER_MCP_PORT` 等变量（注意只改宿主机侧，容器内始终监听 8001-8010）。

---

## OpenClaw 生产部署注意事项

后端通过 Docker API 为每个登录用户动态创建独立的 OpenClaw 容器，因此：

- **Docker Socket 挂载**：`docker-compose.yml` 默认挂载了 `/var/run/docker.sock`，这赋予了 backend 容器对宿主机 Docker 的完全控制权。**生产环境应评估此安全风险**，可考虑：
  - 使用 Docker Socket Proxy（如 [tecnativa/docker-socket-proxy](https://github.com/Tecnativa/docker-socket-proxy)）限制 API 权限
  - 通过用户权限（非 root 运行 backend）降低攻击面
- **镜像构建**：OpenClaw base 镜像需要预先构建：
  ```bash
  cd deploy
  docker compose --profile build build openclaw-image
  ```
- **资源管控**：大量并发用户可能创建大量容器，建议配置 Docker 资源限制（CPU、内存）并设置合理的容器回收策略。

---

## 常见错误与快速定位

### 1) 前端能打开，但所有请求 401/跨域失败

- 检查 `NEXT_PUBLIC_API_URL`（或 `deploy/.env` 的 `BACKEND_URL`）是否写成了容器内地址（如 `http://backend:8000`）→ **必须是浏览器可访问的公网地址**
- 检查后端 `CORS_ORIGINS` 是否包含真实前端源（协议+域名+端口一致）
- 检查 Cookie 配置（HTTPS 下是否 `COOKIE_SECURE=true`，跨站点是否需要 `COOKIE_SAMESITE=none`）

### 2) 邮件里的重置密码/邀请链接跳转到错误地址

- 99% 是 `FRONTEND_URL` 配错（写成了 `localhost` 或容器域名）
- 在 Docker Compose 部署时优先改 `deploy/.env` 的 `FRONTEND_URL`

### 3) CSP 报错导致 websocket/MCP/第三方请求被浏览器拦截

- 首先确认 `NEXT_PUBLIC_API_URL` 正确（你们中间件会自动把该域名加入 CSP）
- 如果第三方服务不在该主机上，用 `NEXT_PUBLIC_CSP_CONNECT_SRC_EXTRA` 追加允许域名

### 4) 重启后端后，模型凭据全部失效 / 解密失败

- 99% 是未配置 `CREDENTIAL_ENCRYPTION_KEY`。后端默认每次启动生成随机密钥，重启后旧密钥丢失、无法解密已存储的凭据
- 解决：在 `backend/.env` 中设置固定的 `CREDENTIAL_ENCRYPTION_KEY`（用 `python -c "import secrets; print(secrets.token_urlsafe(32))"` 生成）

### 5) 数据库连接失败 / 认证错误

- 检查 `deploy/.env` 和 `backend/.env` 中的 `POSTGRES_PASSWORD` 是否一致
- Docker Compose 使用 `deploy/.env` 中的值创建数据库，后端使用 `backend/.env` 中的值连接——两者不一致会导致认证失败

### 6) `prod.sh` 启动报错 "deploy/.env 文件不存在"

- 先运行 `./install.sh --mode prod` 初始化配置文件，或手动从 `.env.example` 复制
