import { describe, expect, it } from 'vitest'

import en from './locales/en'
import zh from './locales/zh'

describe('credential domain terminology', () => {
  it('uses the normalized English vocabulary', () => {
    const text = en.translation
    expect(text.nav.secrets).toBe('Connections & Credentials')
    expect(text.nav.vaults).toBe('MCP Credential Sets')
    expect(text.nav.apiKeys).toBe('Project Access Tokens')
    expect(text.managed.secrets.title).toBe('Connections & Credentials')
    expect(text.managed.llm.modelConfiguration).toBe('Model Connection')
    expect(text.managed.llm.genericSecret).toBe('Service Credential')
    expect(text.managed.vaults.title).toBe('MCP Credential Sets')
    expect(text.managed.apiKeys.title).toBe('Project Access Tokens')
    expect(text.managed.triggers.serviceCredential).toBe('Service Credential')
    expect(text.managed.triggers.credentialField).toBe('Credential Field')
  })

  it('uses the normalized Chinese vocabulary', () => {
    const text = zh.translation
    expect(text.nav.secrets).toBe('连接与凭据')
    expect(text.nav.vaults).toBe('MCP 凭据组')
    expect(text.nav.apiKeys).toBe('项目访问令牌')
    expect(text.managed.secrets.title).toBe('连接与凭据')
    expect(text.managed.llm.modelConfiguration).toBe('模型连接')
    expect(text.managed.llm.genericSecret).toBe('服务凭据')
    expect(text.managed.vaults.title).toBe('MCP 凭据组')
    expect(text.managed.apiKeys.title).toBe('项目访问令牌')
    expect(text.managed.triggers.serviceCredential).toBe('服务凭据')
    expect(text.managed.triggers.credentialField).toBe('凭据字段')
  })
})
