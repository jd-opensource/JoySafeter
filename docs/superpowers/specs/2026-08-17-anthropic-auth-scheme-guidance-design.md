# Anthropic 鉴权字段引导重设计

- 日期: 2026-08-17
- 分支: joysafeter-v2-0814
- 状态: 待评审

## 背景与问题

JoySafeter 模型接入(anthropic 协议)当前把鉴权拆成两个裸密钥字段:`ANTHROPIC_API_KEY`
(注入 `x-api-key` 头)和 `ANTHROPIC_AUTH_TOKEN`(注入 `Authorization: Bearer` 头,且被标为
advanced 折叠)。二者对应上游的两种鉴权方式:

- 官方 Anthropic(`api.anthropic.com`)只认 `x-api-key`。
- 国内 Anthropic 兼容中转网关(京东云 `ai-api.jdcloud.com` 等)只认 `Authorization: Bearer`。

2026-08-17 实测:一条 Claude-Opus-4.6 凭据把 key 填进了 `ANTHROPIC_API_KEY`,而 base_url 指向
京东云网关,网关返回 `401 {"message":"missing or invalid Authorization header"}`,会话报
`API Error: 400 异常apikey`。根因是**鉴权头填错字段**——网关要 Bearer,凭据却给了 x-api-key。
把 key 移到 `ANTHROPIC_AUTH_TOKEN` 后即恢复(已确认)。

痛点:用户无法从"API Key / Auth Token"两个字段名判断该填哪个;而国内用户绝大多数用 Bearer
中转网关(这也是 CC-switch 等工具默认写 `ANTHROPIC_AUTH_TOKEN` 的原因),当前 UI 却把 Auth Token
藏进 advanced、默认引导填 API Key,恰好把多数人带向错误字段,失败信息又晦涩。

## 目标

- 用户只填**一把 key**,不必理解 `x-api-key` vs `Authorization: Bearer` 的 header 细节。
- 系统按 base_url **自动判断**鉴权方式(官方=x-api-key,其余=Bearer)。
- 自动判错时,提供一个**开关**让用户手动指定鉴权方式。
- 杜绝"两个鉴权字段同时填"导致的歧义。
- 不触碰下游 Envoy 注入、沙箱 egress 等已验证的链路;改动集中在"表单 + 保存映射"。

非目标:不改 openai 协议的鉴权;不自动迁移存量凭据;不改 Rust 注入映射与 Envoy。

## 用户体验(页面)

anthropic 模型接入表单的鉴权区从"两个裸字段"改为:

1. **API Key**(必填,单个密钥输入框)——合并原 API Key / Auth Token 两个字段。
2. **鉴权方式**开关,三态:
   - `自动`(默认):base_url 为官方 `api.anthropic.com` → x-api-key;其余 → Bearer。
     开关下方小字实时显示当前判定(例:"当前将使用 Bearer(中转网关)")。
   - `x-api-key(官方)`:手动锁定 x-api-key。
   - `Bearer(中转网关)`:手动锁定 Bearer。
   手动扳定后不再随 base_url 变化。
3. **Base URL**、**Model** 保留。Model 增加帮助文案:提示填上游真实 model id(而非显示名)。

编辑已有凭据时:按 `data` 里哪个鉴权字段非空反推开关初值(`ANTHROPIC_API_KEY` 非空→x-api-key,
`ANTHROPIC_AUTH_TOKEN` 非空→Bearer),key 回填到单一输入框。

## 页面自洽约束(review 意见:注意页面的自洽)

改动必须让 anthropic 凭据在**所有页面/状态下呈现一致**,不能出现"新建页是单 key+开关、别处仍露两个
裸字段"的半吊子。逐条约束:

1. **新建 与 编辑 同构。** 新建对话框和编辑对话框用**同一个**鉴权控件(单 key + 方式开关),字段集、
   顺序、必填标记、帮助文案完全一致。编辑打开时开关按反推规则预选,展示与新建无缝对齐。
2. **不再出现裸的第二鉴权字段。** 全线不再单独渲染 `ANTHROPIC_API_KEY` 和 `ANTHROPIC_AUTH_TOKEN`
   两个并列输入框(尤其现在藏在"高级"里的 Auth Token 要撤掉),统一由"单 key + 方式开关"取代。
   凡引用 anthropic 字段清单的地方(`secret-keys.ts` 分组、任何字段渲染表)一并对齐,避免遗留旧字段。
3. **详情/列表展示一致。** 凭据详情或列表若展示鉴权信息,用与表单同一套措辞(如"鉴权方式:Bearer
   (中转网关)"),密钥值保持既有脱敏;不暴露内部 env 变量名(`ANTHROPIC_AUTH_TOKEN` 等)给用户。
4. **文案与实际行为一致。** 开关下方"当前将使用 X"的实时提示,必须与后端最终解析结果一致(同一判定
   规则),不能页面显示 Bearer、后端却按 x-api-key 落库。
5. **校验反馈同源。** 前端即时校验(鉴权恰好一个非空、model/base_url 必填)与后端校验规则一致,报错
   措辞对齐,避免"前端放过、后端拒绝"或反之。
6. **术语一致。** 开关标签、帮助文案沿用既有 i18n 术语体系(模型接入等),中英一致,纳入术语一致性测试;
   面向用户只说"鉴权方式 / API Key",不外泄 header 名(x-api-key / Authorization)与 env 变量名——
   除非作为高级说明的补充解释。

## 统一原则(本次核心约束)

用户要求「统一修复,别出现测试通过、使用不通过」。据此两条硬约束贯穿全设计:

1. **判定逻辑单一权威在后端。** 「auto → 具体鉴权方式 → 落到哪个 env 字段」的解析,是所有建/改
   凭据入口(表单 `/credentials`、`/credentials/test`、quickstart、以及任何直接 API 调用)**共用的
   同一段后端逻辑**,不在前端各写一套。前端开关只提交"意图"(`auth_scheme: auto|xapikey|bearer`),
   后端把它解析成最终存储。杜绝"前端映射对、别的入口漏映射"的分叉。
2. **运行时即真源,必须端到端验证。** 判成功的唯一标准是「真实会话经 Envoy 注入后上游返回 200」,
   不以单测/连接测试通过为准(本次调试反复出现的 127.0.0.1 免密假阳性、orchestrator 直连 503 都是
   "测试通过、使用不通过"的活教训)。验收闸见测试节。

## 数据行为(保存映射,后端权威)

请求体新增/沿用:`{ apiKey, authScheme: auto|xapikey|bearer, baseUrl, model }`(前端开关产出
`authScheme`;`apiKey` 是单一密钥输入)。**后端在持久化时**统一解析成现有 `data` JSONB 的 env 键:

1. 求有效方式:`auto` → 官方 host 判 x-api-key,否则 Bearer;非 auto → 用传入所选。
2. `xapikey` → key 写入 `ANTHROPIC_API_KEY`,`ANTHROPIC_AUTH_TOKEN` 置空/不写。
3. `bearer` → key 写入 `ANTHROPIC_AUTH_TOKEN`,`ANTHROPIC_API_KEY` 置空/不写。
4. 二者**互斥**,永不同时非空。

因此持久化结构不变(仍是 `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_MODEL`/
`ANTHROPIC_BASE_URL`),Rust 注入映射(`llm_providers.rs`)、Envoy、沙箱**零改动**。开关状态本身
不单独持久化,由"哪个字段非空"隐式表达。

"官方 host" 判定:base_url 主机名等于 `api.anthropic.com`(忽略大小写/末尾斜杠;为空时按官方处理,
因为空 base_url 走 Anthropic 默认端点)。**判定规则是后端单一函数/常量**;前端若需实时预览判定结果,
复用后端下发的同一规则(或后端提供 dry-run 预览),不在前端复制一份可能漂移的实现。

## 影响的层

- **后端(权威层)**:credentials 建/改的持久化路径新增一段 anthropic 鉴权解析(auto→具体方式→写对
  env 字段 + 互斥清空),所有入口共用。落点为 credentials application/domain 层(`joysafeter_application/
  credentials` + `joysafeter_domain/credentials` 或 credentials API `backend/app/joysafeter_api/api/v1/
  credentials.py` 的规范化处),具体文件在实现计划阶段定位;要求 `/credentials`、`/credentials/test`、
  quickstart 三处入口都经此解析。
- **后端 catalog** `backend/config/llm_catalog.yaml` 的 `anthropic_standard` profile:文案/可见性微调
  (base_url 是否仍 advanced、help_text 更新)。**约束:该 yaml 同时被 Rust orchestrator
  `include_str!` 嵌入,任何结构改动必须 Python(pydantic)与 Rust(serde)双端 parse 兼容;优先只改
  值/文案,不新增 schema 概念。**
- **前端** `frontend/components/managed/llm/llm-secret-configurator.tsx`:anthropic 鉴权区改为"单 key +
  方式开关",开关提交 `authScheme`;实时预览判定复用后端规则;编辑回填按"哪个字段非空"反推开关。
  前端**不**自行决定最终存哪个 env 字段——只传意图,存储由后端定。
- **前端** `frontend/lib/managed/secret-keys.ts` 及相关校验:调整 anthropic 分组呈现。
- **校验**:后端保证鉴权恰好一个非空(替换现有 `required_any_of` 两字段写法);前端同步友好提示;
  model/base_url 保持规则。
- **i18n**:开关三态标签 + 帮助文案的中英文案,纳入既有 i18n 清单与术语一致性测试。

## 连接测试与失败可读性

- `/credentials/test` **必须经上面同一段后端解析**得到最终鉴权方式再去连,确保"测试用的头"和"运行时
  Envoy 注入的头"一致——否则会重演"测试通过、运行不通过"。
- 当上游返回鉴权类 4xx 时,回显更可读的提示(例:"网关要求 Bearer,请把鉴权方式切到 Bearer")。

## 兼容与迁移

- 不自动迁移存量凭据。老数据 `ANTHROPIC_API_KEY` 非空者照常工作;打开编辑时按反推规则回填开关,用户可
  一键切到 Bearer 重存。
- 下游(Rust/Envoy/沙箱)不变,存量会话不受影响。

## 测试

- 后端单测(权威解析,重点):auto 判定(官方→xapikey、京东云→bearer)、手动覆盖锁定、映射互斥
  (永不双非空)、编辑回填反推;三入口(`/credentials`、`/credentials/test`、quickstart)都命中同一解析。
- 前端单测:开关交互、实时预览、回填、提交 `authScheme` 的形状。
- 后端:catalog 加载/校验通过;Rust orchestrator 仍能 `include_str!` 解析改后的 yaml(cargo 构建/相关测试)。
- i18n 术语一致性测试通过。
- **端到端验收闸(硬性,替代"单测过即完成"):** 用一条指向 Bearer 中转网关(京东云)的 anthropic 凭据,
  经前端保存 → 真实发起会话 → 沙箱经 Envoy 出站 → 上游返回 **200 并产出正常回复**。以此为"完成"的唯一
  判据;单测/连接测试通过但真实会话未验证,不算完成。验证手法:任务活跃窗口内经 runner
  `127.0.0.1:3128` 代理桥观察 Envoy access log 状态码 + 沙箱输出(参见调试备忘的取证方法与陷阱)。

## 风险

- 共享 yaml 的双端 parse 兼容(最大风险)——优先只改文案/可见性,不动结构;若必须加字段,需同时验证
  Rust 侧解析不 deny_unknown_fields 或同步更新其 struct。
- 自动判定对"用 x-api-key 的非官方中转"会判错——由手动开关兜底。
