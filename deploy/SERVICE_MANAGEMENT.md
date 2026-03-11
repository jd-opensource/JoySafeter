# Service Management (Docker)

本文件收纳 `deploy/README.md` 中与服务状态/日志/重启/停止清理等运维操作相关的内容，避免部署入口文档过长。

---

## 查看服务状态

```bash
cd deploy

# 查看所有服务状态
docker-compose ps

# 查看中间件状态
docker-compose -f docker-compose-middleware.yml ps
```

## 查看日志

```bash
cd deploy

# 查看所有服务日志
docker-compose logs -f

# 查看特定服务日志
docker-compose logs -f backend
docker-compose logs -f frontend
docker-compose logs -f db
docker-compose logs -f redis
```

## 停止和清理

```bash
cd deploy

# 停止服务（保留数据）
docker-compose down

# 停止并删除数据卷（⚠️ 会删除所有数据）
docker-compose down -v

# 停止中间件
docker-compose -f docker-compose-middleware.yml down
```

## 重启服务

```bash
cd deploy

# 重启单个服务
docker-compose restart backend

# 重启所有服务
docker-compose restart