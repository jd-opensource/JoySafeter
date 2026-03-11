# Advanced Build (Multi-arch) & `deploy.sh`

本文件收纳 `deploy/README.md` 中与镜像构建、`deploy.sh`、多架构构建相关的内容，避免部署入口文档过长。

---

## 镜像构建和管理

`deploy.sh` 是统一的镜像构建和推送脚本，支持多架构构建、镜像推送和拉取。

### 基本用法

```bash
cd deploy

# 构建前后端镜像（默认：linux/amd64,linux/arm64）
./deploy.sh build

# 构建所有镜像（包括 backend, frontend, openclaw）
# 注意：MCP 服务镜像使用预构建镜像 docker.io/jdopensource/joysafeter-mcp:latest
./deploy.sh build --all

# 构建并推送到仓库
./deploy.sh push

# 拉取最新镜像
./deploy.sh pull
```

### 构建选项

```bash
cd deploy

# 只构建后端镜像
./deploy.sh build --backend-only

# 只构建前端镜像
./deploy.sh build --frontend-only

# 只构建 OpenClaw 镜像
./deploy.sh build --openclaw-only

# 构建所有镜像 (包含 backend, frontend, openclaw)
./deploy.sh build --all

# 禁用 Docker 构建缓存
./deploy.sh build --no-cache

# 构建指定架构
./deploy.sh build --arch amd64 --arch arm64

# 构建时指定前端 API 地址
./deploy.sh build --api-url http://api.example.com

# 指定镜像仓库和标签
./deploy.sh build --registry your-registry.com/namespace --tag v1.0.0
```

## 国内镜像源加速

```bash
cd deploy

# 使用华为云镜像源加速基础镜像和 pip
./deploy.sh build --mirror huawei --pip-mirror aliyun

# 支持的镜像源选项：
# --mirror: aliyun, tencent, huawei, docker-cn
# --pip-mirror: aliyun, tencent, huawei, jd
```

## 构建脚本环境变量

可以通过环境变量覆盖 `deploy.sh` 脚本的默认配置：

```bash
# 镜像仓库配置
export DOCKER_REGISTRY="your-registry.com/namespace"
export BACKEND_IMAGE="agent-platform-backend"
export FRONTEND_IMAGE="agent-platform-frontend"
export OPENCLAW_IMAGE="joysafeter-openclaw"
export IMAGE_TAG="v1.0.0"

# 构建平台配置
export BUILD_PLATFORMS="linux/amd64,linux/arm64"

# 前端 API 地址
export NEXT_PUBLIC_API_URL="http://api.example.com"

# pip 镜像源
export PIP_INDEX_URL="https://mirrors.aliyun.com/pypi/simple"
export UV_INDEX_URL="https://mirrors.aliyun.com/pypi/simple"
```

## 多架构构建说明

`deploy.sh` 默认使用 Docker Buildx 进行多架构构建，支持：

- `linux/amd64` - Intel/AMD 64位
- `linux/arm64` - ARM 64位（Apple Silicon, ARM 服务器）
- `linux/arm/v7` - ARM 32位

### 多架构构建注意事项

1. **本地构建多架构镜像**：使用 `--push` 选项才能保存所有架构的镜像到仓库
2. **本地测试**：不使用 `--push` 时，只会构建第一个架构的镜像用于本地测试
3. **Buildx 要求**：多架构构建需要 Docker Buildx，脚本会自动初始化