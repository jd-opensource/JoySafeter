#!/bin/bash
# Docker 中间件启动脚本
# 启动 PostgreSQL + Redis 并初始化数据库

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$DEPLOY_DIR"

# 颜色输出
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}🚀 JoySafeter - 启动服务${NC}"
echo -e "${GREEN}========================================${NC}"

# 检查 backend/.env 文件
if [ ! -f ../backend/.env ]; then
    echo -e "${YELLOW}⚠️  backend/.env 文件不存在，从 env.example 创建...${NC}"
    if [ -f ../backend/env.example ]; then
        cp ../backend/env.example ../backend/.env
        echo -e "${GREEN}✅ 已创建 backend/.env 文件，请根据需要修改配置${NC}"
    else
        echo -e "${RED}❌ backend/env.example 文件不存在${NC}"
        exit 1
    fi
fi

# 启动中间件服务
echo -e "${GREEN}📦 启动中间件服务（PostgreSQL + Redis）...${NC}"
docker-compose -f docker-compose-middleware.yml up -d

# 等待数据库就绪
echo -e "${YELLOW}⏳ 等待数据库就绪...${NC}"
CONTAINER_NAME="joysafeter-db"
timeout=60
counter=0

while [ $counter -lt $timeout ]; do
    health_status=$(docker inspect --format='{{.State.Health.Status}}' "$CONTAINER_NAME" 2>/dev/null || echo "none")
    
    if [ "$health_status" = "healthy" ]; then
        echo -e "${GREEN}✅ 数据库已就绪${NC}"
        break
    fi
    
    sleep 2
    counter=$((counter + 2))
    echo -n "."
done
echo ""

if [ $counter -ge $timeout ]; then
    echo -e "${RED}❌ 数据库启动超时${NC}"
    echo -e "${YELLOW}提示：docker-compose -f docker-compose-middleware.yml logs db${NC}"
    exit 1
fi

# 初始化数据库
echo -e "${GREEN}🔧 初始化数据库...${NC}"
docker-compose -f docker-compose-middleware.yml --profile init run --rm db-init

# 启动 MCP 服务
echo -e "${GREEN}📦 启动 MCP 服务...${NC}"
docker-compose -f docker-compose-middleware.yml up -d mcpserver

# 等待 MCP 容器就绪
echo -e "${YELLOW}⏳ 等待 MCP 容器就绪...${NC}"
MCP_CONTAINER_NAME="joysafeter-mcpserver"
mcp_timeout=60
mcp_counter=0

while [ $mcp_counter -lt $mcp_timeout ]; do
    if docker ps --format '{{.Names}}' | grep -q "^${MCP_CONTAINER_NAME}$"; then
        # 检查容器是否健康（如果健康检查已配置）
        health_status=$(docker inspect --format='{{.State.Health.Status}}' "$MCP_CONTAINER_NAME" 2>/dev/null || echo "none")
        
        # 尝试检查 supervisord 是否运行
        if docker exec "$MCP_CONTAINER_NAME" supervisorctl -c /export/App/supervisor/supervisord.conf status >/dev/null 2>&1; then
            echo -e "${GREEN}✅ MCP 容器已就绪${NC}"
            break
        fi
    fi
    
    sleep 2
    mcp_counter=$((mcp_counter + 2))
    echo -n "."
done
echo ""

if [ $mcp_counter -ge $mcp_timeout ]; then
    echo -e "${YELLOW}⚠️  MCP 容器启动超时，但将继续显示状态${NC}"
fi

# 显示 MCP 容器和 supervisord 进程状态
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}📊 MCP 服务状态${NC}"
echo -e "${GREEN}========================================${NC}"

# 检查容器状态
if docker ps --format '{{.Names}}' | grep -q "^${MCP_CONTAINER_NAME}$"; then
    echo -e "${GREEN}✅ MCP 容器运行中${NC}"
    container_status=$(docker inspect --format='{{.State.Status}}' "$MCP_CONTAINER_NAME" 2>/dev/null || echo "unknown")
    echo "  容器状态: $container_status"
    
    # 显示 supervisord 管理的进程状态
    echo ""
    echo -e "${GREEN}Supervisord 管理的进程状态：${NC}"
    if docker exec "$MCP_CONTAINER_NAME" supervisorctl -c /export/App/supervisor/supervisord.conf status 2>/dev/null; then
        echo ""
    else
        echo -e "${YELLOW}⚠️  无法获取 supervisord 进程状态${NC}"
    fi
else
    echo -e "${RED}❌ MCP 容器未运行${NC}"
    echo "提示: docker-compose -f docker-compose-middleware.yml logs mcpserver"
fi

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}✅ 服务启动完成！${NC}"
echo -e "${GREEN}========================================${NC}"