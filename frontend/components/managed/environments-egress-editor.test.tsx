import { cleanup, render } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n', async () => {
  const { default: zh } = await import('@/lib/i18n/locales/zh')
  const resolve = (key: string) =>
    key.split('.').reduce<unknown>((value, segment) => {
      if (typeof value !== 'object' || value === null) return undefined
      return (value as Record<string, unknown>)[segment]
    }, zh.translation)
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
  Textarea: (props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) => (
    <textarea {...props} />
  ),
}))

vi.mock('@/components/ui/label', () => ({
  Label: ({ children }: { children: ReactNode }) => <label>{children}</label>,
}))

vi.mock('@/components/ui/select', () => ({
  Select: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectItem: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectTrigger: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectValue: () => null,
}))

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement

import { EgressServicesEditor, emptyEgressService } from './environments-egress-editor'

describe('EgressServicesEditor terminology', () => {
  afterEach(cleanup)

  it('renders approved Chinese Service Credential terminology', () => {
    const service = {
      ...emptyEgressService(),
      name: 'crm',
      baseUrl: 'https://crm.example.com/api/',
    }
    const { getAllByText, getByText } = render(
      <EgressServicesEditor services={[service]} setServices={vi.fn()} />,
    )

    expect(
      getByText(
        '填写第三方接口的真实地址（含 https）。skill 内改用 http 访问同一地址；平台会在网关使用服务凭据注入认证信息，并回源到 https。',
      ),
    ).toBeTruthy()
    expect(getAllByText('服务凭据')).toHaveLength(2)
    expect(getByText('在 skill 中使用此地址访问；服务凭据中的认证信息会自动注入。')).toBeTruthy()
  })
})
