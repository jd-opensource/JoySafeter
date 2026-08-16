import { act, cleanup, fireEvent, render } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import { StrictMode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const forgetPasswordMock = vi.fn()
const signInEmailMock = vi.fn()
const refetchSessionMock = vi.fn()
const searchParamValues: Record<string, string | null> = {
  bypass_sso: 'true',
  callbackUrl: '/signin#after',
}

type AuthClientMockGlobal = typeof globalThis & {
  __joysafeterAuthClientMock?: {
    forgetPassword?: (...args: unknown[]) => unknown
  }
}

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => ({
    get: (key: string) => searchParamValues[key] ?? null,
  }),
}))

vi.mock('next/link', () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}))

vi.mock('@/components/auth/oauth-buttons', () => ({
  OAuthButtons: () => null,
}))

vi.mock('@/components/ui/button', () => ({
  Button: ({
    children,
    disabled,
    onClick,
    type = 'button',
  }: {
    children: React.ReactNode
    disabled?: boolean
    onClick?: () => void
    type?: 'button' | 'submit' | 'reset'
  }) => (
    <button type={type} disabled={disabled} onClick={onClick}>
      {children}
    </button>
  ),
}))

vi.mock('@/components/ui/dialog', () => ({
  Dialog: ({
    children,
    onOpenChange,
    open,
  }: {
    children: React.ReactNode
    onOpenChange?: (open: boolean) => void
    open: boolean
  }) =>
    open ? (
      <div>
        {children}
        <button type="button" onClick={() => onOpenChange?.(false)}>
          dialog-close
        </button>
      </div>
    ) : null,
  DialogContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogDescription: ({ children }: { children: React.ReactNode }) => <p>{children}</p>,
  DialogHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
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
  Label: ({ children, htmlFor }: { children: React.ReactNode; htmlFor?: string }) => (
    <label htmlFor={htmlFor}>{children}</label>
  ),
}))

vi.mock('@/lib/api-client', () => ({
  ApiError: class ApiError extends Error {
    code?: string
  },
  managedGet: vi.fn(),
}))

vi.mock('@/lib/auth/auth-client', () => ({
  client: {
    forgetPassword: forgetPasswordMock,
    signIn: {
      email: signInEmailMock,
    },
  },
  useSession: () => ({ data: null, isPending: false, refetch: refetchSessionMock }),
}))

vi.mock('@/lib/core/config/env', () => ({
  getEnv: () => 'true',
  isFalsy: (value: string | boolean | number | undefined) =>
    typeof value === 'string' ? value.toLowerCase() === 'false' || value === '0' : value === false,
}))

vi.mock('@/lib/core/utils/urls', () => ({
  getBaseUrl: () => 'http://localhost',
}))

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@/lib/logs/console/logger', () => ({
  createLogger: () => ({
    error: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
  }),
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
globalThis.sessionStorage = dom.window.sessionStorage

import { managedGet } from '@/lib/api-client'

const managedGetMock = managedGet as unknown as ReturnType<typeof vi.fn>

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

function oauthRequests(prefix: string) {
  return managedGetMock.mock.calls.filter(([path]) => String(path).startsWith(prefix))
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

describe('LoginPage lifecycle', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    forgetPasswordMock.mockReset()
    signInEmailMock.mockReset()
    refetchSessionMock.mockReset()
    managedGetMock.mockReset()
    forgetPasswordMock.mockResolvedValue({})
    signInEmailMock.mockResolvedValue({ data: { user: { id: 'user-1' } }, error: null })
    refetchSessionMock.mockResolvedValue(undefined)
    searchParamValues.bypass_sso = 'true'
    searchParamValues.callbackUrl = '/signin#after'
    ;(globalThis as AuthClientMockGlobal).__joysafeterAuthClientMock = {
      forgetPassword: forgetPasswordMock,
    }
    window.history.replaceState({}, '', '/signin')
    sessionStorage.clear()
  })

  afterEach(() => {
    cleanup()
    vi.useRealTimers()
    delete (globalThis as AuthClientMockGlobal).__joysafeterAuthClientMock
  })

  it('does not let an older reset-link timer close a reopened forgot password dialog', async () => {
    const { default: LoginPage } = await import('./login-form')
    const view = render(<LoginPage />)

    fireEvent.click(view.getByText('auth.forgotPassword'))
    await act(async () => {
      fireEvent.input(view.container.querySelector('#reset-email')!, {
        target: { value: 'ada@example.com' },
      })
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(view.getByText('auth.sendResetLink'))
      await Promise.resolve()
    })

    await settle()
    expect(forgetPasswordMock).toHaveBeenCalledTimes(1)

    fireEvent.click(view.getByText('dialog-close'))
    fireEvent.click(view.getByText('auth.forgotPassword'))
    expect(view.getByText('auth.resetPassword')).toBeTruthy()

    await act(async () => {
      vi.advanceTimersByTime(2000)
      await Promise.resolve()
    })

    expect(view.getByText('auth.resetPassword')).toBeTruthy()
  })

  it('does not let a stale reset-link response close a reopened forgot password dialog', async () => {
    const resetRequest = deferred<Record<string, never>>()
    forgetPasswordMock.mockReturnValueOnce(resetRequest.promise)
    const { default: LoginPage } = await import('./login-form')
    const view = render(<LoginPage />)

    fireEvent.click(view.getByText('auth.forgotPassword'))
    await act(async () => {
      fireEvent.input(view.container.querySelector('#reset-email')!, {
        target: { value: 'ada@example.com' },
      })
      await Promise.resolve()
    })

    await act(async () => {
      fireEvent.click(view.getByText('auth.sendResetLink'))
      await Promise.resolve()
    })

    await settle()
    expect(forgetPasswordMock).toHaveBeenCalledTimes(1)

    fireEvent.click(view.getByText('dialog-close'))
    fireEvent.click(view.getByText('auth.forgotPassword'))

    await act(async () => {
      resetRequest.resolve({})
      await resetRequest.promise
      await Promise.resolve()
    })

    await act(async () => {
      vi.advanceTimersByTime(2000)
      await Promise.resolve()
    })

    expect(view.getByText('auth.resetPassword')).toBeTruthy()
  })

  it('does not run the delayed login redirect after the login page unmounts', async () => {
    const { default: LoginPage } = await import('./login-form')
    const view = render(<LoginPage />)

    await act(async () => {
      fireEvent.input(view.container.querySelector('#email')!, {
        target: { value: 'ada@example.com' },
      })
      fireEvent.input(view.container.querySelector('#password')!, {
        target: { value: 'correct-password' },
      })
      fireEvent.submit(view.container.querySelector('form')!)
      await Promise.resolve()
      await Promise.resolve()
    })

    await settle()
    expect(signInEmailMock).toHaveBeenCalledTimes(1)

    view.unmount()

    await act(async () => {
      vi.advanceTimersByTime(50)
      await Promise.resolve()
    })

    expect(window.location.href).toBe('http://localhost/signin')
  })

  it('does not pass a protocol-relative callback URL into email login', async () => {
    searchParamValues.callbackUrl = '//evil.example/path'

    const { default: LoginPage } = await import('./login-form')
    const view = render(<LoginPage />)

    await act(async () => {
      fireEvent.input(view.container.querySelector('#email')!, {
        target: { value: 'ada@example.com' },
      })
      fireEvent.input(view.container.querySelector('#password')!, {
        target: { value: 'correct-password' },
      })
      fireEvent.submit(view.container.querySelector('form')!)
      await Promise.resolve()
      await Promise.resolve()
    })

    await settle()
    expect(signInEmailMock).toHaveBeenCalledTimes(1)

    expect(signInEmailMock.mock.calls[0]?.[0]).toMatchObject({
      callbackURL: '/managed/quickstart',
    })
  })

  it('does not pass an origin-prefix callback URL into email login', async () => {
    searchParamValues.callbackUrl = 'http://localhost.evil.example/path'

    const { default: LoginPage } = await import('./login-form')
    const view = render(<LoginPage />)

    await act(async () => {
      fireEvent.input(view.container.querySelector('#email')!, {
        target: { value: 'ada@example.com' },
      })
      fireEvent.input(view.container.querySelector('#password')!, {
        target: { value: 'correct-password' },
      })
      fireEvent.submit(view.container.querySelector('form')!)
      await Promise.resolve()
      await Promise.resolve()
    })

    await settle()
    expect(signInEmailMock).toHaveBeenCalledTimes(1)

    expect(signInEmailMock.mock.calls[0]?.[0]).toMatchObject({
      callbackURL: '/managed/quickstart',
    })
  })

  it('does not auto-authorize in chooser mode and clears a prior auto-attempt guard', async () => {
    searchParamValues.bypass_sso = null
    searchParamValues.callbackUrl = '/managed/quickstart'
    sessionStorage.setItem('sso_auto_attempted', String(Date.now()))
    managedGetMock.mockResolvedValueOnce({
      providers: [
        { id: 'github', display_name: 'GitHub', icon: 'github' },
        { id: 'jd', display_name: 'JD SSO', icon: 'building' },
      ],
      login_mode: 'chooser',
    })

    const { default: LoginPage } = await import('./login-form')
    render(<LoginPage />)

    await settle()

    expect(managedGetMock).toHaveBeenCalledTimes(1)
    expect(managedGetMock).toHaveBeenCalledWith(
      'auth/oauth/providers',
      expect.objectContaining({
        withAuth: false,
        skipManagedContext: true,
        signal: expect.any(AbortSignal),
      }),
    )
    expect(sessionStorage.getItem('sso_auto_attempted')).toBeNull()
    expect(window.location.href).toBe('http://localhost/signin')
  })

  it('auto-authorizes exactly once with the first backend provider in redirect mode', async () => {
    searchParamValues.bypass_sso = null
    searchParamValues.callbackUrl = '/managed/quickstart'
    managedGetMock
      .mockResolvedValueOnce({
        providers: [
          { id: 'jd', display_name: 'JD SSO', icon: 'building' },
          { id: 'github', display_name: 'GitHub', icon: 'github' },
        ],
        login_mode: 'redirect',
      })
      .mockResolvedValueOnce({
        authorization_url: '/signin#jd-sso',
        state: 'attempt-1',
      })

    const { default: LoginPage } = await import('./login-form')
    const view = render(<LoginPage />)

    await settle()

    expect(managedGetMock).toHaveBeenCalledTimes(2)
    expect(managedGetMock).toHaveBeenNthCalledWith(
      2,
      'auth/oauth/jd?callback_url=%2Fmanaged%2Fquickstart',
      expect.objectContaining({
        withAuth: false,
        skipManagedContext: true,
        signal: expect.any(AbortSignal),
      }),
    )
    expect(
      managedGetMock.mock.calls.some(([path]) => String(path).startsWith('auth/oauth/github')),
    ).toBe(false)
    expect(window.location.href).toBe('http://localhost/signin#jd-sso')

    const committedGuard = sessionStorage.getItem('sso_auto_attempted')
    expect(committedGuard).toBeTruthy()
    view.unmount()
    expect(sessionStorage.getItem('sso_auto_attempted')).toBe(committedGuard)
  })

  it('ignores an overlapping stale provider response after the callback changes', async () => {
    searchParamValues.bypass_sso = null
    searchParamValues.callbackUrl = '/first-callback'
    const firstProviders = deferred<{
      providers: Array<{ id: string; display_name: string; icon: string }>
      login_mode: 'redirect'
    }>()
    const secondProviders = deferred<{
      providers: Array<{ id: string; display_name: string; icon: string }>
      login_mode: 'redirect'
    }>()
    managedGetMock
      .mockReturnValueOnce(firstProviders.promise)
      .mockReturnValueOnce(secondProviders.promise)
      .mockResolvedValueOnce({ authorization_url: '/signin#current-provider', state: 'attempt-2' })

    const { default: LoginPage } = await import('./login-form')
    const view = render(<LoginPage />)

    await settle()
    expect(oauthRequests('auth/oauth/providers')).toHaveLength(1)

    searchParamValues.callbackUrl = '/second-callback'
    view.rerender(<LoginPage />)
    await settle()

    expect(oauthRequests('auth/oauth/providers')).toHaveLength(2)
    expect(oauthRequests('auth/oauth/providers')[0]?.[1]?.signal?.aborted).toBe(true)

    await act(async () => {
      firstProviders.resolve({
        providers: [{ id: 'stale', display_name: 'Stale', icon: 'key' }],
        login_mode: 'redirect',
      })
      await firstProviders.promise
      await Promise.resolve()
    })

    expect(oauthRequests('auth/oauth/stale')).toHaveLength(0)

    await act(async () => {
      secondProviders.resolve({
        providers: [{ id: 'current', display_name: 'Current', icon: 'key' }],
        login_mode: 'redirect',
      })
      await secondProviders.promise
      await Promise.resolve()
    })
    await settle()

    expect(managedGetMock).toHaveBeenCalledWith(
      'auth/oauth/current?callback_url=%2Fsecond-callback',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(window.location.href).toBe('http://localhost/signin#current-provider')
  })

  it('does not let stale authorization resolution navigate or clear the current guard', async () => {
    searchParamValues.bypass_sso = null
    searchParamValues.callbackUrl = '/first-callback'
    const staleAuthorization = deferred<{ authorization_url: string; state: string }>()
    const currentAuthorization = deferred<{ authorization_url: string; state: string }>()
    managedGetMock
      .mockResolvedValueOnce({
        providers: [{ id: 'first', display_name: 'First', icon: 'key' }],
        login_mode: 'redirect',
      })
      .mockReturnValueOnce(staleAuthorization.promise)
      .mockResolvedValueOnce({
        providers: [{ id: 'second', display_name: 'Second', icon: 'key' }],
        login_mode: 'redirect',
      })
      .mockReturnValueOnce(currentAuthorization.promise)

    const { default: LoginPage } = await import('./login-form')
    const view = render(<LoginPage />)

    await settle()
    const staleGuard = sessionStorage.getItem('sso_auto_attempted')
    expect(staleGuard).toBeTruthy()

    searchParamValues.callbackUrl = '/second-callback'
    view.rerender(<LoginPage />)
    await settle()

    const currentGuard = sessionStorage.getItem('sso_auto_attempted')
    expect(currentGuard).toBeTruthy()
    expect(currentGuard).not.toBe(staleGuard)
    expect(oauthRequests('auth/oauth/first')[0]?.[1]?.signal?.aborted).toBe(true)

    await act(async () => {
      staleAuthorization.resolve({ authorization_url: '/signin#stale', state: 'attempt-1' })
      await staleAuthorization.promise
      await Promise.resolve()
    })

    expect(window.location.href).toBe('http://localhost/signin')
    expect(sessionStorage.getItem('sso_auto_attempted')).toBe(currentGuard)

    await act(async () => {
      currentAuthorization.resolve({ authorization_url: '/signin#current', state: 'attempt-2' })
      await currentAuthorization.promise
      await Promise.resolve()
    })

    expect(window.location.href).toBe('http://localhost/signin#current')
    expect(sessionStorage.getItem('sso_auto_attempted')).toBe(currentGuard)
  })

  it('authorizes exactly once with the current callback under StrictMode', async () => {
    searchParamValues.bypass_sso = null
    searchParamValues.callbackUrl = '/strict-current'
    managedGetMock.mockImplementation((path) => {
      if (String(path) === 'auth/oauth/providers') {
        return Promise.resolve({
          providers: [{ id: 'github', display_name: 'GitHub', icon: 'github' }],
          login_mode: 'redirect',
        })
      }
      return Promise.resolve({ authorization_url: '/signin#strict', state: 'attempt-1' })
    })

    const { default: LoginPage } = await import('./login-form')
    render(
      <StrictMode>
        <LoginPage />
      </StrictMode>,
    )

    await settle()

    expect(oauthRequests('auth/oauth/github')).toHaveLength(1)
    expect(oauthRequests('auth/oauth/github')[0]?.[0]).toBe(
      'auth/oauth/github?callback_url=%2Fstrict-current',
    )
    expect(window.location.href).toBe('http://localhost/signin#strict')
  })

  it('keeps the redirect loop guard from authorizing again during its ttl', async () => {
    searchParamValues.bypass_sso = null
    sessionStorage.setItem('sso_auto_attempted', String(Date.now()))
    managedGetMock.mockResolvedValueOnce({
      providers: [{ id: 'jd', display_name: 'JD SSO', icon: 'building' }],
      login_mode: 'redirect',
    })

    const { default: LoginPage } = await import('./login-form')
    render(<LoginPage />)

    await settle()

    expect(managedGetMock).toHaveBeenCalledTimes(1)
    expect(sessionStorage.getItem('sso_auto_attempted')).toBeTruthy()
    expect(window.location.href).toBe('http://localhost/signin')
  })

  it('does not authorize when redirect mode has no providers', async () => {
    searchParamValues.bypass_sso = null
    managedGetMock.mockResolvedValueOnce({ providers: [], login_mode: 'redirect' })

    const { default: LoginPage } = await import('./login-form')
    render(<LoginPage />)

    await settle()

    expect(managedGetMock).toHaveBeenCalledTimes(1)
    expect(sessionStorage.getItem('sso_auto_attempted')).toBeNull()
    expect(window.location.href).toBe('http://localhost/signin')
  })

  it('does not disturb an unowned guard when the provider policy request fails', async () => {
    searchParamValues.bypass_sso = null
    const existingGuard = String(Date.now())
    sessionStorage.setItem('sso_auto_attempted', existingGuard)
    managedGetMock.mockRejectedValueOnce(new Error('provider policy unavailable'))

    const { default: LoginPage } = await import('./login-form')
    render(<LoginPage />)

    await settle()

    expect(managedGetMock).toHaveBeenCalledTimes(1)
    expect(sessionStorage.getItem('sso_auto_attempted')).toBe(existingGuard)
    expect(window.location.href).toBe('http://localhost/signin')
  })

  it.each([
    ['missing', undefined],
    ['invalid', 'auto'],
  ])('fails safe for %s login_mode and clears a stale guard', async (_label, loginMode) => {
    searchParamValues.bypass_sso = null
    sessionStorage.setItem('sso_auto_attempted', `${Date.now()}:older-run`)
    managedGetMock.mockResolvedValueOnce({
      providers: [{ id: 'github', display_name: 'GitHub', icon: 'github' }],
      ...(loginMode === undefined ? {} : { login_mode: loginMode }),
    })

    const { default: LoginPage } = await import('./login-form')
    render(<LoginPage />)

    await settle()

    expect(managedGetMock).toHaveBeenCalledTimes(1)
    expect(sessionStorage.getItem('sso_auto_attempted')).toBeNull()
    expect(window.location.href).toBe('http://localhost/signin')
  })

  it('clears the auto-attempt guard when redirect authorization fails', async () => {
    searchParamValues.bypass_sso = null
    managedGetMock
      .mockResolvedValueOnce({
        providers: [{ id: 'github', display_name: 'GitHub', icon: 'github' }],
        login_mode: 'redirect',
      })
      .mockRejectedValueOnce(new Error('authorization unavailable'))

    const { default: LoginPage } = await import('./login-form')
    render(<LoginPage />)

    await settle()

    expect(managedGetMock).toHaveBeenCalledTimes(2)
    expect(sessionStorage.getItem('sso_auto_attempted')).toBeNull()
    expect(window.location.href).toBe('http://localhost/signin')
  })

  it('clears the SSO auto-attempt flag when authorization URL resolution is cancelled by unmount', async () => {
    searchParamValues.bypass_sso = null
    searchParamValues.callbackUrl = '/managed/quickstart'
    const authorization = deferred<{ authorization_url: string; state: string }>()
    managedGetMock
      .mockResolvedValueOnce({
        providers: [{ id: 'okta', display_name: 'Okta', icon: 'key' }],
        login_mode: 'redirect',
      })
      .mockReturnValueOnce(authorization.promise)

    const { default: LoginPage } = await import('./login-form')
    const view = render(<LoginPage />)

    await settle()
    expect(managedGetMock).toHaveBeenCalledWith(
      'auth/oauth/providers',
      expect.objectContaining({
        withAuth: false,
        skipManagedContext: true,
        signal: expect.any(AbortSignal),
      }),
    )
    await settle()
    expect(managedGetMock).toHaveBeenCalledWith(
      'auth/oauth/okta?callback_url=%2Fmanaged%2Fquickstart',
      expect.objectContaining({
        withAuth: false,
        skipManagedContext: true,
        signal: expect.any(AbortSignal),
      }),
    )

    expect(sessionStorage.getItem('sso_auto_attempted')).toBeTruthy()
    view.unmount()

    await act(async () => {
      authorization.resolve({
        authorization_url: 'https://sso.example.test/authorize',
        state: 'attempt-1',
      })
      await authorization.promise
      await Promise.resolve()
    })

    expect(window.location.href).toBe('http://localhost/signin')
    expect(sessionStorage.getItem('sso_auto_attempted')).toBeNull()
  })

  it('aborts a never-resolving provider request immediately on unmount', async () => {
    searchParamValues.bypass_sso = null
    const providers = deferred<{
      providers: Array<{ id: string; display_name: string; icon: string }>
      login_mode: 'redirect'
    }>()
    managedGetMock.mockReturnValueOnce(providers.promise)

    const { default: LoginPage } = await import('./login-form')
    const view = render(<LoginPage />)

    await settle()
    const providerSignal = oauthRequests('auth/oauth/providers')[0]?.[1]?.signal
    expect(providerSignal).toBeInstanceOf(AbortSignal)
    expect(providerSignal.aborted).toBe(false)

    view.unmount()

    expect(providerSignal.aborted).toBe(true)
    expect(sessionStorage.getItem('sso_auto_attempted')).toBeNull()
  })

  it('aborts a never-resolving authorization and releases its owned guard on unmount', async () => {
    searchParamValues.bypass_sso = null
    const authorization = deferred<{ authorization_url: string; state: string }>()
    managedGetMock
      .mockResolvedValueOnce({
        providers: [{ id: 'github', display_name: 'GitHub', icon: 'github' }],
        login_mode: 'redirect',
      })
      .mockReturnValueOnce(authorization.promise)

    const { default: LoginPage } = await import('./login-form')
    const view = render(<LoginPage />)

    await settle()
    const authorizationSignal = oauthRequests('auth/oauth/github')[0]?.[1]?.signal
    expect(authorizationSignal).toBeInstanceOf(AbortSignal)
    expect(authorizationSignal.aborted).toBe(false)
    expect(sessionStorage.getItem('sso_auto_attempted')).toBeTruthy()

    view.unmount()

    expect(authorizationSignal.aborted).toBe(true)
    expect(sessionStorage.getItem('sso_auto_attempted')).toBeNull()
  })

  it('does not remove a replacement guard when cancelling an older authorization run', async () => {
    searchParamValues.bypass_sso = null
    const authorization = deferred<{ authorization_url: string; state: string }>()
    managedGetMock
      .mockResolvedValueOnce({
        providers: [{ id: 'github', display_name: 'GitHub', icon: 'github' }],
        login_mode: 'redirect',
      })
      .mockReturnValueOnce(authorization.promise)

    const { default: LoginPage } = await import('./login-form')
    const view = render(<LoginPage />)

    await settle()
    const ownedGuard = sessionStorage.getItem('sso_auto_attempted')
    expect(ownedGuard).toBeTruthy()

    const replacementGuard = `${Date.now()}:replacement-run`
    sessionStorage.setItem('sso_auto_attempted', replacementGuard)
    view.unmount()

    expect(sessionStorage.getItem('sso_auto_attempted')).toBe(replacementGuard)
  })
})
