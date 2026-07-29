import { act, cleanup, fireEvent, render } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { toastError } from '@/lib/utils/toast'

vi.mock('@/components/ui/button', () => ({
  Button: ({
    children,
    disabled,
    onClick,
    type = 'button',
  }: {
    children: ReactNode
    disabled?: boolean
    onClick?: () => void
    type?: 'button' | 'submit' | 'reset'
  }) => (
    <button type={type} disabled={disabled} onClick={onClick}>
      {children}
    </button>
  ),
}))

vi.mock('@/components/ui/input', () => ({
  Input: ({ onChange, ...props }: React.InputHTMLAttributes<HTMLInputElement>) => (
    <input
      {...props}
      onChange={onChange}
      onInput={onChange as React.FormEventHandler<HTMLInputElement>}
    />
  ),
}))

vi.mock('@/components/ui/label', () => ({
  Label: ({ children, htmlFor }: { children: ReactNode; htmlFor?: string }) => (
    <label htmlFor={htmlFor}>{children}</label>
  ),
}))

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@/lib/utils/toast', () => ({
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
}))

vi.mock('@/styles/fonts/inter/inter', () => ({
  inter: { className: 'inter' },
}))

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement

describe('SetNewPasswordForm validation lifecycle', () => {
  beforeEach(() => {
    ;(toastError as unknown as ReturnType<typeof vi.fn>).mockReset()
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  it('shows one validation toast for one invalid password submit', async () => {
    const { SetNewPasswordForm } = await import('./reset-password-form')
    const view = render(
      <SetNewPasswordForm
        token="reset-token"
        onSubmit={vi.fn()}
        isSubmitting={false}
        statusType={null}
        statusMessage=""
      />,
    )

    await act(async () => {
      fireEvent.input(view.container.querySelector('#password')!, {
        target: { value: 'short' },
      })
      fireEvent.input(view.container.querySelector('#confirmPassword')!, {
        target: { value: 'short' },
      })
      fireEvent.submit(view.container.querySelector('form')!)
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(toastError).toHaveBeenCalledTimes(1)
    expect(toastError).toHaveBeenCalledWith('auth.passwordMinLength')
  })
})
