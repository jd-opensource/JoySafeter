# JoySafeter Frontend

JoySafeter 的前端应用（Next.js），提供可视化编排与交互式 Web UI。

> 说明：本文件只保留 **前端本地开发** 的最短路径；Docker/生产部署请统一以 `deploy/` 文档为准，避免重复与不一致。

## 快速开始（本地开发）

### 1) 安装依赖

```bash
cd frontend
# 推荐 bun（也可 npm/pnpm）
bun install
```

### 2) 配置环境变量

```bash
cp env.example .env.local
# 按需修改 .env.local（例如 NEXT_PUBLIC_API_URL）
```

### 3) 启动开发服务器

```bash
bun run dev
# 或：npm run dev / pnpm dev
```

访问：http://localhost:3000

## 常用脚本

```bash
bun run dev
bun run build
bun run start
bun run lint
bun run type-check
bun run test
```

## 部署入口（统一文档）

- 一键启动 / 场景化脚本 / 生产部署：[`deploy/README.md`](../deploy/README.md)
- 生产 IP/URL 配置最佳实践：[`deploy/PRODUCTION_IP_GUIDE.md`](../deploy/PRODUCTION_IP_GUIDE.md)

## 相关链接

- 后端：[`backend/README.md`](../backend/README.md)
- Next.js: https://nextjs.org/docs

## License

Apache 2.0
