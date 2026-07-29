import { act, cleanup, fireEvent, render } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const pushMock = vi.fn()
const signUpEmailMock = vi.fn()
const searchParamValues: Record<string, string | null> = {
  email: null,
  invite_flow: null,
  redirect: null,
}

type AuthClientMockGlobal = typeof globalThis & {
  __joysafeterAuthClientMock?: {
    signUpEmail?: (...args: unknown[]) => unknown
  }
}

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock }),
  useSearchParams: () => ({
    get: (key: string) => searchParamValues[key] ?? null,
  }),
}))

vi.mock('next/link', () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}))

vi.mock('@/lib/auth/auth-client', () => ({
  client: {
    signUp: {
      email: signUpEmailMock,
    },
  },
  useSession: () => ({}),
}))

vi.mock('@/lib/core/config/env', () => ({
  getEnv: () => 'true',
  isFalsy: (value: string | boolean | number | undefined) =>
    typeof value === 'string' ? value.toLowerCase() === 'false' || value === '0' : value === false,
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
globalThis.FormData = dom.window.FormData
globalThis.sessionStorage = dom.window.sessionStorage

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

describe('SignupForm lifecycle', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    pushMock.mockReset()
    signUpEmailMock.mockReset()
    signUpEmailMock.mockResolvedValue({ data: { user: { id: 'user_1' } }, error: null })
    searchParamValues.email = null
    searchParamValues.invite_flow = null
    searchParamValues.redirect = null
    ;(globalThis as AuthClientMockGlobal).__joysafeterAuthClientMock = {
      signUpEmail: signUpEmailMock,
    }
    sessionStorage.clear()
  })

  afterEach(() => {
    cleanup()
    vi.useRealTimers()
    delete (globalThis as AuthClientMockGlobal).__joysafeterAuthClientMock
  })

  it('does not run the delayed signin redirect after the signup page unmounts', async () => {
    const { default: SignupPage } = await import('./signup-form')
    const view = render(<SignupPage />)

    fireEvent.change(view.container.querySelector('input[name="name"]')!, {
      target: { value: 'Ada Lovelace' },
    })
    fireEvent.change(view.container.querySelector('input[name="email"]')!, {
      target: { value: 'ada@example.com' },
    })
    fireEvent.change(view.container.querySelector('input[name="password"]')!, {
      target: { value: 'Passw0rd!' },
    })

    await act(async () => {
      fireEvent.submit(view.container.querySelector('form')!)
      await Promise.resolve()
    })

    await settle()
    expect(signUpEmailMock).toHaveBeenCalledTimes(1)

    view.unmount()

    await act(async () => {
      vi.advanceTimersByTime(500)
      await Promise.resolve()
    })

    expect(pushMock).not.toHaveBeenCalled()
  })

  it('does not schedule the signin redirect when signup resolves after unmount', async () => {
    const signup = deferred<{ data: { user: { id: string } }; error: null }>()
    signUpEmailMock.mockReturnValueOnce(signup.promise)
    const { default: SignupPage } = await import('./signup-form')
    const view = render(<SignupPage />)

    fireEvent.change(view.container.querySelector('input[name="name"]')!, {
      target: { value: 'Ada Lovelace' },
    })
    fireEvent.change(view.container.querySelector('input[name="email"]')!, {
      target: { value: 'ada@example.com' },
    })
    fireEvent.change(view.container.querySelector('input[name="password"]')!, {
      target: { value: 'Passw0rd!' },
    })

    await act(async () => {
      fireEvent.submit(view.container.querySelector('form')!)
      await Promise.resolve()
    })

    await settle()
    expect(signUpEmailMock).toHaveBeenCalledTimes(1)

    view.unmount()

    await act(async () => {
      signup.resolve({ data: { user: { id: 'user_1' } }, error: null })
      await signup.promise
      await Promise.resolve()
    })

    await act(async () => {
      vi.advanceTimersByTime(500)
      await Promise.resolve()
    })

    expect(pushMock).not.toHaveBeenCalled()
    expect(sessionStorage.getItem('verificationEmail')).toBeNull()
  })

  it('does not persist an unsafe invite redirect after successful signup', async () => {
    searchParamValues.invite_flow = 'true'
    searchParamValues.redirect = '//evil.example/invite/team'

    const { default: SignupPage } = await import('./signup-form')
    const view = render(<SignupPage />)

    fireEvent.change(view.container.querySelector('input[name="name"]')!, {
      target: { value: 'Ada Lovelace' },
    })
    fireEvent.change(view.container.querySelector('input[name="email"]')!, {
      target: { value: 'ada@example.com' },
    })
    fireEvent.change(view.container.querySelector('input[name="password"]')!, {
      target: { value: 'Passw0rd!' },
    })

    await act(async () => {
      fireEvent.submit(view.container.querySelector('form')!)
      await Promise.resolve()
    })

    await settle()
    expect(signUpEmailMock).toHaveBeenCalledTimes(1)

    expect(sessionStorage.getItem('inviteRedirectUrl')).toBeNull()
    expect(sessionStorage.getItem('isInviteFlow')).toBeNull()
  })
})
