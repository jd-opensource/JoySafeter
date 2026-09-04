import { act, renderHook } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import { beforeAll, describe, expect, it } from 'vitest'

import { CREDENTIAL_GROUP_ID, ENVIRONMENT_ID } from '@/test-utils/entity-ids'

import { useQuickstartSecurityFlow } from './use-quickstart-security-flow'

beforeAll(() => {
  if (typeof document === 'undefined') {
    const dom = new JSDOM('<!doctype html><html><body></body></html>')
    Object.assign(globalThis, {
      window: dom.window,
      document: dom.window.document,
      navigator: dom.window.navigator,
    })
  }
})

function populateFlow(result: ReturnType<typeof renderSecurityFlow>['result']) {
  act(() => {
    result.current.environment.setSubStep('hosts')
    result.current.environment.setAnswers({
      choiceLabel: 'Create environment',
      networkingLabel: 'Limited access',
    })
    result.current.environment.setNetworkingType('full')
    result.current.environment.setHosts('example.com')
    result.current.environment.setPendingId(ENVIRONMENT_ID)
    result.current.credentialGroup.setSubStep('name')
    result.current.credentialGroup.setAnswers({ choiceLabel: 'Create credential group' })
    result.current.credentialGroup.setName('Quickstart credentials')
    result.current.credentialGroup.setCredentials([
      {
        name: 'GitHub token',
        mcpServerUrl: 'https://mcp.example.com/sse',
        authRequirement: 'required',
        tokenValue: 'secret',
      },
    ])
    result.current.credentialGroup.setPendingId(CREDENTIAL_GROUP_ID)
  })
}

function renderSecurityFlow(
  scopeKey = 'org-a/project-a',
  suggestedAllowlist = '',
  recommendedMcpServers: Array<{
    name: string
    url: string
    authRequirement: 'required' | 'optional' | 'none'
  }> = [],
) {
  return renderHook(
    ({ scope, allowlist, mcpServers }) =>
      useQuickstartSecurityFlow({
        scopeKey: scope,
        suggestedAllowlist: allowlist,
        recommendedMcpServers: mcpServers,
      }),
    {
      initialProps: {
        scope: scopeKey,
        allowlist: suggestedAllowlist,
        mcpServers: recommendedMcpServers,
      },
    },
  )
}

describe('useQuickstartSecurityFlow', () => {
  it('resets both security resources when the managed scope changes', () => {
    const view = renderSecurityFlow()
    populateFlow(view.result)

    view.rerender({ scope: 'org-a/project-b', allowlist: '', mcpServers: [] })

    expect(view.result.current.environment).toMatchObject({
      subStep: 'choose',
      answers: {},
      networkingType: 'limited',
      hosts: '',
      pendingId: null,
    })
    expect(view.result.current.credentialGroup).toMatchObject({
      subStep: 'choose',
      answers: {},
      name: '',
      credentials: [],
      pendingId: null,
    })
  })

  it('prefills an empty host list when the backend suggestion arrives', () => {
    const view = renderSecurityFlow()

    act(() => view.result.current.environment.setSubStep('hosts'))
    view.rerender({
      scope: 'org-a/project-a',
      allowlist: 'api.github.com, github.com',
      mcpServers: [],
    })

    expect(view.result.current.environment.hosts).toBe('api.github.com, github.com')
  })

  it('does not replace user-entered hosts with a later backend suggestion', () => {
    const view = renderSecurityFlow()

    act(() => {
      view.result.current.environment.setSubStep('hosts')
      view.result.current.environment.setHosts('internal.example.com')
    })
    view.rerender({
      scope: 'org-a/project-a',
      allowlist: 'api.github.com, github.com',
      mcpServers: [],
    })

    expect(view.result.current.environment.hosts).toBe('internal.example.com')
  })

  it('resets environment and credential state when reopening step 4', () => {
    const view = renderSecurityFlow()
    populateFlow(view.result)

    act(() => view.result.current.resetFromStep(4))

    expect(view.result.current.environment.subStep).toBe('choose')
    expect(view.result.current.environment.hosts).toBe('')
    expect(view.result.current.credentialGroup.subStep).toBe('choose')
    expect(view.result.current.credentialGroup.name).toBe('')
  })

  it('preserves environment state and resets credential state when reopening step 5', () => {
    const view = renderSecurityFlow()
    populateFlow(view.result)

    act(() => view.result.current.resetFromStep(5))

    expect(view.result.current.environment).toMatchObject({
      subStep: 'hosts',
      networkingType: 'full',
      hosts: 'example.com',
      pendingId: ENVIRONMENT_ID,
    })
    expect(view.result.current.credentialGroup).toMatchObject({
      subStep: 'choose',
      answers: {},
      name: '',
      credentials: [],
      pendingId: null,
    })
  })

  it('prefills every credential-bearing recommended MCP server', () => {
    const view = renderSecurityFlow()

    view.rerender({
      scope: 'org-a/project-a',
      allowlist: '',
      mcpServers: [
        {
          name: 'GitHub',
          url: 'https://api.github.com/mcp',
          authRequirement: 'required' as const,
        },
        {
          name: 'Optional',
          url: 'https://optional.example.org/mcp',
          authRequirement: 'optional' as const,
        },
      ],
    })

    expect(view.result.current.credentialGroup.credentials).toEqual([
      {
        name: 'GitHub',
        mcpServerUrl: 'https://api.github.com/mcp',
        authRequirement: 'required',
        tokenValue: '',
      },
      {
        name: 'Optional',
        mcpServerUrl: 'https://optional.example.org/mcp',
        authRequirement: 'optional',
        tokenValue: '',
      },
    ])
  })

  it('preserves edited MCP credentials when recommendations refresh', () => {
    const recommended = [
      {
        name: 'GitHub',
        url: 'https://api.github.com/mcp',
        authRequirement: 'required' as const,
      },
    ]
    const view = renderSecurityFlow('org-a/project-a', '', recommended)

    act(() => {
      view.result.current.credentialGroup.updateCredential(0, { tokenValue: 'secret' })
    })
    view.rerender({
      scope: 'org-a/project-a',
      allowlist: '',
      mcpServers: [...recommended],
    })

    expect(view.result.current.credentialGroup.credentials[0].tokenValue).toBe('secret')
  })
})
