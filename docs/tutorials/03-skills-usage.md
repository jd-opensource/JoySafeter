# 教程 03：高级技能（Skills）的导入、投递与沙盒验证闭环

> **适合人群**：希望让 Agent 拥有执行本地 Python/Shell 脚本能力的高阶玩家，或需要为团队维护通用工具库的平台开发者。
> **目标**：彻底理解 JoySafeter 中 Skills 的“三段式”生命周期（存储 -> 投递落盘 -> 隔离消费）。学会合规导入包含代码和 Markdown 描述的复杂技能，并掌握如何在 OpenClaw 沙盒中验证该文件是否已真实物理落盘。

---

## 0. 重新认识 Skills：它不只是“一段提示词”

初学者常常混淆 MCP 工具和本地 Skills。
- **MCP 服务**：是通过特定的标准协议提供的一组远程 HTTP/RPC 接口。代码在远端跑。
- **JoySafeter Skills**：则是**一组真实的物理文件**（通常包含一个 `SKILL.md` 描述文件 + 若干个 `.py` / `.sh` / `.json` 文件）。这意味着你想让 Agent 执行这些代码，平台就必须在系统底层**安全地传递并存储这些文件**。

为了兼顾代码共享的敏捷性和执行安全，JoySafeter 采用了一套极其严格的 **存储 (Storage) → 投递 (Delivery) → 消费 (Consumption)** 隔离管线。

---

## 1. 核心管线与实现原理（“Under the Hood”）

### 1.1 第一阶段：校验与存储（Validation & Storage - `SkillService`）
当你通过界面上传 ZIP 包或通过 API 导入文件夹时：
1. **防爆与清洗**：后端的 `is_system_file` 会拦截所有敏感系统文件；`is_valid_text_content` 会拦截所有不合规的二进制文件（仅允许导入 `.py, .md, .json, .yaml` 等纯文本）。这防止了恶意二进制可执行文件入库。
2. **元数据劫持（YAML Frontmatter）**：系统强制要求技能包内必须含有 `SKILL.md`。不仅如此，系统会提取该 Markdown 顶部的 YAML 声明（如 `name`, `description`, `compatibility` 等），**并用文件中的值强行覆盖数据库中的记录**。这意味着 `SKILL.md` 是这个技能“唯一的真相来源（Single Source of Truth）”。
3. 此时，你的技能通过了安检，**沉睡在 JoySafeter 的 PostgreSQL 数据库中**，尚未触及任何执行环境。

### 1.2 第二阶段：解包落盘与投递（Delivery - `SkillSandboxLoader`）
Agent 要跑脚本，不能去数据库里 read()。这就需要“沙盒装载器”。
- 当你在 UI 点击“同步 Skills”或图引擎（GraphBuilder）准备执行之前。
- 后端扫描该用户账户下所有授权的技能文件。在内存中将它们打包成一个 `tar` 归档。
- 它调用底层的 Docker API (`BackendProtocol.write`)，直接连通到用户专属的 **OpenClaw 沙盒容器**。
- 将归档推送到容器内的固定挂载点：**`/workspace/skills/<技能英文名>/`**，并在容器内解压。
- **至此，虚拟的数据库记录，正式化为了沙盒容器主机上一份份真实的物理文件。**

### 1.3 第三阶段：安全消费（Consumption）
图引擎中的某个 Agent Node 开始运作。它带有执行代码的能力（`code_interpreter` 工具）。
- 它的起始运行目录（CWD）被沙盒引擎严格锁死在了 `/workspace` 附近。
- Agent 可以通过标准的 Python `import` 或读取 `/workspace/skills/<技能名>/XXX.py` 来安全地调用这些刚刚由系统同步进来的隔离脚本，而由于这台容器是隔离的，无论脚本有多高危，都无法触及宿主机的环境。

---

## 2. 核心能力实操验证（打造闭环！）

下面我们来跑通一个完整的验证流水线。我们不用界面 UI，而是通过最根本的 API 调用去感受文件从数据库到沙盒的旅程。

### 2.1 准备符合规范的 Skill 文件结构

在你的本地机器创建一个文件夹 `my_test_skill/`：

**文件 1: `/my_test_skill/SKILL.md`**
这是技能的灵魂。请务必包含 YAML 头部：
```markdown
---
name: verify_disk_writer
description: 验证系统是否能将内容安全写入 /workspace，附带 100% 测试覆盖率。
compatibility: openclaw>=1.0.0
tags: [test, filesystem]
---

# Verify Disk Writer

这是一个测试沙盒文件穿透挂载是否成功的验证技能。
它提供了一个简单的 python 函数 `write_test_log()`。
```

**文件 2: `/my_test_skill/verify.py`**
真正的执行代码：
```python
import os
import datetime

def write_test_log():
    log_path = "/workspace/verification.log"
    with open(log_path, "a") as f:
        f.write(f"Verified at: {datetime.datetime.now()}\n")
    print(f"Success! Wrote to {log_path}")
```

你可以通过 JoySafeter 界面的【技能大厅】->【导入】压缩包上传，或者使用后台提供的自带脚本一键刷入：
```bash
# 在 JoySafeter 源码根目录下执行
python backend/scripts/load_skills.py ./my_test_skill
```

### 2.2 验证存储（Storage）元数据解析
进入 JoySafeter 界面 -> 技能大厅。
点开你刚导入的 `verify_disk_writer` 技能。
> **可验证点**：核对界面的“技能名称”、“描述”、“标签”是否完全读取了你刚才手写的 `SKILL.md` 顶部的 YAML 声明？这证明 `SkillService` 拦截并成功解析生效了。

### 2.3 **[最关键一步]** 验证沙盒投递落盘（Delivery）

只有落盘，Agent 才能用。
1. 前往左侧边栏的 **【OpenClaw】** 管理界面。确保你的实例正在运行 `running`。
2. 点击下方的 **【同步技能 / Sync Skills】** 按钮。（背后的 `SkillSandboxLoader` 正在将数据库打包推入你的这个专属容器中）。
3. 稍微等待完成。

**如何闭环验证它真的进沙盒了？**
打开你服务器的终端控制台，直连到你当前正在运行的那个 OpenClaw 容器里去看它的底层目录：

```bash
# 1. 找到你名下的那台 OpenClaw 沙盒容器 ID
docker ps | grep openclaw-user

# 2. 进入容器，查看系统的 /workspace/skills 挂载目录
docker exec -it <你的容器ID> ls -l /workspace/skills
```

> **可验证成功指标**：
> 如果显示出了 `verify_disk_writer` 文件夹，且你还能进一步 `cat /workspace/skills/verify_disk_writer/verify.py` 看到你写的 python 代码，**闭环达成！这证明系统不仅在库里存了信息，还成功穿透沙盒引擎把文件实打实地布置好了**。

### 2.4 在 Agent Builder 中真实挂载与消费验证（完整应用案例）

前排提示：文件虽然进了沙盒，但 Agent 在执行图（Graph）时，默认是不知道有哪些技能可用的。你必须显式地将技能装配（Mount）给它，它的 `systemPrompt` 才能“看见”工具的说明书。

我们来模拟一个最真实的业务开发闭环：

**步骤 1：新建包含技能的执行节点（Graph Node）**
1. 进入 JoySafeter 的 **【AgentBuilder】**（图构建器）界面。
2. 在画布上拖拽创建一个新的 **Agent 节点**（或者让 Copilot 帮你建一个）。
3. 选中该节点，打开右侧配置面板。
4. 找到 **【Tools（工具配置区）】** -> **【Skills（技能库挂载）】**。
5. 在下拉列表中，找到并勾选我们刚刚导入成功的 `verify_disk_writer` 技能。
*(这一步的背后：图引擎的 `SkillsMiddleware` 才会在该节点执行前，把 `SKILL.md` 里的描述动态注入到大模型的 System Prompt 里)*

**步骤 2：配置触发指令**
同样在右侧面板的 **【系统设定 / System Prompt】** 中，给 Agent 下达明确的指令：
> “你现在已经拥有了一项探测文件系统基础指标的技能。请直接执行为你准备好的 `/workspace/skills/verify_disk_writer/verify.py` 脚本，并调用其中的 `write_test_log` 函数。不要做多余的解释，直接输出脚本执行后的返回值。”

**步骤 3：模拟运行（测试沙盒穿透能力）**
1. 确保该节点连有输入端（如 Start 节点或 Human Input 节点）。
2. 在调试控制台（Runner）中发起首次对话，输入：“**开始巡检本地盘**”。
3. 观察执行流：
   - 此时，大模型会意识到它被附魔了特定的 Skill。
   - 它会自主生成 Python 代码去 `import sys` 并 `sys.path.append('/workspace/skills/verify_disk_writer')`，然后拉起 `verify.py`。
   - 打开右上角的 **【Action Logs（动作执行日志）】**，你会清晰地看到大模型生成的代码。
   - 看到最后的输出 `Success! Wrote to /workspace/verification.log`。

**核心结论：**
至此，一个 Skill 走完了它的一生：
「你手写的 `verify.py`」 -> 「封装进带 YAML 的 `.zip`」 -> 「存入 `SkillService` 数据库通过安检」 -> 「`SkillSandboxLoader` 打包推送到专属 OpenClaw 容器内落盘」 -> 「Graph 引擎中的 Agent 节点挂载描述文件」 -> 「大模型在隔离环境中动态运行你的代码」。这就是 JoySafeter 安全、合规、可复用的高阶本地技能管线架构。

## 3. 前端 UI 管控与发布市场真实案例 (Marketplace)

除了硬核的终端闭环验证，JoySafeter 同样提供了极度对非技术人员友好的完善 UI 体验面板。
下面，我们将演示如何**纯通过页面点选**，走完一个高价值能力的“导入 -> 修改 -> 验证 -> 发布变现”的全生命周期。

### 3.1 [实战案例] 从导入到公开发布的“大盘分析助手”

**步骤一：可视化导入 (UI Import)**
假如你在网上或者同事那里拿到了一份非常优秀的本地技能包 `stock_analyzer.zip`（内含一个 `analyze.py` 脚本和一个 `SKILL.md` 描述文件）。

1. 展开页面左侧导航栏，进入 **【技能大厅 (Skills Hub)】**。
2. 点击右上角的 **【导入 ☁️】** 按钮。
3. 把那个 `.zip` 文件直接拖拽进上传框，点击确认。
   > **UI 背后在干嘛？**：此时界面立刻调用了后端的 `SkillService` 进行校验，防爆系统会当面拆包，排查你有没有偷塞二进制乱码文件（如 `.exe`, `.dll`）。如果没有，就会读取你压缩包里的 `SKILL.md` 顶端 YAML 配置，并直接帮你生成好名称为“Stock Analyzer”的技能卡片！

**步骤二：使用自带源码编辑器 (Web IDE) 紧急 Debug**
如果你导入后，发现由于你的大盘 API Key 填错了，导致这个文件在被 Agent 引用时报错。
按照传统开发，你得本地改好代码，重新打压缩包，再传一遍——这里完全不需要！

1. 在 **【技能大厅】** 中点击你刚刚创建的 `stock_analyzer` 私有卡片，进入详情页。
2. 转到 **【文件编辑器 (Editor)】** 选项卡。左侧是一棵清晰的文件树。
3. 双击 `analyze.py`，你就能如同在 VSCode 里一样，对带有高亮的代码直接修改那个填错的 API Key。修改完毕点击保存。
   > **⚠️ 最容易中招的陷阱（必记）**：
   > 你在网页上点的“保存”，仅仅是把它更新到了 **PostgreSQL 数据库的存根** 里。
   > 大模型执行代码是在沙盒里的，所以**你必须立刻移步到左侧导航栏的【OpenClaw】面板，点一次【同步技能 / Sync Skills】**，触发落盘机制将新代码覆盖进沙盒，Bug 才算真正修好。

**步骤三：版本管理与协作 (Versioning & Collaboration)**

> **新功能**：JoySafeter 现已支持技能版本化和协作者管理，让团队协作开发技能成为可能。

**版本发布与回滚：**
1. 进入技能详情页，点击 **【版本 (Versions)】** 选项卡。
2. 点击 **【发布新版本 (Publish Version)】**，填写版本号（遵循 SemVer 语义化版本，如 `1.0.0`）和变更说明。
3. 系统会将当前技能的所有文件快照为一个不可变的版本。
4. 如果新版本出了问题，在版本历史列表中点击任意旧版本的 **【回滚 (Rollback)】** 即可一键恢复。

**邀请协作者：**
1. 在技能详情页，点击 **【协作者 (Collaborators)】** 选项卡。
2. 点击 **【邀请 (Invite)】**，输入同事的用户名，选择角色：
   - **Editor**：可编辑文件、发布版本
   - **Viewer**：仅可查看，不能修改
3. 技能所有者还可以通过 **【转移所有权 (Transfer Ownership)】** 将技能交给其他人管理。

**步骤四：发布到公共市场 (Publish to Public Market)**

JoySafeter 平台鼓励 AI 资产的相互复用。在经历前面步骤确信代码跑通可用后：

1. 重新进入该技能的详情页基本信息栏。
2. 找到 **【设置公开 (Set Public)】** 的开关按钮（或者你也可以在 Web编辑器 里的 `SKILL.md` 的 YAML 头部直接加上 `is_public: true` 并保存）。
3. 你的这张技能卡片会瞬间打上绿色的公开标识，并出现在整个平台所有用户的**公共技能大厅广场**中。

> **物理沙盒穿透隔离分发（关于安全！）**
> - 问题来了：如果你写了一个高危的 `rm -rf` 甚至能探测局域网的 Python 脚本发到了公屏，这是不是意味着大家点开你的脚本，平台的安全就被突破了？
> - 绝对不会！当其他同事在市场浏览到你的强力技能，并把它拖进他们自己创建的图引擎（GraphBuilder）的节点中时，JoySafeter 强大的沙盒分发层开始接管。
> - 系统会将你这段已经公开的代码文件无感抽取，**直接部署打包推进这位同事名下单独隔离的那一台 OpenClaw Docker 容器内，并在他的这台容器里执行**。无论脚本威力多大，都在他自家的铁盒子里“引爆炸弹”，平台获得了极致的隔离安全！

这就是从 0 构建一条私有技能走向公开分享变现链路的精妙设计理念。

---

## 4. 高级疑难排解

如果你在导入或使用中遇到了问题：

- **上传压缩包时报错：Invalid File Type**
  请确保证压包中没有 macOS 自动生成的 `.DS_Store` 或其他 `.dll`/`.exe`. `SkillService` 极度洁癖，只允许放入纯文本文件。
- **Agent 说找不着那个 Python 代码**
  极度可能是你在界面上新导了技能，但**忘记了去 OpenClaw 重新点一次【同步技能 / Sync Skills】**。数据库更新了，但沙盒里的物理文件还没被替换！
- **更新 `SKILL.md` 后名称或描述没跟上**
  UI 层面修改描述可能没用，JoySafeter 是以文件中的 YAML 为第一权威源头。如果你要永久性改名，请打开左侧边栏进入具体文件的代码编辑器，直接修改 `SKILL.md` 顶部的 YAML 字段。
