'use client'

import { ArrowRight, ChevronRight, Eye, EyeOff } from 'lucide-react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

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
import { getEnv, isFalsy, isTruthy } from '@/lib/core/config/env'
import { cn } from '@/lib/core/utils/cn'
import { getBaseUrl } from '@/lib/core/utils/urls'
import { createLogger } from '@/lib/logs/console/logger'
import { toastError, toastSuccess } from '@/lib/utils/toast'
import { quickValidateEmail } from '@/services/email/validation'
import { inter } from '@/styles/fonts/inter/inter'
import { soehne } from '@/styles/fonts/soehne/soehne'


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

const validateEmailField = (emailValue: string, t: (key: string) => string): string[] => {
  const errors: string[] = []

  if (!emailValue || !emailValue.trim()) {
    errors.push(t('auth.emailRequired'))
    return errors
  }

  const validation = quickValidateEmail(emailValue.trim().toLowerCase())
  if (!validation.isValid) {
    const errorKey = getEmailErrorKey(validation.reason)
    errors.push(t(errorKey))
  }

  return errors
}

const PASSWORD_VALIDATIONS = {
  required: {
    test: (value: string) => Boolean(value && typeof value === 'string'),
    getMessage: (t: (key: string) => string) => t('auth.passwordRequired'),
  },
  notEmpty: {
    test: (value: string) => value.trim().length > 0,
    getMessage: (t: (key: string) => string) => t('auth.passwordEmpty'),
  },
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

const validatePassword = (passwordValue: string, t: (key: string) => string): string[] => {
  const errors: string[] = []

  if (!PASSWORD_VALIDATIONS.required.test(passwordValue)) {
    errors.push(PASSWORD_VALIDATIONS.required.getMessage(t))
    return errors
  }

  if (!PASSWORD_VALIDATIONS.notEmpty.test(passwordValue)) {
    errors.push(PASSWORD_VALIDATIONS.notEmpty.getMessage(t))
    return errors
  }

  return errors
}

export default function LoginPage() {
  const { t } = useTranslation()
  const router = useRouter()
  const searchParams = useSearchParams()
  const { refetch: refetchSession } = useSession()
  const [isLoading, setIsLoading] = useState(false)
  const [mounted, setMounted] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [password, setPassword] = useState('')
  const [passwordErrors, setPasswordErrors] = useState<string[]>([])
  const [showValidationError, setShowValidationError] = useState(false)
  const [buttonClass, setButtonClass] = useState('auth-button-gradient')
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

  const [email, setEmail] = useState('')
  const [emailErrors, setEmailErrors] = useState<string[]>([])
  const [showEmailValidationError, setShowEmailValidationError] = useState(false)

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
    }

    const checkCustomBrand = () => {
      const computedStyle = getComputedStyle(document.documentElement)
      const brandAccent = computedStyle.getPropertyValue('--brand-accent-hex').trim()

      if (brandAccent && brandAccent !== '#6f3dfa') {
        setButtonClass('auth-button-custom')
      } else {
        setButtonClass('auth-button-gradient')
      }
    }

    checkCustomBrand()

    window.addEventListener('resize', checkCustomBrand)
    const observer = new MutationObserver(checkCustomBrand)
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['style', 'class'],
    })

    return () => {
      window.removeEventListener('resize', checkCustomBrand)
      observer.disconnect()
    }
  }, [searchParams])

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
  }, [forgotPasswordEmail, forgotPasswordOpen])

  const handleEmailChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newEmail = e.target.value
    setEmail(newEmail)

    const errors = validateEmailField(newEmail, t)
    setEmailErrors(errors)
    setShowEmailValidationError(false)
  }

  const handlePasswordChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newPassword = e.target.value
    setPassword(newPassword)

    const errors = validatePassword(newPassword, t)
    setPasswordErrors(errors)
    setShowValidationError(false)
  }

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setIsLoading(true)

    const formData = new FormData(e.currentTarget)
    const emailRaw = formData.get('email') as string
    const email = emailRaw.trim().toLowerCase()

    const emailValidationErrors = validateEmailField(email, t)
    setEmailErrors(emailValidationErrors)
    setShowEmailValidationError(emailValidationErrors.length > 0)

    const passwordValidationErrors = validatePassword(password, t)
    setPasswordErrors(passwordValidationErrors)
    setShowValidationError(passwordValidationErrors.length > 0)

    if (emailValidationErrors.length > 0) {
      toastError(emailValidationErrors[0])
      setIsLoading(false)
      return
    }
    if (passwordValidationErrors.length > 0) {
      toastError(passwordValidationErrors[0])
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
            } else if (
              errorCode.includes('USER_NOT_FOUND') ||
              errorMessage.includes('not found')
            ) {
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
        }
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

          if (errorCode.includes('INVALID_CREDENTIALS') ||
              errorMsg.includes('invalid password') ||
              errorMsg.includes('Incorrect email or password')) {
            displayMessage = t('auth.invalidCredentials')
          } else if (errorCode.includes('USER_NOT_FOUND') ||
                     errorMsg.includes('not found')) {
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
        .find(row => row.startsWith('csrf_token='))
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

  const handleForgotPassword = async () => {
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
  }

  return (
    <>
      <div className='space-y-1 text-center'>
        <h1 className={`${soehne.className} font-medium text-[32px] text-black tracking-tight`} suppressHydrationWarning>
          {mounted ? t('auth.signIn') : 'Sign In'}
        </h1>
        <p className={`${inter.className} font-[380] text-[16px] text-muted-foreground`} suppressHydrationWarning>
          {mounted ? t('auth.enterYourDetails') : 'Enter your details'}
        </p>
      </div>

      {!isFalsy(getEnv('NEXT_PUBLIC_EMAIL_PASSWORD_SIGNUP_ENABLED')) && (
        <form onSubmit={onSubmit} className={`${inter.className} mt-8 space-y-8`}>
          <div className='space-y-6'>
            <div className='space-y-2'>
              <div className='flex items-center justify-between'>
                <Label htmlFor='email' suppressHydrationWarning>
                  {mounted ? t('auth.email') : 'Email'}
                </Label>
              </div>
              <Input
                id='email'
                name='email'
                placeholder={mounted ? t('auth.enterYourEmail') : 'Enter your email'}
                required
                autoCapitalize='none'
                autoComplete='email'
                autoCorrect='off'
                value={email}
                onChange={handleEmailChange}
                className={cn(
                  'rounded-[10px] shadow-sm transition-colors focus:border-gray-400 focus:ring-2 focus:ring-gray-100',
                  showEmailValidationError &&
                    emailErrors.length > 0 &&
                    'border-red-500 focus:border-red-500 focus:ring-red-100 focus-visible:ring-red-500'
                )}
              />
            </div>
            <div className='space-y-2'>
              <div className='flex items-center justify-between'>
                <Label htmlFor='password' suppressHydrationWarning>
                  {mounted ? t('auth.password') : 'Password'}
                </Label>
                <button
                  type='button'
                  onClick={() => setForgotPasswordOpen(true)}
                  className='font-medium text-muted-foreground text-xs transition hover:text-foreground'
                  suppressHydrationWarning
                >
                  {mounted ? t('auth.forgotPassword') : 'Forgot password?'}
                </button>
              </div>
              <div className='relative'>
                <Input
                  id='password'
                  name='password'
                  required
                  type={showPassword ? 'text' : 'password'}
                  autoCapitalize='none'
                  autoComplete='current-password'
                  autoCorrect='off'
                  placeholder={mounted ? t('auth.enterYourPassword') : 'Enter your password'}
                  value={password}
                  onChange={handlePasswordChange}
                  className={cn(
                    'rounded-[10px] pr-10 shadow-sm transition-colors focus:border-gray-400 focus:ring-2 focus:ring-gray-100',
                    showValidationError &&
                      passwordErrors.length > 0 &&
                      'border-red-500 focus:border-red-500 focus:ring-red-100 focus-visible:ring-red-500'
                  )}
                />
                <button
                  type='button'
                  onClick={() => setShowPassword(!showPassword)}
                  className='-translate-y-1/2 absolute top-1/2 right-3 text-gray-500 transition hover:text-gray-700'
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                >
                  {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </div>
          </div>

          <Button
            type='submit'
            onMouseEnter={() => setIsButtonHovered(true)}
            onMouseLeave={() => setIsButtonHovered(false)}
            className='group inline-flex w-full items-center justify-center gap-2 rounded-[10px] border border-[#6F3DFA] bg-gradient-to-b from-[#8357FF] to-[#6F3DFA] py-[6px] pr-[10px] pl-[12px] text-[15px] text-white shadow-[inset_0_2px_4px_0_#9B77FF] transition-all'
            disabled={isLoading}
            suppressHydrationWarning
          >
            <span className='flex items-center gap-1'>
              {isLoading
                ? mounted
                  ? t('auth.signingIn')
                  : 'Signing in...'
                : mounted
                  ? t('auth.signIn')
                  : 'Sign In'}
              <span className='inline-flex transition-transform duration-200 group-hover:translate-x-0.5'>
                {isButtonHovered ? (
                  <ArrowRight className='h-4 w-4' aria-hidden='true' />
                ) : (
                  <ChevronRight className='h-4 w-4' aria-hidden='true' />
                )}
              </span>
            </span>
          </Button>
        </form>
      )}

      {!isFalsy(getEnv('NEXT_PUBLIC_EMAIL_PASSWORD_SIGNUP_ENABLED')) && (
        <div className={`${inter.className} pt-6 text-center font-light text-[14px]`} suppressHydrationWarning>
          <span className='font-normal'>
            {mounted ? t('auth.dontHaveAccount') : "Don't have an account?"}{' '}
          </span>
          <Link
            href={isInviteFlow ? `/signup?invite_flow=true&callbackUrl=${callbackUrl}` : '/signup'}
            className='font-medium text-[var(--brand-accent-hex)] underline-offset-4 transition hover:text-[var(--brand-accent-hover-hex)] hover:underline'
          >
            {mounted ? t('auth.signUp') : 'Sign Up'}
          </Link>
        </div>
      )}


      <Dialog open={forgotPasswordOpen} onOpenChange={setForgotPasswordOpen}>
        <DialogContent className='auth-card auth-card-shadow max-w-[540px] rounded-[10px] border backdrop-blur-sm'>
          <DialogHeader>
            <DialogTitle className='auth-text-primary font-semibold text-xl tracking-tight' suppressHydrationWarning>
              {mounted ? t('auth.resetPassword') : 'Reset Password'}
            </DialogTitle>
            <DialogDescription className='auth-text-secondary text-sm' suppressHydrationWarning>
              {mounted ? t('auth.resetPasswordDescription') : 'Enter your email to receive a password reset link'}
            </DialogDescription>
          </DialogHeader>
          <div className='space-y-4'>
            <div className='space-y-2'>
              <div className='flex items-center justify-between'>
                <Label htmlFor='reset-email' suppressHydrationWarning>
                  {mounted ? t('auth.email') : 'Email'}
                </Label>
              </div>
              <Input
                id='reset-email'
                value={forgotPasswordEmail}
                onChange={(e) => setForgotPasswordEmail(e.target.value)}
                placeholder={mounted ? t('auth.enterYourEmail') : 'Enter your email'}
                required
                type='email'
                className={cn(
                  'rounded-[10px] shadow-sm transition-colors focus:border-gray-400 focus:ring-2 focus:ring-gray-100',
                  resetStatus.type === 'error' &&
                    'border-red-500 focus:border-red-500 focus:ring-red-100 focus-visible:ring-red-500'
                )}
              />
            </div>
            <Button
              type='button'
              onClick={handleForgotPassword}
              onMouseEnter={() => setIsResetButtonHovered(true)}
              onMouseLeave={() => setIsResetButtonHovered(false)}
              className='group inline-flex w-full items-center justify-center gap-2 rounded-[10px] border border-[#6F3DFA] bg-gradient-to-b from-[#8357FF] to-[#6F3DFA] py-[6px] pr-[10px] pl-[12px] text-[15px] text-white shadow-[inset_0_2px_4px_0_#9B77FF] transition-all'
              disabled={isSubmittingReset}
            >
              <span className='flex items-center gap-1' suppressHydrationWarning>
                {isSubmittingReset
                  ? mounted
                    ? t('auth.sending')
                    : 'Sending...'
                  : mounted
                    ? t('auth.sendResetLink')
                    : 'Send Reset Link'}
                <span className='inline-flex transition-transform duration-200 group-hover:translate-x-0.5'>
                  {isResetButtonHovered ? (
                    <ArrowRight className='h-4 w-4' aria-hidden='true' />
                  ) : (
                    <ChevronRight className='h-4 w-4' aria-hidden='true' />
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
