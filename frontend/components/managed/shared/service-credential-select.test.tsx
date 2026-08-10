import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Secret } from '@/types/managed'

const selectState = vi.hoisted(() => ({
  onValueChange: undefined as ((value: string) => void) | undefined,
}))

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@/components/ui/select', () => ({
  Select: ({
    children,
    onValueChange,
  }: {
    children: ReactNode
    onValueChange?: (value: string) => void
  }) => {
    selectState.onValueChange = onValueChange
    return <div>{children}</div>
  },
  SelectContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectGroup: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectItem: ({ children, value }: { children: ReactNode; value: string }) => (
    <button
      type="button"
      role="option"
      data-value={value}
      onClick={() => selectState.onValueChange?.(value)}
    >
      {children}
    </button>
  ),
  SelectTrigger: ({ children, ...props }: { children: ReactNode; 'aria-label'?: string }) => (
    <button type="button" {...props}>
      {children}
    </button>
  ),
  SelectValue: () => null,
}))

import { ServiceCredentialSelect } from './service-credential-select'

function genericSecret(name: string, id: string, keys: string[]): Secret {
  return {
    id: id as Secret['id'],
    name,
    kind: 'generic',
    provider: null,
    protocol: null,
    model: null,
    compatible_engine_ids: [],
    is_default: false,
    keys,
    created_at: '2030-01-01T00:00:00Z',
    updated_at: '2030-01-01T00:00:00Z',
  }
}

describe('ServiceCredentialSelect', () => {
  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('uses Secret resource names as option and change values', () => {
    const onChange = vi.fn()
    render(
      <ServiceCredentialSelect
        value=""
        onChange={onChange}
        credentials={[
          genericSecret(
            'hook-prod',
            'secret_018f6f42-0a51-7cc4-98c8-4f6f0ca5f020',
            ['WEBHOOK_SECRET', 'ALT_TOKEN'],
          ),
        ]}
        ariaLabel="Service credential"
      />,
    )

    const option = screen.getByRole('option', { name: /hook-prod/ })
    expect(option).toHaveAttribute('data-value', 'hook-prod')
    expect(option).not.toHaveAttribute('data-value', 'WEBHOOK_SECRET')

    fireEvent.click(option)
    expect(onChange).toHaveBeenCalledWith('hook-prod')
  })

  it('keeps an unavailable current resource visible', () => {
    render(
      <ServiceCredentialSelect
        value="deleted-hook"
        onChange={vi.fn()}
        credentials={[]}
        ariaLabel="Service credential"
      />,
    )

    const option = screen.getByRole('option', { name: /deleted-hook/ })
    expect(option).toHaveAttribute('data-value', 'deleted-hook')
    expect(option).toHaveTextContent('managed.triggers.serviceCredentialUnavailable')
  })
})
