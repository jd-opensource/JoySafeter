# JoySafeter - Frontend

JoySafeter 的前端应用，基于 Next.js 构建的现代化智能体平台 Web 界面。

## 🛠️ 技术栈

### 核心框架
- **Next.js 16.0** - React 全栈框架
- **React 19.2** - UI 库
- **TypeScript 5.7** - 类型安全
- **Tailwind CSS 3.4** - 实用优先的 CSS 框架

### UI 组件库
- **Radix UI** - 无样式、可访问的 UI 组件
- **Lucide React** - 图标库
- **Framer Motion** - 动画库
- **React Flow** - 流程图和节点编辑器

### 状态管理和数据获取
- **Zustand** - 轻量级状态管理
- **TanStack Query (React Query)** - 服务器状态管理
- **React Hook Form** - 表单处理
- **Zod** - Schema 验证

### 其他重要库
- **i18next** - 国际化支持
- **next-themes** - 主题切换（深色/浅色模式）
- **React Markdown** - Markdown 渲染
- **Better Auth** - 认证和授权

## 📋 前置要求

- **Node.js** >= 20.0.0
- **Bun** >= 1.2.0 (可选，但推荐用于更快的包管理)
- **npm** 或 **pnpm** (如果使用 npm/pnpm)

## 🚀 快速开始

### 1. 安装依赖

使用 Bun（推荐）：
```bash
bun install
```

或使用 npm：
```bash
npm install
```

或使用 pnpm：
```bash
pnpm install
```

### 2. 配置环境变量

创建 `.env.local` 文件（可以参考 `.env.example`）：

```bash
# 后端 API 地址
NEXT_PUBLIC_API_URL=http://localhost:8000

# 认证配置
BETTER_AUTH_URL=http://localhost:3000
BETTER_AUTH_SECRET=your-secret-key-here

# 其他配置...
```

### 3. 运行开发服务器

```bash
# 使用 npm
npm run dev

# 使用 Bun
bun run dev

# 使用 pnpm
pnpm dev
```

应用将在 http://localhost:3000 启动。

## 📜 可用脚本

```bash
# 开发模式（热重载）
npm run dev

# 构建生产版本
npm run build

# 启动生产服务器
npm run start

# 运行 ESLint
npm run lint

# TypeScript 类型检查
npm run type-check

# 运行测试
npm run test

# 监听模式运行测试
npm run test:watch
```

## 🏗️ 项目结构

```
frontend/
├── app/                      # Next.js App Router 页面和路由
│   ├── (auth)/              # 认证相关页面（登录、注册等）
│   ├── chat/                # 聊天界面
│   ├── workspace/           # 工作区管理
│   ├── skills/              # 技能管理
│   └── layout.tsx           # 根布局
├── components/              # React 组件
│   ├── ui/                  # 通用 UI 组件
│   └── app-shell/           # 应用外壳组件
├── lib/                     # 工具库和配置
│   ├── auth/                # 认证相关
│   ├── core/                # 核心工具
│   ├── i18n/                # 国际化
│   └── utils.ts             # 工具函数
├── hooks/                   # 自定义 React Hooks
├── services/                # API 服务层
├── stores/                  # Zustand 状态管理
├── providers/               # React Context Providers
├── public/                  # 静态资源
├── styles/                  # 全局样式
└── types.ts                 # TypeScript 类型定义
```

## 🔧 开发指南

### 代码规范

- 使用 TypeScript 进行类型安全开发
- 遵循 ESLint 规则（运行 `npm run lint` 检查）
- 使用 Prettier 格式化代码（如果配置了）
- 组件使用函数式组件和 Hooks

### 添加新页面

在 `app/` 目录下创建新的路由：

```typescript
// app/new-page/page.tsx
export default function NewPage() {
  return <div>新页面</div>
}
```

### 使用 UI 组件

从 `components/ui/` 导入组件：

```typescript
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'

export default function MyComponent() {
  return (
    <Card>
      <Button>点击我</Button>
    </Card>
  )
}
```

### 状态管理

使用 Zustand 进行客户端状态管理：

```typescript
// stores/my-store.ts
import { create } from 'zustand'

interface MyState {
  count: number
  increment: () => void
}

export const useMyStore = create<MyState>((set) => ({
  count: 0,
  increment: () => set((state) => ({ count: state.count + 1 })),
}))
```

### API 调用

使用 TanStack Query 进行数据获取：

```typescript
import { useQuery } from '@tanstack/react-query'

function MyComponent() {
  const { data, isLoading } = useQuery({
    queryKey: ['myData'],
    queryFn: async () => {
      const res = await fetch('/api/data')
      return res.json()
    },
  })

  // ...
}
```

## 🌍 国际化

项目支持多语言，使用 i18next 实现。

添加新语言：
1. 在 `lib/i18n/locales/` 下创建语言文件
2. 在 `lib/i18n/config.ts` 中注册新语言

使用翻译：

```typescript
import { useTranslation } from 'react-i18next'

function MyComponent() {
  const { t } = useTranslation()
  return <h1>{t('welcome')}</h1>
}
```

## 🎨 主题配置

项目支持深色和浅色主题，使用 `next-themes` 实现。

切换主题：
- 用户可以通过 UI 切换主题
- 系统会自动保存用户偏好

自定义主题颜色：
- 编辑 `tailwind.config.ts` 中的颜色配置
- 或在 `styles/globals.css` 中修改 CSS 变量

## 📦 构建和部署

### 构建生产版本

```bash
npm run build
```

构建输出位于 `.next/` 目录。

### Docker 部署

使用 Docker 进行部署，Dockerfile 位于 `deploy/docker/frontend.Dockerfile`。

详细部署说明请参考：
- [Deploy - Docker 部署配置](../deploy/README.md)
- [生产环境 & 指定前后端 IP/域名 最佳实践](../deploy/PRODUCTION_IP_GUIDE.md)

快速部署：

```bash
# 开发快速启动（本机）
cd deploy
./quick-start.sh

# 生产部署（服务器）
./scripts/prod.sh
```

### 环境变量

生产环境需要配置以下环境变量：

提示：在 Docker Compose 部署场景下，`NEXT_PUBLIC_API_URL` 通常由 `deploy/.env` 中的 `BACKEND_URL` 注入，无需手动设置。

**必需变量：**
- `NEXT_PUBLIC_API_URL` - 后端 API 地址
- `BETTER_AUTH_URL` - 认证服务地址
- `BETTER_AUTH_SECRET` - 认证密钥

**可选变量：**
- `NEXT_PUBLIC_CSP_WHITELIST` - CSP 白名单
- `NEXT_PUBLIC_ALLOW_EMBED` - 是否允许嵌入
- 其他配置请参考 `.env.example`

## 🧪 测试

运行测试：

```bash
# 运行所有测试
npm run test

# 监听模式
npm run test:watch
```

## 📚 相关文档

- [后端 README](../backend/README.md)
- [Docker 部署文档](../deploy/docker/DOCKER_DEPLOYMENT.md)
- [Next.js 文档](https://nextjs.org/docs)
- [React 文档](https://react.dev)
- [Tailwind CSS 文档](https://tailwindcss.com/docs)

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

Apache 2.0 License

## 🔗 链接

- 项目主页: https://github.com/jd-opensource/JoySafeter
- 文档: https://docs.your-platform.com
- API 文档: http://localhost:8000/docs (开发环境)
