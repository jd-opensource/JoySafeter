'use client'

import { zodResolver } from '@hookform/resolvers/zod'
import { ArrowRight, ChevronRight, Eye, EyeOff } from 'lucide-react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useForm } from 'react-hook-form'

import { OAuthButtons } from '@/components/auth/oauth-buttons'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ApiError, managedGet } from '@/lib/api-client'
import { client, useSession } from '@/lib/auth/auth-client'
import { getEnv, isFalsy } from '@/lib/core/config/env'
import { getBaseUrl } from '@/lib/core/utils/urls'
import { useTranslation } from '@/lib/i18n'
import { createLogger } from '@/lib/logs/console/logger'
import { cn } from '@/lib/utils'
import { toastError, toastSuccess } from '@/lib/utils/toast'
import { quickValidateEmail } from '@/services/email/validation'
import { useProjectStore } from '@/stores/managed/project-store'
import { inter } from '@/styles/fonts/inter/inter'
import { soehne } from '@/styles/fonts/soehne/soehne'

import { loginFormSchema, type LoginFormData } from './schemas/loginFormSchema'

const logger = createLogger('LoginForm')
const SSO_AUTO_ATTEMPTED_KEY = 'sso_auto_attempted'
const SSO_AUTO_ATTEMPTED_TTL_MS = 60_000

interface OAuthProvider {
  id: string
}

interface OAuthProvidersResponse {
  providers: OAuthProvider[]
  login_mode: 'chooser' | 'redirect'
}

interface OAuthAuthorizationResponse {
  authorization_url: string
  state: string
}

const getEmailErrorKey = (reason?: string): string => {
  if (!reason) return 'auth.emailInvalid'
  if (reason.includes('Invalid email format')) return 'auth.emailInvalidFormat'
  if (reason.includes('Missing domain')) return 'auth.emailMissingDomain'
  if (reason.includes('Disposable email')) return 'auth.emailDisposable'
  if (reason.includes('suspicious patterns')) return 'auth.emailSuspiciousPattern'
  if (reason.includes('Invalid domain format')) return 'auth.emailInvalidDomain'
  if (reason.includes('no MX records')) return 'auth.emailNoMxRecords'
  if (reason.includes('Validation service')) return 'auth.emailValidationUnavailable'
  return 'auth.emailInvalid'
}

const getAuthErrorMessageKey = (errorCode: string): string | null => {
  switch (errorCode) {
    case 'INVALID_CREDENTIALS':
    case 'MISSING_CREDENTIALS':
    case 'FAILED_TO_CREATE_SESSION':
      return 'auth.invalidCredentials'
    case 'USER_NOT_FOUND':
      return 'auth.userNotFound'
    case 'EMAIL_PASSWORD_DISABLED':
      return 'auth.emailSignInDisabled'
    case 'RATE_LIMITED':
      return 'auth.tooManyAttempts'
    case 'NETWORK_ERROR':
    case 'REQUEST_TIMEOUT':
      return 'auth.networkError'
    default:
      return null
  }
}

const getOAuthCallbackErrorKey = (errorCode?: string | null): string => {
  switch (errorCode) {
    case 'OAUTH_ACCESS_DENIED':
      return 'auth.oauthDenied'
    case 'OAUTH_STATE_INVALID':
    case 'OAUTH_STATE_MISSING':
    case 'OAUTH_PROVIDER_MISMATCH':
      return 'auth.oauthInvalidState'
    case 'OAUTH_DISCOVERY_FAILED':
    case 'OAUTH_TOKEN_ENDPOINT_DISCOVERY_FAILED':
    case 'OAUTH_USERINFO_ENDPOINT_DISCOVERY_FAILED':
      return 'auth.oauthDiscoveryFailed'
    case 'OAUTH_AUTHORIZE_URL_MISSING':
      return 'auth.oauthAuthorizeUrlMissing'
    case 'OAUTH_TOKEN_URL_MISSING':
      return 'auth.oauthTokenUrlMissing'
    case 'OAUTH_USERINFO_URL_MISSING':
      return 'auth.oauthUserinfoUrlMissing'
    case 'OAUTH_TOKEN_EXCHANGE_FAILED':
    case 'OAUTH_USERINFO_FETCH_FAILED':
      return 'auth.oauthFailed'
    default:
      return 'auth.oauthError'
  }
}

const validateCallbackUrl = (url: string): boolean => {
  try {
    if (url.startsWith('/')) {
      return !url.startsWith('//') && !url.includes('..') && !url.includes('//')
    }

    const currentOrigin = typeof window !== 'undefined' ? window.location.origin : ''
    if (currentOrigin) {
      const parsedUrl = new URL(url)
      return parsedUrl.origin === currentOrigin
    }

    return false
  } catch (error) {
    logger.error('Error validating callback URL:', { error, url })
    return false
  }
}

function hasRecentSsoAutoAttempt(): boolean {
  const raw = sessionStorage.getItem(SSO_AUTO_ATTEMPTED_KEY)
  if (!raw) return false

  const attemptedAt = Number(raw)
  if (!Number.isFinite(attemptedAt)) {
    sessionStorage.removeItem(SSO_AUTO_ATTEMPTED_KEY)
    return false
  }

  if (Date.now() - attemptedAt > SSO_AUTO_ATTEMPTED_TTL_MS) {
    sessionStorage.removeItem(SSO_AUTO_ATTEMPTED_KEY)
    return false
  }

  return true
}

export default function LoginPage() {
  const { t } = useTranslation()
  const router = useRouter()
  const searchParams = useSearchParams()
  const { data: sessionData, isPending: isSessionPending, refetch: refetchSession } = useSession()
  const [isLoading, setIsLoading] = useState(false)
  const [mounted, setMounted] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [isButtonHovered, setIsButtonHovered] = useState(false)

  const [callbackUrl, setCallbackUrl] = useState('/managed/quickstart')
  const [isInviteFlow, setIsInviteFlow] = useState(false)

  const [forgotPasswordOpen, setForgotPasswordOpen] = useState(false)
  const [forgotPasswordEmail, setForgotPasswordEmail] = useState('')
  const [isSubmittingReset, setIsSubmittingReset] = useState(false)
  const [isResetButtonHovered, setIsResetButtonHovered] = useState(false)
  const resetDialogCloseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const loginRedirectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const isMountedRef = useRef(false)
  const resetRequestRunRef = useRef(0)
  const [, setResetStatus] = useState<{
    type: 'success' | 'error' | null
    message: string
  }>({ type: null, message: '' })

  // When bypass_sso=true (SSO fallback), always show email/password form
  const isBypassSso = searchParams?.get('bypass_sso') === 'true'
  const showEmailPasswordForm =
    isBypassSso || !isFalsy(getEnv('NEXT_PUBLIC_EMAIL_PASSWORD_SIGNUP_ENABLED'))

  const form = useForm<LoginFormData>({
    resolver: zodResolver(loginFormSchema),
    defaultValues: { email: '', password: '' },
    mode: 'onChange',
  })

  const [oauthError, setOauthError] = useState<string | null>(null)

  const clearResetDialogCloseTimer = useCallback(() => {
    if (!resetDialogCloseTimerRef.current) return
    clearTimeout(resetDialogCloseTimerRef.current)
    resetDialogCloseTimerRef.current = null
  }, [])

  const clearLoginRedirectTimer = useCallback(() => {
    if (!loginRedirectTimerRef.current) return
    clearTimeout(loginRedirectTimerRef.current)
    loginRedirectTimerRef.current = null
  }, [])

  const setForgotPasswordDialogOpen = useCallback(
    (open: boolean) => {
      clearResetDialogCloseTimer()
      resetRequestRunRef.current += 1
      setForgotPasswordOpen(open)
    },
    [clearResetDialogCloseTimer],
  )

  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
      resetRequestRunRef.current += 1
      clearResetDialogCloseTimer()
      clearLoginRedirectTimer()
    }
  }, [clearLoginRedirectTimer, clearResetDialogCloseTimer])

  useEffect(() => {
    setMounted(true)

    if (searchParams) {
      const callback = searchParams.get('callbackUrl')
      if (callback) {
        if (validateCallbackUrl(callback)) {
          setCallbackUrl(callback)
        } else {
          logger.warn('Invalid callback URL detected and blocked:', { url: callback })
        }
      }

      const inviteFlow = searchParams.get('invite_flow') === 'true'
      setIsInviteFlow(inviteFlow)

      // handle OAuth errors
      const errorCode = searchParams.get('error_code')
      const errorMessageParam = searchParams.get('error_message')
      if (errorCode) {
        const errorKey = getOAuthCallbackErrorKey(errorCode)
        const errorMessage =
          errorMessageParam &&
          (errorKey === 'auth.oauthFailed' ||
            errorKey === 'auth.oauthError' ||
            errorKey === 'auth.oauthDiscoveryFailed')
            ? errorMessageParam
            : t(errorKey)
        setOauthError(errorMessage)
        // clear error params from URL
        const url = new URL(window.location.href)
        url.searchParams.delete('error_code')
        url.searchParams.delete('error_message')
        window.history.replaceState({}, '', url.toString())
      }
    }
  }, [searchParams, t])

  useEffect(() => {
    if (isSessionPending || !sessionData?.user) {
      return
    }

    // Clear SSO auto-redirect flag on successful login
    sessionStorage.removeItem(SSO_AUTO_ATTEMPTED_KEY)
    const safeCallbackUrl = validateCallbackUrl(callbackUrl) ? callbackUrl : '/managed/quickstart'
    router.replace(safeCallbackUrl)
  }, [callbackUrl, isSessionPending, router, sessionData?.user])

  // SSO auto-redirect: if no OAuth error and not bypassed, redirect to SSO directly
  useEffect(() => {
    if (!mounted) return
    if (sessionData?.user) return
    if (oauthError) return
    if (isBypassSso) return

    let cancelled = false
    const redirectToSso = async () => {
      try {
        const providersResponse = await managedGet<OAuthProvidersResponse>('auth/oauth/providers', {
          withAuth: false,
          skipManagedContext: true,
        })
        if (providersResponse.login_mode !== 'redirect') {
          sessionStorage.removeItem(SSO_AUTO_ATTEMPTED_KEY)
          return
        }

        const ssoProvider = providersResponse.providers?.[0]?.id
        if (!ssoProvider) {
          sessionStorage.removeItem(SSO_AUTO_ATTEMPTED_KEY)
          return
        }

        // Prevent infinite redirect loops only when backend policy requires redirect mode.
        if (hasRecentSsoAutoAttempt()) return
        sessionStorage.setItem(SSO_AUTO_ATTEMPTED_KEY, String(Date.now()))

        const params = new URLSearchParams()
        params.set('callback_url', callbackUrl)
        const response = await managedGet<OAuthAuthorizationResponse>(
          `auth/oauth/${encodeURIComponent(ssoProvider)}?${params.toString()}`,
          {
            withAuth: false,
            skipManagedContext: true,
          },
        )
        if (!cancelled) {
          window.location.href = response.authorization_url
        } else {
          sessionStorage.removeItem(SSO_AUTO_ATTEMPTED_KEY)
        }
      } catch (error) {
        if (!cancelled) logger.warn('Failed to initiate SSO auto-redirect:', { error })
        // No redirect happened, so clear the flag and let the next login page retry.
        sessionStorage.removeItem(SSO_AUTO_ATTEMPTED_KEY)
      }
    }

    redirectToSso()
    return () => {
      cancelled = true
    }
  }, [mounted, sessionData?.user, oauthError, isBypassSso, callbackUrl])

  const handleForgotPassword = useCallback(async () => {
    if (!forgotPasswordEmail) {
      toastError(t('auth.emailRequired'))
      return
    }

    const emailValidation = quickValidateEmail(forgotPasswordEmail.trim().toLowerCase())
    if (!emailValidation.isValid) {
      toastError(t('auth.emailInvalid'))
      return
    }

    const runId = resetRequestRunRef.current + 1
    resetRequestRunRef.current = runId
    const isCurrentResetRequest = () => isMountedRef.current && resetRequestRunRef.current === runId

    try {
      setIsSubmittingReset(true)
      setResetStatus({ type: null, message: '' })

      await client.forgetPassword({
        email: forgotPasswordEmail,
        redirectTo: `${getBaseUrl()}/reset-password`,
      })

      if (!isCurrentResetRequest()) return

      toastSuccess(t('auth.passwordResetLinkSent'))

      clearResetDialogCloseTimer()
      resetDialogCloseTimerRef.current = setTimeout(() => {
        resetDialogCloseTimerRef.current = null
        if (!isCurrentResetRequest()) return
        setForgotPasswordOpen(false)
        setResetStatus({ type: null, message: '' })
      }, 2000)
    } catch (error) {
      if (!isCurrentResetRequest()) return
      logger.error('Error requesting password reset:', { error })

      let errorMessage = t('auth.passwordResetRequestFailed')
      if (error instanceof ApiError) {
        if (error.code === 'INVALID_EMAIL') {
          errorMessage = t('auth.emailInvalid')
        } else if (error.code === 'EMAIL_REQUIRED') {
          errorMessage = t('auth.emailRequired')
        } else {
          errorMessage = error.message
        }
      } else if (error instanceof Error) {
        errorMessage = error.message
      }

      toastError(errorMessage)
    } finally {
      if (isCurrentResetRequest()) {
        setIsSubmittingReset(false)
      }
    }
  }, [clearResetDialogCloseTimer, forgotPasswordEmail, t])

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Enter' && forgotPasswordOpen) {
        handleForgotPassword()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [forgotPasswordEmail, forgotPasswordOpen, handleForgotPassword])

  async function onSubmit(data: LoginFormData) {
    clearLoginRedirectTimer()
    setIsLoading(true)

    const email = data.email.trim().toLowerCase()
    const password = data.password

    // Advanced email validation (disposable email, MX records, etc.)
    const emailValidation = quickValidateEmail(email)
    if (!emailValidation.isValid) {
      const errorKey = getEmailErrorKey(emailValidation.reason)
      form.setError('email', { message: t(errorKey) })
      toastError(t(errorKey))
      setIsLoading(false)
      return
    }

    try {
      const safeCallbackUrl = validateCallbackUrl(callbackUrl) ? callbackUrl : '/managed/quickstart'

      logger.info('Attempting login with email:', email)
      const result = await client.signIn.email(
        {
          email,
          password,
          callbackURL: safeCallbackUrl,
        },
        {
          onError: (ctx: { error: ApiError }) => {
            logger.error('Login error:', ctx.error)

            const errorCode = typeof ctx.error.code === 'string' ? ctx.error.code : ''
            const errorMessage = typeof ctx.error.message === 'string' ? ctx.error.message : ''

            if (errorCode === 'EMAIL_NOT_VERIFIED') {
              return
            }

            let displayMessage = t('auth.invalidCredentials')

            const messageKey = getAuthErrorMessageKey(errorCode)
            if (messageKey) {
              displayMessage = t(messageKey)
            } else if (errorMessage) {
              displayMessage = errorMessage
            }

            toastError(displayMessage)
          },
        },
      )

      logger.info('Login result:', result)
      if (!isMountedRef.current) return
      logger.info('Login result structure:', {
        hasResult: !!result,
        hasError: !!result?.error,
        hasData: !!result?.data,
        resultKeys: result ? Object.keys(result) : [],
      })

      if (!result || result.error) {
        logger.warn('Login failed with error:', result?.error)
        if (result?.error) {
          const error = result.error as ApiError
          const errorCode = typeof error.code === 'string' ? error.code : ''
          const errorMsg = typeof error.message === 'string' ? error.message : ''

          let displayMessage = t('auth.invalidCredentials')

          const messageKey = getAuthErrorMessageKey(errorCode)
          if (messageKey) {
            displayMessage = t(messageKey)
          } else if (errorMsg) {
            displayMessage = errorMsg
          }

          toastError(displayMessage)
        } else {
          toastError(t('auth.invalidCredentials'))
        }
        setIsLoading(false)
        return
      }

      logger.info('Login successful, result data:', result.data)
      useProjectStore.getState().setContext('', '', [], [])

      // Check CSRF token (not HttpOnly, can be read)
      const csrfToken = document.cookie
        .split('; ')
        .find((row) => row.startsWith('csrf_token='))
        ?.split('=')[1]
      logger.info('Checking cookies after login:', {
        csrfToken: !!csrfToken,
        // Note: auth_token and refresh_token are HttpOnly, cannot be read via document.cookie
        // But backend has set these cookies, browser will automatically send them in subsequent requests
        allCookies: document.cookie,
      })

      // Login successful, trigger session refresh in background (don't wait)
      // Note: Even if session refresh fails, continue redirect (since Cookie has been set by backend)
      refetchSession()
        .then(() => {
          logger.info('Session refetched successfully after login')
        })
        .catch((sessionError) => {
          logger.warn('Failed to refresh session after login (continuing anyway):', sessionError)
        })

      // Redirect immediately, don't wait for session refresh to complete
      // Cookie has been set by backend, browser will automatically send it in requests after redirect
      logger.info('Login successful, redirecting to:', safeCallbackUrl)

      // Use setTimeout to ensure all async operations complete, but don't wait too long
      clearLoginRedirectTimer()
      loginRedirectTimerRef.current = setTimeout(() => {
        loginRedirectTimerRef.current = null
        if (!isMountedRef.current) return
        logger.info('Executing redirect to:', safeCallbackUrl)
        try {
          window.location.href = safeCallbackUrl
        } catch (redirectError) {
          logger.error('Failed to redirect:', redirectError)
          // If redirect fails, try using router
          router.push(safeCallbackUrl)
        }
      }, 50)
    } catch (err: unknown) {
      const error = err as { message?: string; code?: string }
      if (error.code === 'EMAIL_NOT_VERIFIED') {
        if (typeof window !== 'undefined') {
          sessionStorage.setItem('verificationEmail', email)
        }
        router.push('/verify')
        return
      }

      logger.error('Uncaught login error:', err)
      const errorMessage = error.message || t('auth.invalidCredentials')
      toastError(errorMessage)
    } finally {
      if (isMountedRef.current) {
        setIsLoading(false)
      }
    }
  }

  return (
    <>
      <div className="space-y-1 text-center">
        <h1
          className={`${soehne.className} text-3xl font-medium tracking-tight text-[var(--text-primary)]`}
          suppressHydrationWarning
        >
          {mounted ? t('auth.signIn') : 'Sign In'}
        </h1>
        <p
          className={`${inter.className} text-lg font-[380] text-muted-foreground`}
          suppressHydrationWarning
        >
          {mounted ? t('auth.enterYourDetails') : 'Enter your details'}
        </p>
      </div>

      {/* OAuth error message */}
      {oauthError && (
        <div className="mt-4 rounded-md bg-[var(--status-error-bg)] p-3 text-sm text-[var(--status-error)]">
          {oauthError}
        </div>
      )}

      {showEmailPasswordForm && (
        <form
          onSubmit={(event) => void form.handleSubmit(onSubmit)(event)}
          className={`${inter.className} mt-8 space-y-8`}
        >
          <div className="space-y-6">
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="email" suppressHydrationWarning>
                  {mounted ? t('auth.email') : 'Email'}
                </Label>
              </div>
              <Input
                id="email"
                placeholder={mounted ? t('auth.enterYourEmail') : 'Enter your email'}
                autoCapitalize="none"
                autoComplete="email"
                autoCorrect="off"
                {...form.register('email')}
                className={cn(
                  'rounded-auth shadow-sm transition-colors focus:border-[var(--brand-400)] focus:ring-2 focus:ring-[var(--brand-100)]',
                  'border-[var(--status-error)] focus:border-[var(--status-error)] focus:ring-[var(--status-error-bg)] focus-visible:ring-[var(--status-error)]',
                )}
              />
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="password" suppressHydrationWarning>
                  {mounted ? t('auth.password') : 'Password'}
                </Label>
                <button
                  type="button"
                  onClick={() => setForgotPasswordDialogOpen(true)}
                  className="text-xs font-medium text-muted-foreground transition hover:text-foreground"
                  suppressHydrationWarning
                >
                  {mounted ? t('auth.forgotPassword') : 'Forgot password?'}
                </button>
              </div>
              <div className="relative">
                <Input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  autoCapitalize="none"
                  autoComplete="current-password"
                  autoCorrect="off"
                  placeholder={mounted ? t('auth.enterYourPassword') : 'Enter your password'}
                  {...form.register('password')}
                  className={cn(
                    'rounded-auth pr-10 shadow-sm transition-colors focus:border-[var(--brand-400)] focus:ring-2 focus:ring-[var(--brand-100)]',
                    form.formState.errors.password &&
                      'border-[var(--status-error)] focus:border-[var(--status-error)] focus:ring-[var(--status-error-bg)] focus-visible:ring-[var(--status-error)]',
                  )}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)] transition hover:text-[var(--text-primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-500)]"
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                >
                  {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </div>
          </div>

          <Button
            type="submit"
            onMouseEnter={() => setIsButtonHovered(true)}
            onMouseLeave={() => setIsButtonHovered(false)}
            className="group inline-flex w-full items-center justify-center gap-2 rounded-auth border border-[var(--brand-600)] bg-gradient-to-b from-[var(--brand-500)] to-[var(--brand-600)] px-3 py-1.5 pr-2.5 text-base text-white shadow-[inset_0_2px_4px_0_var(--brand-200)] transition-all"
            disabled={isLoading}
            suppressHydrationWarning
          >
            <span className="flex items-center gap-1">
              {isLoading
                ? mounted
                  ? t('auth.signingIn')
                  : 'Signing in...'
                : mounted
                  ? t('auth.signIn')
                  : 'Sign In'}
              <span className="inline-flex transition-transform duration-200 group-hover:translate-x-0.5">
                {isButtonHovered ? (
                  <ArrowRight className="h-4 w-4" aria-hidden="true" />
                ) : (
                  <ChevronRight className="h-4 w-4" aria-hidden="true" />
                )}
              </span>
            </span>
          </Button>
        </form>
      )}

      {/* OAuth/SSO login buttons */}
      <OAuthButtons callbackUrl={callbackUrl} showDivider={showEmailPasswordForm} />

      {showEmailPasswordForm && (
        <div
          className={`${inter.className} pt-6 text-center text-base font-light`}
          suppressHydrationWarning
        >
          <span className="font-normal">
            {mounted ? t('auth.dontHaveAccount') : "Don't have an account?"}{' '}
          </span>
          <Link
            href={isInviteFlow ? `/signup?invite_flow=true&callbackUrl=${callbackUrl}` : '/signup'}
            className="font-medium text-[var(--brand-600)] underline-offset-4 transition hover:text-[var(--brand-700)] hover:underline"
          >
            {mounted ? t('auth.signUp') : 'Sign Up'}
          </Link>
        </div>
      )}

      <Dialog open={forgotPasswordOpen} onOpenChange={setForgotPasswordDialogOpen}>
        <DialogContent className="auth-card auth-card-shadow max-w-[540px] rounded-auth border backdrop-blur-sm">
          <DialogHeader>
            <DialogTitle
              className="auth-text-primary text-xl font-semibold tracking-tight"
              suppressHydrationWarning
            >
              {mounted ? t('auth.resetPassword') : 'Reset Password'}
            </DialogTitle>
            <DialogDescription className="auth-text-secondary text-sm" suppressHydrationWarning>
              {mounted
                ? t('auth.resetPasswordDescription')
                : 'Enter your email to receive a password reset link'}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="reset-email" suppressHydrationWarning>
                  {mounted ? t('auth.email') : 'Email'}
                </Label>
              </div>
              <Input
                id="reset-email"
                value={forgotPasswordEmail}
                onChange={(e) => setForgotPasswordEmail(e.target.value)}
                placeholder={mounted ? t('auth.enterYourEmail') : 'Enter your email'}
                required
                type="email"
                className={cn(
                  'rounded-auth shadow-sm transition-colors focus:border-[var(--brand-400)] focus:ring-2 focus:ring-[var(--brand-100)]',
                  'border-[var(--status-error)] focus:border-[var(--status-error)] focus:ring-[var(--status-error-bg)] focus-visible:ring-[var(--status-error)]',
                )}
              />
            </div>
            <Button
              type="button"
              onClick={handleForgotPassword}
              onMouseEnter={() => setIsResetButtonHovered(true)}
              onMouseLeave={() => setIsResetButtonHovered(false)}
              className="group inline-flex w-full items-center justify-center gap-2 rounded-auth border border-[var(--brand-600)] bg-gradient-to-b from-[var(--brand-500)] to-[var(--brand-600)] px-3 py-1.5 pr-2.5 text-base text-white shadow-[inset_0_2px_4px_0_var(--brand-200)] transition-all"
              disabled={isSubmittingReset}
            >
              <span className="flex items-center gap-1" suppressHydrationWarning>
                {isSubmittingReset
                  ? mounted
                    ? t('auth.sending')
                    : 'Sending...'
                  : mounted
                    ? t('auth.sendResetLink')
                    : 'Send Reset Link'}
                <span className="inline-flex transition-transform duration-200 group-hover:translate-x-0.5">
                  {isResetButtonHovered ? (
                    <ArrowRight className="h-4 w-4" aria-hidden="true" />
                  ) : (
                    <ChevronRight className="h-4 w-4" aria-hidden="true" />
                  )}
                </span>
              </span>
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
