'use client'

import { zodResolver } from '@hookform/resolvers/zod'
import { ArrowRight, ChevronRight, Eye, EyeOff } from 'lucide-react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { useCallback, useEffect, useState } from 'react'
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
import { client, useSession, type AuthError } from '@/lib/auth/auth-client'
import { getEnv, isFalsy } from '@/lib/core/config/env'
import { getBaseUrl } from '@/lib/core/utils/urls'
import { useTranslation } from '@/lib/i18n'
import { createLogger } from '@/lib/logs/console/logger'
import { cn } from '@/lib/utils'
import { toastError, toastSuccess } from '@/lib/utils/toast'
import { quickValidateEmail } from '@/services/email/validation'
import { inter } from '@/styles/fonts/inter/inter'
import { soehne } from '@/styles/fonts/soehne/soehne'

import { loginFormSchema, type LoginFormData } from './schemas/loginFormSchema'

const logger = createLogger('LoginForm')

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

const validateCallbackUrl = (url: string): boolean => {
  try {
    if (url.startsWith('/')) {
      return true
    }

    const currentOrigin = typeof window !== 'undefined' ? window.location.origin : ''
    if (url.startsWith(currentOrigin)) {
      return true
    }

    return false
  } catch (error) {
    logger.error('Error validating callback URL:', { error, url })
    return false
  }
}

export default function LoginPage() {
  const { t } = useTranslation()
  const router = useRouter()
  const searchParams = useSearchParams()
  const { refetch: refetchSession } = useSession()
  const [isLoading, setIsLoading] = useState(false)
  const [mounted, setMounted] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [isButtonHovered, setIsButtonHovered] = useState(false)

  const [callbackUrl, setCallbackUrl] = useState('/chat')
  const [isInviteFlow, setIsInviteFlow] = useState(false)

  const [forgotPasswordOpen, setForgotPasswordOpen] = useState(false)
  const [forgotPasswordEmail, setForgotPasswordEmail] = useState('')
  const [isSubmittingReset, setIsSubmittingReset] = useState(false)
  const [isResetButtonHovered, setIsResetButtonHovered] = useState(false)
  const [resetStatus, setResetStatus] = useState<{
    type: 'success' | 'error' | null
    message: string
  }>({ type: null, message: '' })

  const form = useForm<LoginFormData>({
    resolver: zodResolver(loginFormSchema),
    defaultValues: { email: '', password: '' },
    mode: 'onChange',
  })

  const [oauthError, setOauthError] = useState<string | null>(null)

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

      // 处理 OAuth 错误
      const error = searchParams.get('error')
      const errorDescription = searchParams.get('error_description')
      if (error) {
        let errorMessage = t('auth.oauthError')
        if (error === 'oauth_denied') {
          errorMessage = t('auth.oauthDenied')
        } else if (error === 'invalid_state') {
          errorMessage = t('auth.oauthInvalidState')
        } else if (error === 'oauth_failed') {
          errorMessage = errorDescription || t('auth.oauthFailed')
        } else if (errorDescription) {
          errorMessage = errorDescription
        }
        setOauthError(errorMessage)
        // 清除 URL 中的错误参数
        const url = new URL(window.location.href)
        url.searchParams.delete('error')
        url.searchParams.delete('error_description')
        window.history.replaceState({}, '', url.toString())
      }
    }

  }, [searchParams, t])

  const handleForgotPassword = useCallback(async () => {
    if (!forgotPasswordEmail) {
      toastError('Please enter your email address')
      return
    }

    const emailValidation = quickValidateEmail(forgotPasswordEmail.trim().toLowerCase())
    if (!emailValidation.isValid) {
      toastError('Please enter a valid email address')
      return
    }

    try {
      setIsSubmittingReset(true)
      setResetStatus({ type: null, message: '' })

      await client.forgetPassword({
        email: forgotPasswordEmail,
        redirectTo: `${getBaseUrl()}/reset-password`,
      })

      toastSuccess('Password reset link sent to your email')

      setTimeout(() => {
        setForgotPasswordOpen(false)
        setResetStatus({ type: null, message: '' })
      }, 2000)
    } catch (error) {
      logger.error('Error requesting password reset:', { error })

      let errorMessage = 'Failed to request password reset'
      if (error instanceof Error) {
        if (error.message.includes('invalid email')) {
          errorMessage = 'Please enter a valid email address'
        } else if (error.message.includes('Email is required')) {
          errorMessage = 'Please enter your email address'
        } else {
          errorMessage = error.message
        }
      }

      toastError(errorMessage)
    } finally {
      setIsSubmittingReset(false)
    }
  }, [forgotPasswordEmail])

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
      const safeCallbackUrl = validateCallbackUrl(callbackUrl) ? callbackUrl : '/chat'

      logger.info('Attempting login with email:', email)
      const result = await client.signIn.email(
        {
          email,
          password,
          callbackURL: safeCallbackUrl,
        },
        {
          onError: (ctx: { error: AuthError }) => {
            logger.error('Login error:', ctx.error)

            const errorCode = typeof ctx.error.code === 'string' ? ctx.error.code : ''
            const errorMessage = typeof ctx.error.message === 'string' ? ctx.error.message : ''

            if (errorCode.includes('EMAIL_NOT_VERIFIED')) {
              return
            }

            let displayMessage = t('auth.invalidCredentials')

            if (
              errorCode.includes('BAD_REQUEST') ||
              errorMessage.includes('Email and password sign in is not enabled')
            ) {
              displayMessage = t('auth.emailSignInDisabled')
            } else if (
              errorCode.includes('INVALID_CREDENTIALS') ||
              errorMessage.includes('invalid password') ||
              errorMessage.includes('Incorrect email or password')
            ) {
              displayMessage = t('auth.invalidCredentials')
            } else if (errorCode.includes('USER_NOT_FOUND') || errorMessage.includes('not found')) {
              displayMessage = t('auth.userNotFound')
            } else if (errorCode.includes('MISSING_CREDENTIALS')) {
              displayMessage = t('auth.invalidCredentials')
            } else if (errorCode.includes('EMAIL_PASSWORD_DISABLED')) {
              displayMessage = t('auth.emailSignInDisabled')
            } else if (errorCode.includes('FAILED_TO_CREATE_SESSION')) {
              displayMessage = t('auth.invalidCredentials')
            } else if (errorCode.includes('too many attempts')) {
              displayMessage = t('auth.tooManyAttempts')
            } else if (errorCode.includes('account locked')) {
              displayMessage = t('auth.accountLocked')
            } else if (errorCode.includes('network') || errorMessage.includes('network')) {
              displayMessage = t('auth.networkError')
            } else if (errorMessage.includes('rate limit')) {
              displayMessage = t('auth.rateLimitError')
            } else if (errorMessage) {
              displayMessage = errorMessage
            }

            toastError(displayMessage)
          },
        },
      )

      logger.info('Login result:', result)
      logger.info('Login result structure:', {
        hasResult: !!result,
        hasError: !!result?.error,
        hasData: !!result?.data,
        resultKeys: result ? Object.keys(result) : [],
      })

      if (!result || result.error) {
        logger.warn('Login failed with error:', result?.error)
        if (result?.error) {
          const error = result.error as AuthError
          const errorCode = typeof error.code === 'string' ? error.code : ''
          const errorMsg = typeof error.message === 'string' ? error.message : ''

          let displayMessage = t('auth.invalidCredentials')

          if (
            errorCode.includes('INVALID_CREDENTIALS') ||
            errorMsg.includes('invalid password') ||
            errorMsg.includes('Incorrect email or password')
          ) {
            displayMessage = t('auth.invalidCredentials')
          } else if (errorCode.includes('USER_NOT_FOUND') || errorMsg.includes('not found')) {
            displayMessage = t('auth.userNotFound')
          } else if (errorCode.includes('too many attempts')) {
            displayMessage = t('auth.tooManyAttempts')
          } else if (errorCode.includes('account locked')) {
            displayMessage = t('auth.accountLocked')
          } else if (errorCode.includes('network') || errorMsg.includes('network')) {
            displayMessage = t('auth.networkError')
          } else if (errorMsg.includes('rate limit')) {
            displayMessage = t('auth.rateLimitError')
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
      setTimeout(() => {
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
      if (error.message?.includes('not verified') || error.code?.includes('EMAIL_NOT_VERIFIED')) {
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
      setIsLoading(false)
    }
  }

  return (
    <>
      <div className="space-y-1 text-center">
        <h1
          className={`${soehne.className} text-[32px] font-medium tracking-tight text-[var(--text-primary)]`}
          suppressHydrationWarning
        >
          {mounted ? t('auth.signIn') : 'Sign In'}
        </h1>
        <p
          className={`${inter.className} text-[16px] font-[380] text-muted-foreground`}
          suppressHydrationWarning
        >
          {mounted ? t('auth.enterYourDetails') : 'Enter your details'}
        </p>
      </div>

      {/* OAuth 错误提示 */}
      {oauthError && (
        <div className="mt-4 rounded-md bg-[var(--status-error-bg)] p-3 text-sm text-[var(--status-error)]">{oauthError}</div>
      )}

      {!isFalsy(getEnv('NEXT_PUBLIC_EMAIL_PASSWORD_SIGNUP_ENABLED')) && (
        <form
          onSubmit={form.handleSubmit(onSubmit)}
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
                  'rounded-[10px] shadow-sm transition-colors focus:border-[var(--brand-400)] focus:ring-2 focus:ring-[var(--brand-100)]',
                    'border-red-500 focus:border-red-500 focus:ring-red-100 focus-visible:ring-red-500',
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
                  onClick={() => setForgotPasswordOpen(true)}
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
                    'rounded-[10px] pr-10 shadow-sm transition-colors focus:border-[var(--brand-400)] focus:ring-2 focus:ring-[var(--brand-100)]',
                    form.formState.errors.password &&
                      'border-red-500 focus:border-red-500 focus:ring-red-100 focus-visible:ring-red-500',
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
            className="group inline-flex w-full items-center justify-center gap-2 rounded-[10px] border border-[var(--brand-600)] bg-gradient-to-b from-[var(--brand-500)] to-[var(--brand-600)] py-[6px] pl-[12px] pr-[10px] text-[15px] text-white shadow-[inset_0_2px_4px_0_var(--brand-200)] transition-all"
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

      {/* OAuth/SSO 登录按钮 */}
      <OAuthButtons
        callbackUrl={callbackUrl}
        showDivider={!isFalsy(getEnv('NEXT_PUBLIC_EMAIL_PASSWORD_SIGNUP_ENABLED'))}
      />

      {!isFalsy(getEnv('NEXT_PUBLIC_EMAIL_PASSWORD_SIGNUP_ENABLED')) && (
        <div
          className={`${inter.className} pt-6 text-center text-[14px] font-light`}
          suppressHydrationWarning
        >
          <span className="font-normal">
            {mounted ? t('auth.dontHaveAccount') : "Don't have an account?"}{' '}
          </span>
          <Link
            href={isInviteFlow ? `/signup?invite_flow=true&callbackUrl=${callbackUrl}` : '/signup'}
            className="font-medium text-[var(--brand-accent-hex)] underline-offset-4 transition hover:text-[var(--brand-accent-hover-hex)] hover:underline"
          >
            {mounted ? t('auth.signUp') : 'Sign Up'}
          </Link>
        </div>
      )}

      <Dialog open={forgotPasswordOpen} onOpenChange={setForgotPasswordOpen}>
        <DialogContent className="auth-card auth-card-shadow max-w-[540px] rounded-[10px] border backdrop-blur-sm">
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
                  'rounded-[10px] shadow-sm transition-colors focus:border-[var(--brand-400)] focus:ring-2 focus:ring-[var(--brand-100)]',
                    'border-red-500 focus:border-red-500 focus:ring-red-100 focus-visible:ring-red-500',
                )}
              />
            </div>
            <Button
              type="button"
              onClick={handleForgotPassword}
              onMouseEnter={() => setIsResetButtonHovered(true)}
              onMouseLeave={() => setIsResetButtonHovered(false)}
              className="group inline-flex w-full items-center justify-center gap-2 rounded-[10px] border border-[var(--brand-600)] bg-gradient-to-b from-[var(--brand-500)] to-[var(--brand-600)] py-[6px] pl-[12px] pr-[10px] text-[15px] text-white shadow-[inset_0_2px_4px_0_var(--brand-200)] transition-all"
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
