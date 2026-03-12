# 教程 06：OpenClaw（沙盒与设备管控）深度解析与使用指南

> **适合人群**：希望深入了解 JoySafeter 底层沙盒机制、需要在隔离环境中安全执行代码/工具，或需要管理及远程操作真实/虚拟设备（如手机、浏览器）的高级用户。
> **目标**：彻底理解 OpenClaw 在 JoySafeter 架构中的真实定位，掌握其生命周期管理、WebUI 内嵌原理、设备配对流程以及技能隔离执行的闭环验证。

---

## 0. 重新认识 OpenClaw：它到底是什么？

在 JoySafeter 架构中，OpenClaw **不仅仅是一个文件目录**，它是一个**为每个用户独立分配的专属隔离 Docker 容器**（镜像：`joysafeter-openclaw:latest`）。

它在后台扮演着三个核心且高度集成的角色：

1. **内嵌控制台 (Embedded WebUI)**：提供了一个原生的 Dashboard 和 WebChat 界面，通过反向代理被无缝嵌入到 JoySafeter 的前端页面中。
2. **设备管控中心 (Device Manager)**：负责接入、列出并管理配对的外部设备（如 Android 手机、桌面浏览器等），充当 Agent 与真实物理/虚拟世界交互的桥梁。
3. **隔离执行沙盒与技能包裹中心 (Execution Sandbox & Skill Hub)**：提供隔离的文件系统（主要是 `/workspace/skills/`），安全地执行来自 Agent 的代码、脚本或高危工具，彻底杜绝了污染宿主机的风险。

---

## 1. 核心架构与实现原理（“Under the Hood”）

JoySafeter 后端通过一组专门的服务来精细调控 OpenClaw 的整个生命周期：

### 1.1 生命周期管理（Lifecycle Management）
后端的 `OpenClawInstanceService` 负责自动化管理：
- **按需分配**：当用户在界面点击“启动实例”时，服务会在安全的端口范围内（`19001-19999`）为该用户分配一个未被占用的端口。
- **安全鉴权**：系统会生成一个 32 字节的强随机 `gateway_token`，并作为环境变量注入到容器中。
- **容器启停**：通过 Docker Daemon API 直接拉起并管理该用户的专属容器，提供 `starting`、`running`、`stopped` 等明确的状态机。

### 1.2 无缝的 WebUI 嵌入（Reverse Proxy & Iframe）
你在 JoySafeter 界面上看到的 OpenClaw 页面，实际上是嵌入了一个 `iframe`。
- **反向代理**：前端请求 `/api/v1/openclaw/proxy/*`，后端代理服务会自动拦截，附加上对应用户的 `gateway_token`（作为 Bearer Token），然后转发给运行在独立端口上的 OpenClaw 容器内部网关（端口 18789）。
- **LocalStorage 注入**：为了让原生的 OpenClaw 控制台顺畅连接 WebSocket，代理会在返回的 HTML 中动态注入一小段 JavaScript 脚本，提前将 `gatewayUrl` 和 `token` 写入浏览器缓存。

### 1.3 自动设备配对（Device Pairing Auto-Approval）
OpenClaw 提供了连接外部设备的能力。为了提升用户体验：
- 当带有 `gateway_token` 的前端 WebUI 首次连接 WebSocket 时，后端会自动触发一个守护协程（Polling）。
- 该协程会在短时间内不断调用容器内的 `openclaw devices list`，一旦发现有新的待审批设备请求（Pending），就会自动执行 `openclaw devices approve <device_id>` 完成静默授权。

### 1.4 技能同步下发（Skill Synchronization）
当你在 JoySafeter 中导入了一个包含代码或脚本的 Skill（通过教程 03），它最初只存在于数据库中。
- **主动推送**：当你点击同步或 Graph 开始执行时，`SkillSandboxLoader` 会将该技能下属的所有文件打包成一个 `tar` 压缩包。
- **穿透挂载**：通过 Docker 接口，压缩包被直接“推送 (put_archive)”并解压到该用户专属容器内部的 `/workspace/skills/<skill_name>/` 目录下，让代码文件真正落地，随时准备被隔离执行。

---

## 2. 核心能力实操验证（验证你的专属容器）

为了确保你的 OpenClaw 正常运转，我们需要跑通一条最核心的使用与管控闭环，此过程全部聚焦于 OpenClaw 容器本身的能力。

### 2.1 容器启动与状态监控

**步骤**：
1. 进入 JoySafeter 左侧导航栏的【OpenClaw】菜单。
2. 如果你的实例尚未启动，页面会提示你启动。点击**启动实例（Start Instance）**。启动过程（拉取网络与处理配置）可能需要几十秒到几分钟。

**可验证点**：
- **容器层**：在服务器终端运行：
  ```bash
  docker ps | grep openclaw-user
  ```
  你会看到一个类似 `openclaw-user-<user_id>` 的独立容器正在运行。
- **UI 状态层**：页面侧边栏会显示当前实例 `running`，并且你会看到分配给你的专属 **网关端口 (Gateway Port)** 和一段长长的 **Token**。

### 2.2 体验无缝反向代理 WebUI

**可验证点**：
- 在实例启动后，主界面加载的即是 OpenClaw 原生控制台（通过 Iframe 嵌入）。这说明后端配置的反向代理（`/api/v1/openclaw/proxy`）和 Token 注入脚本功能正常，页面已经能够通过 WebSocket 直连容器网关。

### 2.3 技能同步 (Sync Skills) 实战

这是沙盒架构最关键的一环。

**步骤**：
1. 请确保你在 JoySafeter 技能大厅或个人技能库中，拥有至少一个包含具体脚本文件（如 `.py` 或 `.sh`）的 Skill。
2. 在 OpenClaw 管理面板（左侧信息栏下方），点击 **同步技能 (Sync Skills)** 按钮。稍等片刻并留意左下角的成功提示。

**可验证点（证明文件已落地沙盒）**：
- 进入宿主机终端，手动登入你的 OpenClaw 专属容器，并查看对应的技能投递目录：
  ```bash
  # 找出你的容器 ID
  docker ps | grep openclaw-user

  # 进入该容器，查看目录结构
  docker exec -it <你的容器ID> ls -l /workspace/skills
  ```
- 如果同步成功，你能在这看到对应技能名字的文件夹，以及它内部的脚本文件。这意味着，任何运行在这台容器里的 Agent 代码，现在都可以安全地引用和执行这些系统底层的脚本了。

### 2.4 设备接入与自动/手动审批验证

OpenClaw 能够作为客户端连接真实设备（例如一台安装了 OpenClaw Agent 端 APP 的安卓手机）。

**步骤**：
1. 在一部外部设备上运行 OpenClaw 接入端，配置并指向你分配到的**服务器 IP地址 + 专属网关端口 (Gateway Port)**，以及你的**网关 Token**（在 UI 面板上复制）。
2. 在 JoySafeter 界面上刷新“设备配对 (Device Pairing)”面板。

**可验证点**：
- 该新设备会在面板上首先显示为 **Pending**（待审批状态）。
- 很多情况下，当你进入面板的瞬间，内置代理后端的 `_poll_approve_devices` 协程便自动截获请求并完成审批，你会看到设备瞬间转为绿色的 **Paired**（已配对）状态。
- 如果没有自动配对，你可以点击待配对设备侧边的 **Approve (同意接入)** 按钮。审批通过后，Agent 就能在后续的任务规划中，将指令路由给这台真实的物理设备执行了。

---

## 3. 高级疑难排解

如果你在上述能力验证中遇到卡点：

**问题：点击启动后实例长时间处于 Starting（甚至 Failed）**
- **排查**：这通常说明主机网络无法拉取正确的 Openclaw Docker 镜像，或者环境配置遗漏了必需的环境变量。
- **命令**：检查后端分配日志或手动查看该生成容器的日志：`docker logs openclaw-user-<id_prefix>`

**问题：“同步技能”提示成功，但进入 `/workspace/skills` 却什么都没有**
- **排查**：你导入的 Skill 是否只包含了元数据/提示词而没有真实的物理文件？或者该用户权限不足？

**问题：无法使用 Copilot 或 DeepAgents 相关能力**
- **注意**：这是正常的。OpenClaw 只负责“准备好执行环境”和“管理设备”。如何调度模型去解析和调用这些技能，是通过 JoySafeter 庞大的核心图引擎 (Graph Builder) 以及 Copilot 面板在外部指挥完成的。请参考 **教程 04** 和 **教程 05** 获取更多 Agent 消费维度的教程。
