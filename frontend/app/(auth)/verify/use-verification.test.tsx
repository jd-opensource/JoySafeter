import { act, cleanup, fireEvent, render } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useVerification } from './use-verification'

const { emailOtpMock, sendVerificationOtpMock, refetchSessionMock, pushMock, searchParamValues } =
  vi.hoisted(() => ({
    emailOtpMock: vi.fn(),
    sendVerificationOtpMock: vi.fn(),
    refetchSessionMock: vi.fn(),
    pushMock: vi.fn(),
    searchParamValues: {
      redirectAfter: '/dashboard#after',
      invite_flow: 'true',
    } as Record<string, string | null>,
  }))

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

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock }),
  useSearchParams: () => ({
    get: (key: string) => searchParamValues[key] ?? null,
  }),
}))

vi.mock('@/lib/auth/auth-client', () => ({
  client: {
    signIn: {
      emailOtp: emailOtpMock,
    },
    emailOtp: {
      sendVerificationOtp: sendVerificationOtpMock,
    },
  },
  useSession: () => ({ refetch: refetchSessionMock }),
}))

vi.mock('@/lib/api-client', () => ({
  ApiError: class ApiError extends Error {
    code?: string
  },
}))

vi.mock('@/lib/logs/console/logger', () => ({
  createLogger: () => ({
    error: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
  }),
}))

const dom = new JSDOM('<!doctype html><html><body></body></html>', {
  url: 'http://localhost/dashboard',
})
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.sessionStorage = dom.window.sessionStorage

function VerificationHarness({
  isEmailVerificationEnabled = true,
}: {
  isEmailVerificationEnabled?: boolean
}) {
  const verification = useVerification({
    hasEmailService: true,
    isProduction: false,
    isEmailVerificationEnabled,
  })

  return (
    <div>
      <span>{verification.email}</span>
      <span>{verification.isOtpComplete ? 'complete' : 'incomplete'}</span>
      <span>{verification.isVerified ? 'verified' : 'unverified'}</span>
      <span>{verification.errorMessage}</span>
      <button type="button" onClick={() => verification.handleOtpChange('123456')}>
        set-otp
      </button>
      <button type="button" onClick={() => verification.handleOtpChange('654321')}>
        set-new-otp
      </button>
      <button type="button" onClick={() => verification.verifyCode()}>
        verify
      </button>
      <button type="button" onClick={() => verification.resendCode()}>
        resend
      </button>
    </div>
  )
}

describe('useVerification redirect lifecycle', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    emailOtpMock.mockReset()
    sendVerificationOtpMock.mockReset()
    refetchSessionMock.mockReset()
    pushMock.mockReset()
    emailOtpMock.mockResolvedValue({ data: { user: { id: 'user_1' } }, error: null })
    sendVerificationOtpMock.mockResolvedValue(undefined)
    refetchSessionMock.mockResolvedValue(undefined)
    searchParamValues.redirectAfter = '/dashboard#after'
    searchParamValues.invite_flow = 'true'
    window.history.replaceState({}, '', '/dashboard')
    sessionStorage.clear()
    sessionStorage.setItem('verificationEmail', 'ada@example.com')
    sessionStorage.setItem('isInviteFlow', 'true')
  })

  afterEach(() => {
    cleanup()
    vi.useRealTimers()
    sessionStorage.clear()
  })

  it('does not run the delayed verification redirect after the verification view unmounts', async () => {
    const view = render(<VerificationHarness />)

    await settle()
    expect(view.getByText('ada@example.com')).toBeTruthy()

    await act(async () => {
      fireEvent.click(view.getByText('set-otp'))
      await Promise.resolve()
    })
    await settle()
    expect(view.getByText('complete')).toBeTruthy()

    await act(async () => {
      fireEvent.click(view.getByText('verify'))
      await Promise.resolve()
      await Promise.resolve()
    })
    await settle()
    expect(emailOtpMock).toHaveBeenCalledTimes(1)

    view.unmount()

    await act(async () => {
      vi.advanceTimersByTime(1000)
      await Promise.resolve()
    })

    expect(window.location.href).toBe('http://localhost/dashboard')
  })

  it('does not redirect after the verification-disabled refetch resolves post-unmount', async () => {
    const refetch = deferred<void>()
    refetchSessionMock.mockReturnValue(refetch.promise)
    const view = render(<VerificationHarness isEmailVerificationEnabled={false} />)

    await settle()
    expect(refetchSessionMock).toHaveBeenCalled()

    view.unmount()

    await act(async () => {
      refetch.resolve()
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(pushMock).not.toHaveBeenCalled()
    expect(window.location.href).toBe('http://localhost/dashboard')
  })

  it('does not use a same-prefix non-whitelisted path for verification-disabled invite redirects', async () => {
    searchParamValues.redirectAfter = '/dashboardevil'
    render(<VerificationHarness isEmailVerificationEnabled={false} />)

    await settle()
    expect(refetchSessionMock).toHaveBeenCalled()
    await settle()
    expect(pushMock).toHaveBeenCalledWith('/managed/quickstart')
  })

  it('does not let an older verification failure clear a newer successful verification', async () => {
    const olderVerification = deferred<{ error: { code: string } }>()
    const newerVerification = deferred<{ data: { user: { id: string } }; error: null }>()
    emailOtpMock
      .mockReturnValueOnce(olderVerification.promise)
      .mockReturnValueOnce(newerVerification.promise)

    const view = render(<VerificationHarness />)

    await settle()
    expect(view.getByText('ada@example.com')).toBeTruthy()

    await act(async () => {
      fireEvent.click(view.getByText('set-otp'))
      await Promise.resolve()
    })
    await settle()
    expect(view.getByText('complete')).toBeTruthy()

    await act(async () => {
      fireEvent.click(view.getByText('verify'))
      await Promise.resolve()
    })
    expect(emailOtpMock).toHaveBeenCalledTimes(1)

    await act(async () => {
      fireEvent.click(view.getByText('set-new-otp'))
      await Promise.resolve()
    })
    await act(async () => {
      fireEvent.click(view.getByText('verify'))
      await Promise.resolve()
    })
    expect(emailOtpMock).toHaveBeenCalledTimes(2)

    await act(async () => {
      newerVerification.resolve({ data: { user: { id: 'user_1' } }, error: null })
      await Promise.resolve()
      await Promise.resolve()
    })
    await settle()
    expect(view.getByText('verified')).toBeTruthy()

    await act(async () => {
      olderVerification.resolve({ error: { code: 'VERIFICATION_TOKEN_INVALID' } })
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(view.getByText('verified')).toBeTruthy()
    expect(view.queryByText('Invalid verification code. Please check and try again.')).toBeNull()
  })

  it('does not let an older resend failure overwrite a newer resend success', async () => {
    const olderResend = deferred<void>()
    const newerResend = deferred<void>()
    sendVerificationOtpMock
      .mockReturnValueOnce(olderResend.promise)
      .mockReturnValueOnce(newerResend.promise)

    const view = render(<VerificationHarness />)

    await settle()
    expect(view.getByText('ada@example.com')).toBeTruthy()

    await act(async () => {
      fireEvent.click(view.getByText('resend'))
      await Promise.resolve()
    })
    await act(async () => {
      fireEvent.click(view.getByText('resend'))
      await Promise.resolve()
    })
    expect(sendVerificationOtpMock).toHaveBeenCalledTimes(2)

    await act(async () => {
      newerResend.resolve()
      await Promise.resolve()
      await Promise.resolve()
    })

    await act(async () => {
      olderResend.reject(new Error('network failed'))
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(
      view.queryByText('Failed to resend verification code. Please try again later.'),
    ).toBeNull()
  })
})
