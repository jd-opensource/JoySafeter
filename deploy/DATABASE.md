# Database Guide (Docker)

本文件收纳 `deploy/README.md` 中与数据库初始化/管理相关的内容，避免部署入口文档过长。

---

## 初始化数据库

数据库初始化通常会在各场景启动脚本（如 `./scripts/dev.sh`, `./scripts/start-middleware.sh` 等）中自动执行，也可以手动运行：

```bash
cd deploy

# 使用中间件配置初始化（db + redis）
docker-compose -f docker-compose-middleware.yml --profile init run --rm db-init

# 使用完整服务配置初始化
docker-compose --profile init run --rm db-init
```

## 数据库脚本

位于 `backend/scripts/db/`：

- `init-db.py` - 初始化数据库（创建表结构）
- `clean-db.py` - 清理数据（保留表结构）
- `wait-for-db.py` - 等待数据库就绪

## 手动操作数据库

```bash
cd deploy

# 进入数据库容器
docker-compose exec db psql -U postgres -d joysafeter

# 查看数据库状态
docker-compose exec db pg_isready -U postgres
