import { cleanup, render } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Credential } from '@/types/managed'

const { localeState } = vi.hoisted(() => ({
  localeState: { current: 'en' as 'en' | 'zh' },
}))

vi.mock('@/lib/i18n', async () => {
  const { default: en } = await import('@/lib/i18n/locales/en')
  const { default: zh } = await import('@/lib/i18n/locales/zh')
  const catalogs = { en: en.translation, zh: zh.translation }
  const resolve = (key: string) =>
    key.split('.').reduce<unknown>((value, segment) => {
      if (typeof value !== 'object' || value === null) return undefined
      return (value as Record<string, unknown>)[segment]
    }, catalogs[localeState.current])
  return {
    useTranslation: () => ({
      t: (key: string) => {
        const value = resolve(key)
        return typeof value === 'string' ? value : key
      },
    }),
  }
})

vi.mock('@/components/managed/shared/copy-button', () => ({
  CopyButton: () => null,
}))

vi.mock('@/components/managed/shared/field-help', () => ({
  FieldHelp: ({ text }: { text: string }) => <span>{text}</span>,
}))

vi.mock('@/components/ui/input', () => ({
  Input: (props: React.InputHTMLAttributes<HTMLInputElement>) => <input {...props} />,
}))

vi.mock('@/components/ui/textarea', () => ({
  Textarea: (props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...props} />,
}))

vi.mock('@/components/ui/label', () => ({
  Label: ({ children }: { children: ReactNode }) => <label>{children}</label>,
}))

vi.mock('@/components/ui/select', () => ({
  Select: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectItem: ({ children, value }: { children: ReactNode; value: string }) => (
    <div role="option" aria-selected="false" data-value={value}>
      {children}
    </div>
  ),
  SelectTrigger: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectValue: () => null,
}))

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement

import {
  buildEgressServices,
  EgressServicesEditor,
  emptyEgressService,
  serviceToForm,
  validateEgressServiceForms,
} from './environments-egress-editor'

function genericSecret(name: string, id: string): Credential {
  return {
    id: id as Credential['id'],
    name,
    kind: 'service',
    provider: null,
    protocol: null,
    model: null,
    compatible_engine_ids: [],
    is_default: false,
    data: { TOKEN: 'value' },
    created_at: '2030-01-01T00:00:00Z',
    updated_at: '2030-01-01T00:00:00Z',
  }
}

const CRED_A = 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f020'
const CRED_B = 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f021'
const CRED_C = 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f022'

describe('EgressServicesEditor terminology', () => {
  afterEach(cleanup)

  it('round-trips Agent Identity without a static credential', () => {
    const service = buildEgressServices([
      {
        ...emptyEgressService(),
        name: 'crm',
        baseUrl: 'https://crm.example.com/api/',
        authSource: 'agent_identity',
        allowedPaths: '/api/customer/detail\n/api/customer/work/',
      },
    ])[0]

    expect(service).toEqual({
      name: 'crm',
      kind: 'external',
      exposure: 'placeholder',
      base_url: 'https://crm.example.com/api/',
      auth_source: 'agent_identity',
      allowed_paths: ['/api/customer/detail', '/api/customer/work/'],
    })
    expect(serviceToForm(service).authSource).toBe('agent_identity')
  })

  it('defaults an empty Agent Identity path list to the service root', () => {
    const service = buildEgressServices([
      {
        ...emptyEgressService(),
        name: 'crm',
        baseUrl: 'http://crm.internal:8080/api/',
        authSource: 'agent_identity',
      },
    ])[0]

    expect(service?.allowed_paths).toEqual(['/'])
  })

  it('keeps static routes on canonical credential_ref', () => {
    const service = buildEgressServices([
      {
        ...emptyEgressService(),
        name: 'crm',
        baseUrl: 'https://crm.example.com/api/',
        credentialRef: CRED_A,
      },
    ])[0]

    expect(service).toMatchObject({
      auth_source: 'service_credential',
      credential_ref: CRED_A,
    })
    expect(service).not.toHaveProperty('service_credential_id')
  })

  it('requires static credential fields but not Agent Identity credential fields', () => {
    const errors = validateEgressServiceForms(
      [
        {
          ...emptyEgressService(),
          name: 'static-cookie',
          baseUrl: 'https://static.example.com',
          authType: 'cookie',
        },
        {
          ...emptyEgressService(),
          name: 'delegated',
          baseUrl: 'https://identity.example.com',
          authSource: 'agent_identity',
        },
      ],
      { required: 'required', cookieRequired: 'cookie required' },
    )

    expect(errors).toEqual({
      0: { credentialRef: 'required', secretKey: 'cookie required' },
    })
  })

  it.each([
    {
      locale: 'en' as const,
      baseUrlHint:
        'The real third-party endpoint (http or https). In your skill use http:// for the same address; the gateway applies the selected authentication source, then uses the configured protocol upstream.',
      section: 'Authentication',
      skillHint:
        'Use this address in your skill; the selected authentication source is applied automatically.',
    },
    {
      locale: 'zh' as const,
      baseUrlHint:
        '填写第三方接口的真实地址（http 或 https）。Skill 内使用 http 访问同一地址；网关会按所选认证来源自动注入身份，再按配置的协议回源。',
      section: '身份认证',
      skillHint: '在 Skill 中使用此地址访问；平台会自动应用所选的认证来源。',
    },
  ])(
    'renders approved $locale Service Credential semantics',
    ({ locale, baseUrlHint, section, skillHint }) => {
      localeState.current = locale
      const service = {
        ...emptyEgressService(),
        name: 'crm',
        baseUrl: 'https://crm.example.com/api/',
      }
      const { getAllByText, getByText } = render(
        <EgressServicesEditor services={[service]} setServices={vi.fn()} />,
      )

      expect(getByText(baseUrlHint)).toBeTruthy()
      expect(getAllByText(section)).toHaveLength(1)
      expect(getByText(skillHint)).toBeTruthy()
    },
  )

  it('excludes blank and noncanonical historical names from Egress credential options', () => {
    localeState.current = 'en'
    const service = {
      ...emptyEgressService(),
      name: 'crm',
      baseUrl: 'https://crm.example.com/api/',
    }
    const { container } = render(
      <EgressServicesEditor
        services={[service]}
        setServices={vi.fn()}
        secrets={[
          genericSecret('', CRED_A),
          genericSecret(' padded-service ', CRED_B),
          genericSecret('canonical-service', CRED_C),
        ]}
      />,
    )

    expect(container.querySelector(`[data-value="${CRED_C}"]`)).toBeTruthy()
    expect(container.querySelector('[data-value=""]')).toBeNull()
    expect(container.querySelector(`[data-value="${CRED_A}"]`)).toBeNull()
    expect(container.querySelector(`[data-value="${CRED_B}"]`)).toBeNull()
  })
})
