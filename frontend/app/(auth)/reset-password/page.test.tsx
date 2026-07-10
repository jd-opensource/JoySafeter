import { act, cleanup, fireEvent, render } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const pushMock = vi.fn()
const resetPasswordMock = vi.fn()

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock }),
  useSearchParams: () => ({
    get: (key: string) => (key === 'token' ? 'reset-token' : null),
  }),
}))

vi.mock('next/link', () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}))

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

vi.mock('@/lib/auth/api-client', () => ({
  authApi: {
    resetPassword: resetPasswordMock,
  },
}))

vi.mock('@/lib/logs/console/logger', () => ({
  createLogger: () => ({
    error: vi.fn(),
  }),
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

vi.mock('@/styles/fonts/soehne/soehne', () => ({
  soehne: { className: 'soehne' },
}))

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

// testing-library's waitFor polls on real timers, which vi.useFakeTimers()
// freezes, so it hangs. Flush microtasks inside act() instead.
async function settle() {
  for (let i = 0; i < 6; i += 1) {
    await act(async () => {
      await Promise.resolve()
    })
  }
}

describe('ResetPasswordPage lifecycle', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    pushMock.mockReset()
    resetPasswordMock.mockReset()
    resetPasswordMock.mockResolvedValue({})
  })

  afterEach(() => {
    cleanup()
    vi.useRealTimers()
  })

  it('does not run the delayed signin redirect after the reset page unmounts', async () => {
    const { default: ResetPasswordPage } = await import('./page')
    const view = render(<ResetPasswordPage />)

    await act(async () => {
      fireEvent.input(view.container.querySelector('#password')!, {
        target: { value: 'Passw0rd!' },
      })
      fireEvent.input(view.container.querySelector('#confirmPassword')!, {
        target: { value: 'Passw0rd!' },
      })
    })

    await act(async () => {
      fireEvent.submit(view.container.querySelector('form')!)
      await Promise.resolve()
    })

    await settle()
    expect(resetPasswordMock).toHaveBeenCalledTimes(1)

    view.unmount()

    await act(async () => {
      vi.advanceTimersByTime(1500)
      await Promise.resolve()
    })

    expect(pushMock).not.toHaveBeenCalled()
  })

  it('does not schedule the signin redirect when reset resolves after unmount', async () => {
    const reset = deferred<Record<string, never>>()
    resetPasswordMock.mockReturnValueOnce(reset.promise)
    const { default: ResetPasswordPage } = await import('./page')
    const view = render(<ResetPasswordPage />)

    await act(async () => {
      fireEvent.input(view.container.querySelector('#password')!, {
        target: { value: 'Passw0rd!' },
      })
      fireEvent.input(view.container.querySelector('#confirmPassword')!, {
        target: { value: 'Passw0rd!' },
      })
    })

    await act(async () => {
      fireEvent.submit(view.container.querySelector('form')!)
      await Promise.resolve()
    })

    await settle()
    expect(resetPasswordMock).toHaveBeenCalledTimes(1)

    view.unmount()

    await act(async () => {
      reset.resolve({})
      await reset.promise
      await Promise.resolve()
    })

    await act(async () => {
      vi.advanceTimersByTime(1500)
      await Promise.resolve()
    })

    expect(pushMock).not.toHaveBeenCalled()
  })
})
