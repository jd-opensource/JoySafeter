# Deploy Troubleshooting (Docker)

本文件收纳 `deploy/README.md` 中的故障排查内容，避免部署入口文档过长。

> 适用范围：使用 `deploy/scripts/*.sh` 或 `docker compose` / `docker-compose` 启动 JoySafeter 的 Docker 场景。

---

## 常见问题

### 1) 环境检查失败

**问题**：运行 `./scripts/check-env.sh` 时出现错误

**解决方案**：

```bash
# 检查 Docker 是否运行
docker info

# 检查 Docker Compose 是否安装
docker compose version
# 或
docker-compose --version

# 检查端口占用
lsof -i :8000  # 检查后端端口
lsof -i :3000  # 检查前端端口
lsof -i :5432  # 检查数据库端口
```

### 2) 数据库连接失败

**问题**：后端无法连接到数据库

**解决方案**：

```bash
# 检查数据库容器状态
docker-compose ps db

# 查看数据库日志
docker-compose logs db

# 检查网络连接
docker-compose exec backend ping db

# 检查数据库配置
# 确保 backend/.env 中 POSTGRES_HOST=db（容器内使用服务名）
# 确保 deploy/.env 中 POSTGRES_PORT_HOST 正确映射
```

### 3) 端口冲突

**问题**：端口已被占用

**解决方案**：

```bash
# 方法一：使用环境检查工具查找可用端口
./scripts/check-env.sh

# 方法二：修改 deploy/.env 中的端口映射
POSTGRES_PORT_HOST=5433    # 改为其他端口
REDIS_PORT_HOST=6380       # 改为其他端口
BACKEND_PORT_HOST=8001     # 改为其他端口
FRONTEND_PORT_HOST=3001    # 改为其他端口

# 修改后重启服务
docker-compose down
docker-compose up -d
```

### 4) 镜像构建失败

**问题**：构建 Docker 镜像时失败

**解决方案**：

```bash
# 查看详细构建日志
./deploy.sh build --backend-only 2>&1 | tee build.log

# 使用国内镜像源加速
./deploy.sh build --mirror huawei --pip-mirror aliyun

# 清理构建缓存后重试
docker builder prune
./deploy.sh build
```

### 5) 服务启动失败

**问题**：服务无法正常启动

**解决方案**：

```bash
# 查看服务日志
docker-compose logs -f [service_name]

# 查看所有服务状态
docker-compose ps

# 重启服务
docker-compose restart [service_name]

# 完全重建服务
docker-compose down
docker-compose up -d --build
```

### 6) 配置文件缺失

**问题**：提示配置文件不存在

**解决方案**：

```bash
# 使用安装脚本自动创建
./install.sh

# 或手动创建
cp .env.example .env
cd ../backend && cp env.example .env
```

### 7) 数据库初始化失败

**问题**：数据库初始化脚本执行失败

**解决方案**：

```bash
# 检查数据库是否就绪
docker-compose exec db pg_isready -U postgres

# 手动运行初始化脚本
docker-compose --profile init run --rm db-init
# 如果是本地开发环境的中间件：
docker-compose -f docker-compose-middleware.yml --profile init run --rm db-init

# 如果失败，查看详细日志
docker-compose logs db-init
```

### 8) 前端无法连接后端

**问题**：前端页面无法访问后端 API

**解决方案**：

```bash
# 检查后端服务是否运行
docker-compose ps backend

# 检查后端日志
docker-compose logs backend

# 检查 CORS 配置
# 确保 backend/.env 中 CORS_ORIGINS 包含前端地址
# 确保 deploy/.env 中 FRONTEND_URL 正确

# 检查网络连接
curl http://localhost:8000/health  # 测试后端健康检查
```

---

## 日志查看

```bash
# 查看所有服务日志
docker-compose logs -f

# 查看特定服务日志
docker-compose logs -f backend
docker-compose logs -f frontend
docker-compose logs -f db

# 查看最近 100 行日志
docker-compose logs --tail=100 backend

# 查看特定时间段的日志
docker-compose logs --since 30m backend
```

## 服务状态检查

```bash
# 查看所有服务状态
docker-compose ps

# 查看服务健康状态
docker-compose ps --format json | jq '.[] | {name: .Name, status: .State, health: .Health}'

# 检查服务资源使用
docker stats

# 进入容器调试
docker-compose exec backend bash
docker-compose exec frontend sh
```

## 清理和重置

```bash
# 停止所有服务（保留数据）
docker-compose down

# 停止并删除数据卷（⚠️ 会删除所有数据）
docker-compose down -v

# 清理未使用的镜像和容器
docker system prune -a

# 完全重置（停止所有服务、删除数据、清理镜像）
docker-compose down -v
docker system prune -a --volumes
