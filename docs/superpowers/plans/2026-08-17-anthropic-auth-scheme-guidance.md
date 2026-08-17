# Anthropic 鉴权字段引导重设计 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 anthropic 模型接入表单用「单个 API Key + 鉴权方式开关(自动/x-api-key/Bearer)」取代两个裸密钥字段,后端按 base_url 权威解析并落到互斥的 env 字段,消除用户把 key 填错头导致的 `400 异常apikey`。

**Architecture:** 判定逻辑单一权威在后端一个纯函数(auto→具体方式→写对 `ANTHROPIC_API_KEY` 或 `ANTHROPIC_AUTH_TOKEN`,另一个清空),create/update/test 三入口共用;前端只提交 `auth_scheme` 意图。持久化结构不变,Rust 注入映射(`llm_providers.rs`)/Envoy/沙箱零改动。

**Tech Stack:** Python 3.12 + FastAPI + Pydantic(backend);Next.js + TypeScript + vitest(frontend);YAML catalog(Python pydantic + Rust serde 双端读取)。

## Global Constraints

- 判定与落库逻辑**只在后端一处**;前端不自行决定最终存哪个 env 字段,只传 `auth_scheme: auto|xapikey|bearer`。
- `/credentials`(create/update)、`/credentials/test` 三入口都必须经同一后端解析。
- `backend/config/llm_catalog.yaml` 同时被 Python(pydantic)与 Rust(`include_str!`)读取;改它必须双端 parse 兼容,优先只改文案/可见性,不新增 schema 概念。
- 下游不动:`ANTHROPIC_API_KEY`→`x-api-key`、`ANTHROPIC_AUTH_TOKEN`→`Authorization: Bearer` 的注入映射保持。
- 官方 host 判定:base_url 主机名 == `api.anthropic.com`(忽略大小写/协议/末尾斜杠;为空按官方处理)。
- 面向用户文案不外泄 header 名(x-api-key/Authorization)与 env 变量名;走既有 i18n 术语一致性测试。
- 后端测试从 `backend/` 运行:`cd backend && uv run pytest`(pytest 配置只在 `backend/pyproject.toml`)。
- **完成判据是端到端真实会话返回 200(Task 7),不是单测通过。**

---

### Task 1: 后端鉴权方式解析器(单一权威,纯函数)

**Files:**
- Create: `backend/app/joysafeter_domain/llm/anthropic_auth.py`
- Test: `backend/tests/test_anthropic_auth.py`

**Interfaces:**
- Produces:
  - `AUTH_SCHEME_AUTO = "auto"`、`AUTH_SCHEME_XAPIKEY = "xapikey"`、`AUTH_SCHEME_BEARER = "bearer"`
  - `is_official_anthropic(base_url: str) -> bool`
  - `resolve_auth_scheme(base_url: str, requested: str) -> str`(返回 `"xapikey"` 或 `"bearer"`)
  - `normalize_anthropic_auth(data: dict[str, str], requested_scheme: str) -> dict[str, str]`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_anthropic_auth.py
from app.joysafeter_domain.llm.anthropic_auth import (
    AUTH_SCHEME_AUTO,
    AUTH_SCHEME_BEARER,
    AUTH_SCHEME_XAPIKEY,
    is_official_anthropic,
    normalize_anthropic_auth,
    resolve_auth_scheme,
)


def test_official_host_detection():
    assert is_official_anthropic("https://api.anthropic.com") is True
    assert is_official_anthropic("https://api.anthropic.com/") is True
    assert is_official_anthropic("") is True  # 空 = 走官方默认端点
    assert is_official_anthropic("http://ai-api.jdcloud.com/anthropic") is False


def test_resolve_auto_uses_host():
    assert resolve_auth_scheme("https://api.anthropic.com", AUTH_SCHEME_AUTO) == AUTH_SCHEME_XAPIKEY
    assert resolve_auth_scheme("http://ai-api.jdcloud.com/anthropic", AUTH_SCHEME_AUTO) == AUTH_SCHEME_BEARER


def test_resolve_manual_overrides_host():
    # 手动指定压过 host 判定
    assert resolve_auth_scheme("https://api.anthropic.com", AUTH_SCHEME_BEARER) == AUTH_SCHEME_BEARER
    assert resolve_auth_scheme("http://ai-api.jdcloud.com/anthropic", AUTH_SCHEME_XAPIKEY) == AUTH_SCHEME_XAPIKEY


def test_normalize_bearer_moves_key_to_auth_token():
    out = normalize_anthropic_auth(
        {"ANTHROPIC_API_KEY": "pk-secret", "ANTHROPIC_BASE_URL": "http://ai-api.jdcloud.com/anthropic", "ANTHROPIC_MODEL": "m"},
        AUTH_SCHEME_AUTO,
    )
    assert out["ANTHROPIC_AUTH_TOKEN"] == "pk-secret"
    assert "ANTHROPIC_API_KEY" not in out
    assert out["ANTHROPIC_MODEL"] == "m"


def test_normalize_xapikey_keeps_api_key():
    out = normalize_anthropic_auth(
        {"ANTHROPIC_API_KEY": "sk-ant-x", "ANTHROPIC_BASE_URL": "https://api.anthropic.com"},
        AUTH_SCHEME_AUTO,
    )
    assert out["ANTHROPIC_API_KEY"] == "sk-ant-x"
    assert "ANTHROPIC_AUTH_TOKEN" not in out


def test_normalize_is_mutually_exclusive_from_either_carrier():
    # key 可能来自任一字段(编辑回填场景),结果永远只留一个
    out = normalize_anthropic_auth(
        {"ANTHROPIC_AUTH_TOKEN": "tok", "ANTHROPIC_BASE_URL": "http://gw.example.com"},
        AUTH_SCHEME_AUTO,
    )
    assert out["ANTHROPIC_AUTH_TOKEN"] == "tok"
    assert "ANTHROPIC_API_KEY" not in out


def test_normalize_blank_key_leaves_both_absent():
    out = normalize_anthropic_auth({"ANTHROPIC_BASE_URL": "https://api.anthropic.com"}, AUTH_SCHEME_AUTO)
    assert "ANTHROPIC_API_KEY" not in out
    assert "ANTHROPIC_AUTH_TOKEN" not in out
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_anthropic_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.joysafeter_domain.llm.anthropic_auth'`

- [ ] **Step 3: 写实现**

```python
# backend/app/joysafeter_domain/llm/anthropic_auth.py
"""Single authoritative resolver for the anthropic auth scheme.

Anthropic-family credentials can authenticate two ways, which the sandbox
egress (Envoy) injects from two different env keys:
  - ANTHROPIC_API_KEY   -> x-api-key header            (official api.anthropic.com)
  - ANTHROPIC_AUTH_TOKEN -> Authorization: Bearer header (compatible gateways)
The UI collects one key + an intent (auto/xapikey/bearer). This module resolves
the intent to a concrete scheme and rewrites the stored env map so the key lands
in exactly the right field. All credential write/test paths call this so the
tested header always matches the runtime-injected header.
"""

from __future__ import annotations

from urllib.parse import urlparse

OFFICIAL_ANTHROPIC_HOST = "api.anthropic.com"

ANTHROPIC_API_KEY = "ANTHROPIC_API_KEY"
ANTHROPIC_AUTH_TOKEN = "ANTHROPIC_AUTH_TOKEN"
ANTHROPIC_BASE_URL = "ANTHROPIC_BASE_URL"

AUTH_SCHEME_AUTO = "auto"
AUTH_SCHEME_XAPIKEY = "xapikey"
AUTH_SCHEME_BEARER = "bearer"


def _host_of(base_url: str) -> str:
    raw = (base_url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "http://" + raw
    return (urlparse(raw).hostname or "").lower()


def is_official_anthropic(base_url: str) -> bool:
    host = _host_of(base_url)
    return host == "" or host == OFFICIAL_ANTHROPIC_HOST


def resolve_auth_scheme(base_url: str, requested: str) -> str:
    if requested in (AUTH_SCHEME_XAPIKEY, AUTH_SCHEME_BEARER):
        return requested
    return AUTH_SCHEME_XAPIKEY if is_official_anthropic(base_url) else AUTH_SCHEME_BEARER


def normalize_anthropic_auth(data: dict[str, str], requested_scheme: str) -> dict[str, str]:
    result = dict(data)
    key = (result.get(ANTHROPIC_API_KEY) or result.get(ANTHROPIC_AUTH_TOKEN) or "").strip()
    scheme = resolve_auth_scheme(result.get(ANTHROPIC_BASE_URL, ""), requested_scheme)
    result.pop(ANTHROPIC_API_KEY, None)
    result.pop(ANTHROPIC_AUTH_TOKEN, None)
    if key:
        if scheme == AUTH_SCHEME_BEARER:
            result[ANTHROPIC_AUTH_TOKEN] = key
        else:
            result[ANTHROPIC_API_KEY] = key
    return result
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_anthropic_auth.py -v`
Expected: PASS(7 passed)

- [ ] **Step 5: 提交**

```bash
git add backend/app/joysafeter_domain/llm/anthropic_auth.py backend/tests/test_anthropic_auth.py
git commit -m "feat(credentials): add authoritative anthropic auth-scheme resolver"
```

---

### Task 2: 把解析器接进 credentials create/update/test 三入口

**Files:**
- Modify: `backend/app/joysafeter_api/api/v1/credentials.py`(create、update 处理器 与 `_test_credential_connectivity`;请求模型加 `auth_scheme`)
- Test: `backend/tests/test_credentials_anthropic_auth_scheme.py`

**Interfaces:**
- Consumes: `normalize_anthropic_auth`, `AUTH_SCHEME_AUTO`(Task 1)
- Produces: create/update/test 请求体新增可选字段 `auth_scheme: str = "auto"`;provider=="anthropic" 时服务端在校验/持久化/连通性测试前调用 `normalize_anthropic_auth(data, auth_scheme)` 改写 `data`。

- [ ] **Step 1: 定位接缝**

Run: `cd backend && grep -n "class .*Request\|auth_scheme\|def create\|def update\|validate_credential_data\|_test_credential_connectivity\|req.data\|\.data" app/joysafeter_api/api/v1/credentials.py | head -40`
Expected: 看到 create/update 处理器、`_test_credential_connectivity(req)`、以及承载 `data` 的 Pydantic 请求模型(create/update/test 三个)。记下模型类名与处理器函数名。

- [ ] **Step 2: 写失败测试(用既有 httpx AsyncClient / TestClient 夹具)**

先确认测试夹具风格:`cd backend && grep -rn "AsyncClient\|TestClient\|async def test_.*client" tests/test_credentials*.py | head`。按既有风格写:

```python
# backend/tests/test_credentials_anthropic_auth_scheme.py
# 用与 tests/ 里其它 credentials 测试相同的 client / auth 夹具。
# 断言:创建 anthropic 凭据、auth_scheme=auto、base_url 指向非官方网关时,
# 持久化后的 data 里 ANTHROPIC_AUTH_TOKEN 有值、ANTHROPIC_API_KEY 不存在。
import pytest


@pytest.mark.asyncio
async def test_create_anthropic_auto_gateway_stores_auth_token(client, auth_headers):
    payload = {
        "kind": "model",
        "name": "jd-claude",
        "provider": "anthropic",
        "protocol": "anthropic_messages",
        "auth_scheme": "auto",
        "data": {
            "ANTHROPIC_API_KEY": "pk-jd-secret",
            "ANTHROPIC_BASE_URL": "http://ai-api.jdcloud.com/anthropic",
            "ANTHROPIC_MODEL": "claude-3-5-sonnet",
        },
        "is_default": False,
    }
    resp = await client.post("/api/v1/credentials", json=payload, headers=auth_headers)
    assert resp.status_code == 201, resp.text
    keys = set(resp.json()["data"].keys())
    assert "ANTHROPIC_AUTH_TOKEN" in keys
    assert "ANTHROPIC_API_KEY" not in keys


@pytest.mark.asyncio
async def test_create_anthropic_auto_official_stores_api_key(client, auth_headers):
    payload = {
        "kind": "model",
        "name": "official-claude",
        "provider": "anthropic",
        "protocol": "anthropic_messages",
        "auth_scheme": "auto",
        "data": {
            "ANTHROPIC_API_KEY": "sk-ant-secret",
            "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
            "ANTHROPIC_MODEL": "claude-3-5-sonnet",
        },
        "is_default": False,
    }
    resp = await client.post("/api/v1/credentials", json=payload, headers=auth_headers)
    assert resp.status_code == 201, resp.text
    keys = set(resp.json()["data"].keys())
    assert "ANTHROPIC_API_KEY" in keys
    assert "ANTHROPIC_AUTH_TOKEN" not in keys
```

> 说明:response `data` 是脱敏后的键值(见 `_credential_response`),键名保留,值被 mask;断言只看键集合即可。若既有 client 夹具名不同(如 `async_client`),用实际名替换。

- [ ] **Step 3: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_credentials_anthropic_auth_scheme.py -v`
Expected: FAIL — auto 网关场景当前会原样保留 `ANTHROPIC_API_KEY`,断言 `ANTHROPIC_AUTH_TOKEN in keys` 失败(或请求模型不认 `auth_scheme` 字段而报 422)。

- [ ] **Step 4: 实现**

1) 在文件顶部导入:
```python
from app.joysafeter_domain.llm.anthropic_auth import AUTH_SCHEME_AUTO, normalize_anthropic_auth
```
2) 给 create、update、test 三个请求 Pydantic 模型各加一个可选字段(放在已有 `data` 字段旁):
```python
    auth_scheme: str = AUTH_SCHEME_AUTO
```
3) 在 create 与 update 处理器里,**在 `validate_credential_data` / 持久化之前**,对 anthropic 归一化。紧邻已有取 `data` 的位置插入:
```python
    if provider == "anthropic":
        data = normalize_anthropic_auth(data, req.auth_scheme)
```
(`provider`/`data` 用该处理器里已有的局部变量名;若 data 来自 `req.data`,先 `data = {str(k): str(v) for k, v in (req.data or {}).items()}` 再归一化 —— 参照 `_test_credential_connectivity` 第 208 行既有写法。)
4) 在 `_test_credential_connectivity(req)` 开头(第 208 行 `data = {...}` 之后)插入同样两行,保证「测试用的头」= 「运行时注入的头」:
```python
    if provider == "anthropic":
        data = normalize_anthropic_auth(data, req.auth_scheme)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_credentials_anthropic_auth_scheme.py -v`
Expected: PASS(2 passed)

- [ ] **Step 6: 跑 credentials 相关既有测试确认没回归**

Run: `cd backend && uv run pytest tests/ -k credential -q`
Expected: 全绿(既有用例不受影响;归一化仅在 provider==anthropic 生效)。

- [ ] **Step 7: 提交**

```bash
git add backend/app/joysafeter_api/api/v1/credentials.py backend/tests/test_credentials_anthropic_auth_scheme.py
git commit -m "feat(credentials): resolve anthropic auth scheme on create/update/test"
```

---

### Task 3: catalog yaml 文案/可见性 + 双端 parse 校验

**Files:**
- Modify: `backend/config/llm_catalog.yaml`(`credential_profiles: anthropic_standard`,行 33–56)
- Test:(复用)`cd backend && uv run pytest -k catalog` 与 Rust `cargo` 构建

**Interfaces:**
- Consumes: 无新符号。仅调整 `anthropic_standard` profile 的字段 `label`/`help_text`/`advanced`,不新增/删除字段 key(保持 Python pydantic 与 Rust serde 双端兼容)。

- [ ] **Step 1: 读现状**

Run: `sed -n '32,56p' backend/config/llm_catalog.yaml`
Expected: 看到 `anthropic_standard` 的四个字段与 `required_any_of: [[ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN]]`。

- [ ] **Step 2: 改文案/可见性(不删字段、不加新 key)**

把 `anthropic_standard` 段改为(仅动 label/help_text/advanced 与 base_url 可见性;字段 key、`required_any_of`、`base_url_key`、`model_key` 保持不变以确保双端解析不变):
```yaml
  - id: anthropic_standard
    fields:
      - key: ANTHROPIC_API_KEY
        label: API Key
        type: secret
        help_text: 官方 Anthropic 用 x-api-key 鉴权;中转网关一般用 Bearer(见鉴权方式)。
      - key: ANTHROPIC_AUTH_TOKEN
        label: Auth Token
        type: secret
        help_text: Bearer token(Anthropic 兼容中转网关)。表单会按鉴权方式自动使用其一。
        advanced: true
      - key: ANTHROPIC_BASE_URL
        label: Base URL
        type: url
        placeholder: https://api.anthropic.com
      - key: ANTHROPIC_MODEL
        label: Model
        type: text
        help_text: 上游真实模型 ID(而非显示名),如 claude-3-5-sonnet-...。
    required_any_of:
      - [ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN]
    base_url_key: ANTHROPIC_BASE_URL
    model_key: ANTHROPIC_MODEL
```
(把 `ANTHROPIC_BASE_URL` 的 `advanced: true` 去掉 —— base_url 现在参与自动判定,应常驻可见。)

- [ ] **Step 3: Python 侧校验 catalog 仍能加载**

Run: `cd backend && uv run pytest -k catalog -q`
Expected: PASS(`load_llm_catalog` / catalog 校验测试通过)。

- [ ] **Step 4: Rust 侧校验仍能 include_str! 解析**

Run: `cd backend/app/joysafeter_orchestrator_rs && cargo build 2>&1 | tail -5`
Expected: 构建成功(`llm_catalog.rs` 的 `include_str!` 解析改后的 yaml 无 serde 报错)。

- [ ] **Step 5: 提交**

```bash
git add backend/config/llm_catalog.yaml
git commit -m "docs(catalog): clarify anthropic auth/model help text, unhide base_url"
```

---

### Task 4: 前端「单 key + 鉴权方式开关」控件与保存映射

**Files:**
- Modify: `frontend/components/managed/llm/llm-secret-configurator.tsx`
- Create: `frontend/lib/managed/anthropic-auth.ts`(前端侧预览用的同规则判定 + 类型)
- Test: `frontend/lib/managed/anthropic-auth.test.ts`、`frontend/components/managed/llm/llm-secret-configurator.test.tsx`(补用例)

**Interfaces:**
- Consumes: 后端 `auth_scheme` 请求字段(Task 2);catalog fields(`LlmCredentialField`)。
- Produces:
  - `frontend/lib/managed/anthropic-auth.ts`:`type AnthropicAuthScheme = 'auto' | 'xapikey' | 'bearer'`;`resolveAnthropicScheme(baseUrl: string, requested: AnthropicAuthScheme): 'xapikey' | 'bearer'`;`inferSchemeFromValues(values: Record<string,string>): AnthropicAuthScheme`(编辑回填:AUTH_TOKEN 非空→'bearer',API_KEY 非空→'xapikey',否则 'auto')。
  - 提交 `/credentials` 时 body 带 `auth_scheme`,且 `data['ANTHROPIC_API_KEY']` 作为单一 key 载体(后端再归一化)。

- [ ] **Step 1: 写前端判定单测(失败)**

```ts
// frontend/lib/managed/anthropic-auth.test.ts
import { describe, expect, it } from 'vitest'
import { inferSchemeFromValues, resolveAnthropicScheme } from './anthropic-auth'

describe('resolveAnthropicScheme', () => {
  it('auto: official host -> xapikey', () => {
    expect(resolveAnthropicScheme('https://api.anthropic.com', 'auto')).toBe('xapikey')
    expect(resolveAnthropicScheme('', 'auto')).toBe('xapikey')
  })
  it('auto: gateway host -> bearer', () => {
    expect(resolveAnthropicScheme('http://ai-api.jdcloud.com/anthropic', 'auto')).toBe('bearer')
  })
  it('manual overrides host', () => {
    expect(resolveAnthropicScheme('https://api.anthropic.com', 'bearer')).toBe('bearer')
    expect(resolveAnthropicScheme('http://gw.example.com', 'xapikey')).toBe('xapikey')
  })
})

describe('inferSchemeFromValues', () => {
  it('reads back stored field', () => {
    expect(inferSchemeFromValues({ ANTHROPIC_AUTH_TOKEN: 'tok' })).toBe('bearer')
    expect(inferSchemeFromValues({ ANTHROPIC_API_KEY: 'k' })).toBe('xapikey')
    expect(inferSchemeFromValues({})).toBe('auto')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run lib/managed/anthropic-auth.test.ts`
Expected: FAIL — 模块不存在。

- [ ] **Step 3: 实现前端判定模块**

```ts
// frontend/lib/managed/anthropic-auth.ts
export type AnthropicAuthScheme = 'auto' | 'xapikey' | 'bearer'

const OFFICIAL_HOST = 'api.anthropic.com'

function hostOf(baseUrl: string): string {
  const raw = (baseUrl || '').trim()
  if (!raw) return ''
  try {
    return new URL(raw.includes('://') ? raw : `http://${raw}`).hostname.toLowerCase()
  } catch {
    return ''
  }
}

export function isOfficialAnthropic(baseUrl: string): boolean {
  const host = hostOf(baseUrl)
  return host === '' || host === OFFICIAL_HOST
}

export function resolveAnthropicScheme(
  baseUrl: string,
  requested: AnthropicAuthScheme,
): 'xapikey' | 'bearer' {
  if (requested === 'xapikey' || requested === 'bearer') return requested
  return isOfficialAnthropic(baseUrl) ? 'xapikey' : 'bearer'
}

export function inferSchemeFromValues(values: Record<string, string>): AnthropicAuthScheme {
  if ((values.ANTHROPIC_AUTH_TOKEN || '').trim()) return 'bearer'
  if ((values.ANTHROPIC_API_KEY || '').trim()) return 'xapikey'
  return 'auto'
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run lib/managed/anthropic-auth.test.ts`
Expected: PASS。

- [ ] **Step 5: 在 configurator 里对 anthropic 定制渲染**

在 `llm-secret-configurator.tsx`:
1) import:`import { type AnthropicAuthScheme, inferSchemeFromValues, resolveAnthropicScheme } from '@/lib/managed/anthropic-auth'`
2) 新增 state:`const [authScheme, setAuthScheme] = useState<AnthropicAuthScheme>('auto')`
3) 判定当前 profile 是否 anthropic:`const isAnthropic = selectedOption?.credentialProfile.id === 'anthropic_standard'`
4) `isAnthropic` 时:在 `visibleFields` 渲染里,**跳过** `ANTHROPIC_AUTH_TOKEN` 字段(不再渲染第二个裸密钥框),把 `ANTHROPIC_API_KEY` 作为唯一 key 输入框;在其下渲染鉴权方式 `select`(三态 `auto/xapikey/bearer`,`value={authScheme}` `onChange` setAuthScheme),并显示 `resolveAnthropicScheme(values['ANTHROPIC_BASE_URL'] ?? '', authScheme)` 的实时结果小字。
5) `selectedOption` 变化(编辑回填)时:`setAuthScheme(inferSchemeFromValues(values))`(在既有重置 `values` 的 `useEffect` 里补一行)。
6) 提交 `createSecret` 的 body 里补 `auth_scheme: isAnthropic ? authScheme : undefined`;`testConnection` 的 `/credentials/test` body 同样补 `auth_scheme`。
7) `data` 提交保持:单 key 值写在 `values['ANTHROPIC_API_KEY']`(载体),后端归一化到正确字段。

- [ ] **Step 6: 补 configurator 组件测试**

在 `llm-secret-configurator.test.tsx` 增用例:选中 anthropic profile 时,DOM 中只出现一个密钥输入(不出现独立的 Auth Token 输入),出现鉴权方式选择器;改 base_url 为 jdcloud 时预览显示 Bearer。用既有测试里的 catalog mock 风格。

Run: `cd frontend && npx vitest run components/managed/llm/llm-secret-configurator.test.tsx`
Expected: PASS。

- [ ] **Step 7: 类型检查 + 提交**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无错误。
```bash
git add frontend/lib/managed/anthropic-auth.ts frontend/lib/managed/anthropic-auth.test.ts frontend/components/managed/llm/llm-secret-configurator.tsx frontend/components/managed/llm/llm-secret-configurator.test.tsx
git commit -m "feat(llm): single key + auth-scheme switch for anthropic credentials"
```

---

### Task 5: 页面自洽 + i18n(撤裸字段、统一措辞、术语一致)

**Files:**
- Modify: `frontend/lib/managed/secret-keys.ts`(anthropic 分组字段呈现)
- Modify: i18n 文案文件(`frontend/lib/i18n/locales/zh.ts` 与 `en.ts`,或既有 i18n 结构下 `managed.llm.*` 所在文件)
- Test:(复用)i18n 术语一致性测试 `frontend/lib/i18n/credential-terminology.test.ts`;凭据详情/列表若有渲染鉴权信息的组件,补一致性断言

**Interfaces:**
- Consumes: Task 4 的开关三态。
- Produces: `managed.llm.authScheme` 系列 i18n key(label + 三态选项 + 实时预览文案),中英齐全。

- [ ] **Step 1: 定位所有仍暴露双鉴权裸字段/旧文案处**

Run: `cd frontend && grep -rn "ANTHROPIC_AUTH_TOKEN\|Auth Token\|authScheme\|managed.llm" lib components app --include=*.ts --include=*.tsx | grep -iv test | head -40`
Expected: 列出 `secret-keys.ts` 分组、任何详情/列表展示、i18n 文案位置。逐一核对不再单独渲染 Auth Token 裸框。

- [ ] **Step 2: 加 i18n 文案(中英)**

在 `managed.llm` 命名空间下新增(zh 与 en 同步):
```
authScheme: '鉴权方式' / 'Auth method'
authSchemeAuto: '自动(按接口地址判断)' / 'Auto (from Base URL)'
authSchemeApiKey: 'API Key(官方 Anthropic)' / 'API Key (official Anthropic)'
authSchemeBearer: 'Bearer(中转网关)' / 'Bearer (compatible gateway)'
authSchemePreviewApiKey: '当前将使用 API Key 方式' / 'Will use API Key auth'
authSchemePreviewBearer: '当前将使用 Bearer 方式' / 'Will use Bearer auth'
```
把 Task 4 配置器里的硬编码文案换成 `t('managed.llm.authScheme...')`。

- [ ] **Step 3: secret-keys.ts 分组对齐**

Run: `sed -n '10,27p' frontend/lib/managed/secret-keys.ts`
把 anthropic 分组注释/呈现与"单 key + 开关"对齐(该文件仍可保留 keys 数组用于其它用途,但不得驱动出第二个可编辑的 Auth Token 裸框;实际渲染以 Task 4 的 configurator 为准)。

- [ ] **Step 4: 跑术语一致性 + i18n 清单测试**

Run: `cd frontend && npx vitest run lib/i18n/credential-terminology.test.ts`
Expected: PASS(新增 key 中英齐全、术语合规)。

- [ ] **Step 5: 全量前端类型 + 单测**

Run: `cd frontend && npx tsc --noEmit && npx vitest run`
Expected: 全绿。

- [ ] **Step 6: 提交**

```bash
git add frontend/lib/managed/secret-keys.ts frontend/lib/i18n
git commit -m "i18n(llm): auth-scheme copy + anthropic page self-consistency"
```

---

### Task 6: 后端全量回归

**Files:** 无改动,仅验证。

- [ ] **Step 1: 后端全量**

Run: `cd backend && uv run pytest -q`
Expected: 全绿(重点:credentials、catalog、anthropic_auth)。

- [ ] **Step 2: Rust orchestrator 测试**

Run: `cd backend/app/joysafeter_orchestrator_rs && cargo test 2>&1 | tail -15`
Expected: 全绿(注入映射未改,catalog 仍解析)。

- [ ] **Step 3:(无提交,纯验证闸)** 若有红,回到对应 Task 修复再继续。

---

### Task 7: 端到端真实会话验收闸(完成的唯一判据)

**Files:** 无。手动/脚本验证。

**约束:** 单测/连接测试通过 **不等于** 完成;必须真实会话经 Envoy 返回 200。取证陷阱见
`docs/superpowers/specs/2026-08-17-anthropic-auth-scheme-guidance-design.md` 的测试节 + 相关调试备忘
(runner `127.0.0.1:3128` 桥仅任务活跃时监听;127.0.0.1 免密假阳性;orchestrator 直连 503 内网不可达)。

- [ ] **Step 1: 重建并起本地栈(若未运行)**

Run: `cd deploy && ./deploy.sh local`(或仅重建 api/frontend:`docker compose up -d --no-build --force-recreate api frontend`)
Expected: api `Application startup complete`,frontend 可访问。

- [ ] **Step 2: 前端建一条指向 Bearer 网关(京东云)的 anthropic 模型接入**

在"模型接入"新建 anthropic 凭据:填 API Key、Base URL 指向 `http://ai-api.jdcloud.com/anthropic`、鉴权方式留"自动"、Model 填真实 id。保存。

- [ ] **Step 3: DB 确认落到 AUTH_TOKEN(后端权威生效)**

Run:
```bash
docker exec -e PGPASSWORD=postgres joysafeter-db psql -U postgres -d joysafeter -tAc \
"SELECT jsonb_object_keys(data) FROM joysafeter_credentials WHERE kind='model' AND name='<刚建的名字>' AND deleted_at IS NULL;"
```
Expected: 出现 `ANTHROPIC_AUTH_TOKEN`,不出现 `ANTHROPIC_API_KEY`。

- [ ] **Step 4: 发起真实会话,抓 Envoy 出站状态**

用该凭据发起一次会话;任务活跃窗口内:
```bash
docker logs joysafeter-envoy 2>&1 | grep 'ai-api.jdcloud.com' | tail -3
```
Expected: `POST /anthropic/v1/messages ... status:200`(不再是 401/400)。会话在前端有正常回复。

- [ ] **Step 5: 判定**

- 200 且会话正常回复 → **完成**。
- 仍 401/400 → 未完成:按 spec「失败可读性」核对解析结果,回到 Task 2/4 修,不得因单测绿就宣布完成。
