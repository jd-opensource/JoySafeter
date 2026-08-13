import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Secret } from '@/types/managed'

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: (key: string, params?: { count?: number }) =>
      key === 'managed.triggers.credentialFieldCount' ? `${params?.count ?? 0} fields` : key,
  }),
}))

vi.mock('@/components/ui/select', async () => {
  const React = await import('react')
  const SelectContext = React.createContext({
    value: '',
    disabled: false,
    onValueChange: (_value: string) => undefined,
  })

  return {
    Select: ({
      children,
      value = '',
      disabled = false,
      onValueChange,
    }: {
      children: ReactNode
      value?: string
      disabled?: boolean
      onValueChange?: (value: string) => void
    }) => (
      <SelectContext.Provider
        value={{ value, disabled, onValueChange: onValueChange ?? (() => undefined) }}
      >
        <div>{children}</div>
      </SelectContext.Provider>
    ),
    SelectContent: ({ children }: { children: ReactNode }) => (
      <div role="listbox">{children}</div>
    ),
    SelectGroup: ({ children }: { children: ReactNode }) => <div role="group">{children}</div>,
    SelectItem: ({ children, value }: { children: ReactNode; value: string }) => {
      const select = React.useContext(SelectContext)
      return (
        <div
          role="option"
          aria-selected={select.value === value}
          aria-disabled={select.disabled}
          data-value={value}
          tabIndex={select.disabled ? -1 : 0}
          onClick={() => {
            if (!select.disabled) select.onValueChange(value)
          }}
        >
          {children}
        </div>
      )
    },
    SelectTrigger: ({
      children,
      disabled = false,
      ...props
    }: {
      children: ReactNode
      disabled?: boolean
      'aria-label'?: string
    }) => {
      const select = React.useContext(SelectContext)
      return (
        <button
          type="button"
          aria-haspopup="listbox"
          disabled={disabled || select.disabled}
          {...props}
        >
          {children}
        </button>
      )
    },
    SelectValue: ({ placeholder }: { placeholder?: ReactNode }) => {
      const select = React.useContext(SelectContext)
      return <span>{select.value || placeholder}</span>
    },
  }
})

import { ServiceCredentialSelect } from './service-credential-select'

function genericSecret(name: string, id: string, keys: string[]): Secret {
  return {
    id: id as Secret['id'],
    name,
    kind: 'service',
    provider: null,
    protocol: null,
    model: null,
    compatible_engine_ids: [],
    is_default: false,
    data: Object.fromEntries(keys.map((key) => [key, 'value'])),
    created_at: '2030-01-01T00:00:00Z',
    updated_at: '2030-01-01T00:00:00Z',
  }
}

const HOOK_ID = 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f020'
const HOOK_ID_B = 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f021'
const HOOK_ID_C = 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f022'
const MISSING_ID = 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f099'

describe('ServiceCredentialSelect', () => {
  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('uses credential ids as option and change values', () => {
    const onChange = vi.fn()
    render(
      <ServiceCredentialSelect
        value=""
        onChange={onChange}
        credentials={[genericSecret('hook-prod', HOOK_ID, ['WEBHOOK_SECRET', 'ALT_TOKEN'])]}
        ariaLabel="Service credential"
      />,
    )

    const trigger = screen.getByRole('button', { name: 'Service credential' })
    const option = screen.getByRole('option', { name: /hook-prod/ })
    expect(trigger).toHaveTextContent('managed.triggers.serviceCredentialPlaceholder')
    expect(option).toHaveAttribute('data-value', HOOK_ID)
    expect(option).toHaveAttribute('aria-selected', 'false')

    fireEvent.click(option)
    expect(onChange).toHaveBeenCalledWith(HOOK_ID)
  })

  it('marks the selected credential id in the labelled trigger', () => {
    render(
      <ServiceCredentialSelect
        value={HOOK_ID}
        onChange={vi.fn()}
        credentials={[genericSecret('hook-prod', HOOK_ID, ['WEBHOOK_SECRET'])]}
        ariaLabel="Service credential"
      />,
    )

    expect(screen.getByRole('option', { name: /hook-prod/ })).toHaveAttribute(
      'aria-selected',
      'true',
    )
  })

  it('keeps an unavailable current credential visible', () => {
    render(
      <ServiceCredentialSelect
        value={MISSING_ID}
        onChange={vi.fn()}
        credentials={[]}
        ariaLabel="Service credential"
      />,
    )

    const option = screen.getByRole('option', { name: new RegExp(MISSING_ID) })
    expect(option).toHaveAttribute('data-value', MISSING_ID)
    expect(option).toHaveTextContent('managed.triggers.serviceCredentialUnavailable')
  })

  it('exposes disabled state and ignores disabled option interaction', () => {
    const onChange = vi.fn()
    render(
      <ServiceCredentialSelect
        value={HOOK_ID}
        onChange={onChange}
        credentials={[genericSecret('hook-prod', HOOK_ID, ['WEBHOOK_SECRET'])]}
        disabled
        ariaLabel="Service credential"
      />,
    )

    expect(screen.getByRole('button', { name: 'Service credential' })).toBeDisabled()
    const option = screen.getByRole('option', { name: /hook-prod/ })
    expect(option).toHaveAttribute('aria-disabled', 'true')

    fireEvent.click(option)
    expect(onChange).not.toHaveBeenCalled()
  })

  it('omits malformed blank keys from the displayed field count', () => {
    render(
      <ServiceCredentialSelect
        value=""
        onChange={vi.fn()}
        credentials={[genericSecret('hook-prod', HOOK_ID, ['', '   ', ' TOKEN '])]}
        ariaLabel="Service credential"
      />,
    )

    expect(screen.getByRole('option', { name: /hook-prod/ })).toHaveTextContent('1 fields')
  })

  it('does not render blank or noncanonical historical resource names as selectable values', () => {
    render(
      <ServiceCredentialSelect
        value={HOOK_ID_B}
        onChange={vi.fn()}
        credentials={[
          genericSecret('', HOOK_ID, ['TOKEN']),
          genericSecret(' padded-service ', HOOK_ID_B, ['TOKEN']),
          genericSecret('canonical-service', HOOK_ID_C, ['TOKEN']),
        ]}
        ariaLabel="Service credential"
      />,
    )

    expect(screen.getAllByRole('option')).toHaveLength(1)
    expect(screen.getByRole('option', { name: /canonical-service/ })).toHaveAttribute(
      'data-value',
      HOOK_ID_C,
    )
  })
})
