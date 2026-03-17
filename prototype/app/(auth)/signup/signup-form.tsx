'use client'

import { ArrowRight, ChevronRight, Eye, EyeOff } from 'lucide-react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { Suspense, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { client, useSession, type AuthError } from '@/lib/auth/auth-client'
import { getEnv, isFalsy } from '@/lib/core/config/env'
import { cn } from '@/lib/core/utils/cn'
import { createLogger } from '@/lib/logs/console/logger'
import { toastError, toastSuccess } from '@/lib/utils/toast'
import { quickValidateEmail } from '@/services/email/validation'
import { inter } from '@/styles/fonts/inter/inter'
import { soehne } from '@/styles/fonts/soehne/soehne'

const logger = createLogger('SignupForm')

const PASSWORD_VALIDATIONS = {
  minLength: {
    regex: /.{8,}/,
    getMessage: (t: (key: string) => string) => t('auth.passwordMinLength'),
  },
  uppercase: {
    regex: /(?=.*?[A-Z])/,
    getMessage: (t: (key: string) => string) => t('auth.passwordUppercase'),
  },
  lowercase: {
    regex: /(?=.*?[a-z])/,
    getMessage: (t: (key: string) => string) => t('auth.passwordLowercase'),
  },
  number: {
    regex: /(?=.*?[0-9])/,
    getMessage: (t: (key: string) => string) => t('auth.passwordNumber'),
  },
  special: {
    regex: /(?=.*?[#?!@$%^&*-])/,
    getMessage: (t: (key: string) => string) => t('auth.passwordSpecial'),
  },
}

const NAME_VALIDATIONS = {
  required: {
    test: (value: string) => Boolean(value && typeof value === 'string'),
    getMessage: (t: (key: string) => string) => t('auth.nameRequired'),
  },
  notEmpty: {
    test: (value: string) => value.trim().length > 0,
    getMessage: (t: (key: string) => string) => t('auth.nameEmpty'),
  },
  validCharacters: {
    regex: /^[\p{L}\s\-']+$/u,
    getMessage: (t: (key: string) => string) => t('auth.nameInvalidCharacters'),
  },
  noConsecutiveSpaces: {
    regex: /^(?!.*\s\s).*$/,
    getMessage: (t: (key: string) => string) => t('auth.nameConsecutiveSpaces'),
  },
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

function SignupFormContent() {
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
  const [email, setEmail] = useState('')
  const [emailError, setEmailError] = useState('')
  const [emailErrors, setEmailErrors] = useState<string[]>([])
  const [showEmailValidationError, setShowEmailValidationError] = useState(false)
  const [redirectUrl, setRedirectUrl] = useState('')
  const [isInviteFlow, setIsInviteFlow] = useState(false)
  const [buttonClass, setButtonClass] = useState('auth-button-gradient')
  const [isButtonHovered, setIsButtonHovered] = useState(false)

  const [name, setName] = useState('')
  const [nameErrors, setNameErrors] = useState<string[]>([])
  const [showNameValidationError, setShowNameValidationError] = useState(false)

  useEffect(() => {
    queueMicrotask(() => setMounted(true))
    const emailParam = searchParams.get('email')
    if (emailParam) {
      setEmail(emailParam)
    }

    const redirectParam = searchParams.get('redirect')
    if (redirectParam) {
      setRedirectUrl(redirectParam)

      if (redirectParam.startsWith('/invite/')) {
        setIsInviteFlow(true)
      }
    }

    const inviteFlowParam = searchParams.get('invite_flow')
    if (inviteFlowParam === 'true') {
      setIsInviteFlow(true)
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

  const validatePassword = (passwordValue: string): string[] => {
    const errors: string[] = []

    if (!PASSWORD_VALIDATIONS.minLength.regex.test(passwordValue)) {
      errors.push(PASSWORD_VALIDATIONS.minLength.getMessage(t))
    }

    if (!PASSWORD_VALIDATIONS.uppercase.regex.test(passwordValue)) {
      errors.push(PASSWORD_VALIDATIONS.uppercase.getMessage(t))
    }

    if (!PASSWORD_VALIDATIONS.lowercase.regex.test(passwordValue)) {
      errors.push(PASSWORD_VALIDATIONS.lowercase.getMessage(t))
    }

    if (!PASSWORD_VALIDATIONS.number.regex.test(passwordValue)) {
      errors.push(PASSWORD_VALIDATIONS.number.getMessage(t))
    }

    if (!PASSWORD_VALIDATIONS.special.regex.test(passwordValue)) {
      errors.push(PASSWORD_VALIDATIONS.special.getMessage(t))
    }

    return errors
  }

  const validateName = (nameValue: string): string[] => {
    const errors: string[] = []

    if (!NAME_VALIDATIONS.required.test(nameValue)) {
      errors.push(NAME_VALIDATIONS.required.getMessage(t))
      return errors
    }

    if (!NAME_VALIDATIONS.notEmpty.test(nameValue)) {
      errors.push(NAME_VALIDATIONS.notEmpty.getMessage(t))
      return errors
    }

    if (!NAME_VALIDATIONS.validCharacters.regex.test(nameValue.trim())) {
      errors.push(NAME_VALIDATIONS.validCharacters.getMessage(t))
    }

    if (!NAME_VALIDATIONS.noConsecutiveSpaces.regex.test(nameValue)) {
      errors.push(NAME_VALIDATIONS.noConsecutiveSpaces.getMessage(t))
    }

    return errors
  }

  const handlePasswordChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newPassword = e.target.value
    setPassword(newPassword)

    const errors = validatePassword(newPassword)
    setPasswordErrors(errors)
    setShowValidationError(false)
  }

  const handleNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const rawValue = e.target.value
    setName(rawValue)

    const errors = validateName(rawValue)
    setNameErrors(errors)
    setShowNameValidationError(false)
  }

  const handleEmailChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newEmail = e.target.value
    setEmail(newEmail)

    const errors = validateEmailField(newEmail, t)
    setEmailErrors(errors)
    setShowEmailValidationError(false)

    if (emailError) {
      setEmailError('')
    }
  }

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setIsLoading(true)

    const formData = new FormData(e.currentTarget)
    const emailValueRaw = formData.get('email') as string
    const emailValue = emailValueRaw.trim().toLowerCase()
    const passwordValue = formData.get('password') as string
    const nameValue = formData.get('name') as string

    const trimmedName = nameValue.trim()

    const nameValidationErrors = validateName(trimmedName)
    setNameErrors(nameValidationErrors)
    setShowNameValidationError(nameValidationErrors.length > 0)

    const emailValidationErrors = validateEmailField(emailValue, t)
    setEmailErrors(emailValidationErrors)
    setShowEmailValidationError(emailValidationErrors.length > 0)

    const errors = validatePassword(passwordValue)
    setPasswordErrors(errors)

    setShowValidationError(errors.length > 0)

    try {
      if (nameValidationErrors.length > 0) {
        toastError(nameValidationErrors[0])
        setIsLoading(false)
        return
      }
      if (emailValidationErrors.length > 0) {
        toastError(emailValidationErrors[0])
        setIsLoading(false)
        return
      }
      if (errors.length > 0) {
        toastError(errors[0])
        setIsLoading(false)
        return
      }

      if (trimmedName.length > 100) {
        toastError(t('auth.nameTooLong'))
        setIsLoading(false)
        return
      }

      const sanitizedName = trimmedName

      const response = await client.signUp.email(
        {
          email: emailValue,
          password: passwordValue,
          name: sanitizedName,
        },
        {
          onError: (ctx: { error: AuthError }) => {
            logger.error('Signup error:', ctx.error)
            // Safely get code and message
            const errorCode = typeof ctx.error.code === 'string' ? ctx.error.code : ''
            const errorMessage = typeof ctx.error.message === 'string' ? ctx.error.message : ''

            if (
              errorCode.includes('USER_ALREADY_EXISTS') ||
              errorMessage.includes('already registered')
            ) {
              toastError(t('auth.userAlreadyExists'))
            } else if (
              errorCode.includes('BAD_REQUEST') ||
              errorMessage.includes('Email and password sign up is not enabled')
            ) {
              toastError(t('auth.emailSignInDisabled'))
            } else if (errorCode.includes('INVALID_EMAIL')) {
              toastError(t('auth.emailInvalid'))
            } else if (errorCode.includes('PASSWORD_TOO_SHORT')) {
              toastError(t('auth.passwordMinLength'))
            } else if (errorCode.includes('PASSWORD_TOO_LONG')) {
              toastError(t('auth.passwordMaxLength'))
            } else if (errorCode.includes('network')) {
              toastError(t('auth.networkError'))
            } else if (errorCode.includes('rate limit')) {
              toastError(t('auth.rateLimitError'))
            } else {
              toastError(errorMessage || t('auth.invalidCredentials'))
            }
          },
        }
      )

      if (!response || response.error) {
        setIsLoading(false)
        return
      }

      // Registration successful, display success message
      toastSuccess(t('auth.registrationSuccess') || 'Registration successful! Please sign in to continue.')

      if (typeof window !== 'undefined') {
        sessionStorage.setItem('verificationEmail', emailValue)
        if (isInviteFlow && redirectUrl) {
          sessionStorage.setItem('inviteRedirectUrl', redirectUrl)
          sessionStorage.setItem('isInviteFlow', 'true')
        }
      }

      // Redirect to login page, don't auto-login
      setTimeout(() => {
        router.push('/signin')
      }, 500)
    } catch (error) {
      logger.error('Signup error:', error)
      setIsLoading(false)
    }
  }

  return (
    <>
      <div className='space-y-1 text-center'>
        <h1 className={`${soehne.className} font-medium text-[32px] text-black tracking-tight`} suppressHydrationWarning>
          {mounted ? t('auth.createAccount') : 'Create Account'}
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
                <Label htmlFor='name' suppressHydrationWarning>
                  {mounted ? t('auth.fullName') : 'Full Name'}
                </Label>
              </div>
              <Input
                id='name'
                name='name'
                placeholder={mounted ? t('auth.enterYourName') : 'Enter your name'}
                type='text'
                autoCapitalize='words'
                autoComplete='name'
                title='Name can only contain letters, spaces, hyphens, and apostrophes'
                value={name}
                onChange={handleNameChange}
                className={cn(
                  'rounded-[10px] shadow-sm transition-colors focus:border-gray-400 focus:ring-2 focus:ring-gray-100',
                  showNameValidationError &&
                    nameErrors.length > 0 &&
                    'border-red-500 focus:border-red-500 focus:ring-red-100 focus-visible:ring-red-500'
                )}
              />
            </div>
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
                autoCapitalize='none'
                autoComplete='email'
                autoCorrect='off'
                value={email}
                onChange={handleEmailChange}
                className={cn(
                  'rounded-[10px] shadow-sm transition-colors focus:border-gray-400 focus:ring-2 focus:ring-gray-100',
                  (emailError || (showEmailValidationError && emailErrors.length > 0)) &&
                    'border-red-500 focus:border-red-500 focus:ring-red-100 focus-visible:ring-red-500'
                )}
              />
            </div>
            <div className='space-y-2'>
              <div className='flex items-center justify-between'>
                <Label htmlFor='password' suppressHydrationWarning>
                  {mounted ? t('auth.password') : 'Password'}
                </Label>
              </div>
              <div className='relative'>
                <Input
                  id='password'
                  name='password'
                  type={showPassword ? 'text' : 'password'}
                  autoCapitalize='none'
                  autoComplete='new-password'
                  placeholder={mounted ? t('auth.enterYourPassword') : 'Enter your password'}
                  autoCorrect='off'
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
                  ? t('auth.creatingAccount')
                  : 'Creating account...'
                : mounted
                  ? t('auth.createAccount')
                  : 'Create Account'}
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

      <div className={`${inter.className} pt-6 text-center font-light text-[14px]`} suppressHydrationWarning>
        <span className='font-normal'>
          {mounted ? t('auth.alreadyHaveAccount') : 'Already have an account?'}{' '}
        </span>
        <Link
          href={isInviteFlow ? `/signin?invite_flow=true&callbackUrl=${redirectUrl}` : '/signin'}
          className='font-medium text-[var(--brand-accent-hex)] underline-offset-4 transition hover:text-[var(--brand-accent-hover-hex)] hover:underline'
        >
          {mounted ? t('auth.signIn') : 'Sign In'}
        </Link>
      </div>

    </>
  )
}

export default function SignupPage() {
  return (
    <Suspense
      fallback={<div className='flex h-screen items-center justify-center'>Loading...</div>}
    >
      <SignupFormContent
      />
    </Suspense>
  )
}
