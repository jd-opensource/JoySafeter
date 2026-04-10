'use client'

import { ArrowRight, ChevronRight, Eye, EyeOff } from 'lucide-react'
import { useEffect, useState } from 'react'


import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { toastError, toastSuccess } from '@/lib/utils/toast'
import { inter } from '@/styles/fonts/inter/inter'

interface RequestResetFormProps {
  email: string
  onEmailChange: (email: string) => void
  onSubmit: (email: string) => Promise<void>
  isSubmitting: boolean
  statusType: 'success' | 'error' | null
  statusMessage: string
  className?: string
}

export function RequestResetForm({
  email,
  onEmailChange,
  onSubmit,
  isSubmitting,
  statusType,
  statusMessage,
  className,
}: RequestResetFormProps) {
  const { t } = useTranslation()
  const [mounted, setMounted] = useState(false)
  const [isButtonHovered, setIsButtonHovered] = useState(false)

  useEffect(() => {
    queueMicrotask(() => setMounted(true))
    // Display status message toast
    if (statusType && statusMessage) {
      if (statusType === 'error') {
        toastError(statusMessage)
      } else if (statusType === 'success') {
        toastSuccess(statusMessage)
      }
    }
  }, [statusType, statusMessage])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    onSubmit(email)
  }

  return (
    <form onSubmit={handleSubmit} className={cn(`${inter.className} space-y-8`, className)}>
      <div className="space-y-6">
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label htmlFor="reset-email" suppressHydrationWarning>
              {mounted ? t('auth.email') : 'Email'}
            </Label>
          </div>
          <Input
            id="reset-email"
            value={email}
            onChange={(e) => onEmailChange(e.target.value)}
            placeholder={mounted ? t('auth.enterYourEmail') : 'Enter your email'}
            type="email"
            disabled={isSubmitting}
            required
            className="rounded-auth shadow-sm transition-colors focus:border-[var(--border-strong)] focus:ring-2 focus:ring-[var(--border-muted)]"
          />
          <p className="text-sm text-muted-foreground" suppressHydrationWarning>
            {mounted
              ? t('auth.sendResetLinkDescription')
              : 'We will send you a password reset link'}
          </p>
        </div>
      </div>

      <Button
        type="submit"
        disabled={isSubmitting}
        onMouseEnter={() => setIsButtonHovered(true)}
        onMouseLeave={() => setIsButtonHovered(false)}
        className="group inline-flex w-full items-center justify-center gap-2 rounded-auth border border-[var(--brand-500)] bg-gradient-to-b from-[var(--brand-400)] to-[var(--brand-500)] py-1.5 px-3 pr-2.5 text-app-base text-white shadow-[inset_0_2px_4px_0_var(--brand-200)] transition-all"
      >
        <span className="flex items-center gap-1" suppressHydrationWarning>
          {isSubmitting
            ? mounted
              ? t('auth.sending')
              : 'Sending...'
            : mounted
              ? t('auth.sendResetLink')
              : 'Send Reset Link'}
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
  )
}

interface SetNewPasswordFormProps {
  token: string | null
  onSubmit: (password: string) => Promise<void>
  isSubmitting: boolean
  statusType: 'success' | 'error' | null
  statusMessage: string
  className?: string
}

export function SetNewPasswordForm({
  token,
  onSubmit,
  isSubmitting,
  statusType,
  statusMessage,
  className,
}: SetNewPasswordFormProps) {
  const { t } = useTranslation()
  const [mounted, setMounted] = useState(false)
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [validationMessage, setValidationMessage] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)
  const [isButtonHovered, setIsButtonHovered] = useState(false)

  useEffect(() => {
    queueMicrotask(() => setMounted(true))
    if (statusType && statusMessage) {
      if (statusType === 'error') {
        toastError(statusMessage)
      } else if (statusType === 'success') {
        toastSuccess(statusMessage)
      }
    }
    if (validationMessage) {
      toastError(validationMessage)
    }
  }, [statusType, statusMessage, validationMessage])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (password.length < 8) {
      const errorMsg = t('auth.passwordMinLength')
      setValidationMessage(errorMsg)
      toastError(errorMsg)
      return
    }

    if (password.length > 100) {
      const errorMsg = t('auth.passwordMaxLength')
      setValidationMessage(errorMsg)
      toastError(errorMsg)
      return
    }

    if (!/[A-Z]/.test(password)) {
      const errorMsg = t('auth.passwordUppercase')
      setValidationMessage(errorMsg)
      toastError(errorMsg)
      return
    }

    if (!/[a-z]/.test(password)) {
      const errorMsg = t('auth.passwordLowercase')
      setValidationMessage(errorMsg)
      toastError(errorMsg)
      return
    }

    if (!/[0-9]/.test(password)) {
      const errorMsg = t('auth.passwordNumber')
      setValidationMessage(errorMsg)
      toastError(errorMsg)
      return
    }

    if (!/[^A-Za-z0-9]/.test(password)) {
      const errorMsg = t('auth.passwordSpecial')
      setValidationMessage(errorMsg)
      toastError(errorMsg)
      return
    }

    if (password !== confirmPassword) {
      const errorMsg = t('auth.passwordsNotMatch')
      setValidationMessage(errorMsg)
      toastError(errorMsg)
      return
    }

    setValidationMessage('')
    onSubmit(password)
  }

  return (
    <form onSubmit={handleSubmit} className={cn(`${inter.className} space-y-8`, className)}>
      <div className="space-y-6">
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label htmlFor="password" suppressHydrationWarning>
              {mounted ? t('auth.newPassword') : 'New Password'}
            </Label>
          </div>
          <div className="relative">
            <Input
              id="password"
              type={showPassword ? 'text' : 'password'}
              autoCapitalize="none"
              autoComplete="new-password"
              autoCorrect="off"
              disabled={isSubmitting || !token}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              placeholder={mounted ? t('auth.enterNewPassword') : 'Enter new password'}
              className={cn(
                'rounded-auth pr-10 shadow-sm transition-colors focus:border-[var(--border-strong)] focus:ring-2 focus:ring-[var(--border-muted)]',
                validationMessage &&
                  'border-[var(--status-error)] focus:border-[var(--status-error)] focus:ring-[var(--status-error-bg)] focus-visible:ring-[var(--status-error)]',
              )}
            />
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)] transition hover:text-[var(--text-secondary)]"
              aria-label={showPassword ? 'Hide password' : 'Show password'}
            >
              {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
            </button>
          </div>
        </div>
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label htmlFor="confirmPassword" suppressHydrationWarning>
              {mounted ? t('auth.confirmPassword') : 'Confirm Password'}
            </Label>
          </div>
          <div className="relative">
            <Input
              id="confirmPassword"
              type={showConfirmPassword ? 'text' : 'password'}
              autoCapitalize="none"
              autoComplete="new-password"
              autoCorrect="off"
              disabled={isSubmitting || !token}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              placeholder={mounted ? t('auth.confirmNewPassword') : 'Confirm new password'}
              className={cn(
                'rounded-auth pr-10 shadow-sm transition-colors focus:border-[var(--border-strong)] focus:ring-2 focus:ring-[var(--border-muted)]',
                validationMessage &&
                  'border-[var(--status-error)] focus:border-[var(--status-error)] focus:ring-[var(--status-error-bg)] focus-visible:ring-[var(--status-error)]',
              )}
            />
            <button
              type="button"
              onClick={() => setShowConfirmPassword(!showConfirmPassword)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)] transition hover:text-[var(--text-secondary)]"
              aria-label={showConfirmPassword ? 'Hide password' : 'Show password'}
            >
              {showConfirmPassword ? <EyeOff size={18} /> : <Eye size={18} />}
            </button>
          </div>
        </div>
      </div>

      <Button
        disabled={isSubmitting || !token}
        type="submit"
        onMouseEnter={() => setIsButtonHovered(true)}
        onMouseLeave={() => setIsButtonHovered(false)}
        className="group inline-flex w-full items-center justify-center gap-2 rounded-auth border border-[var(--brand-500)] bg-gradient-to-b from-[var(--brand-400)] to-[var(--brand-500)] py-1.5 px-3 pr-2.5 text-app-base text-white shadow-[inset_0_2px_4px_0_var(--brand-200)] transition-all"
      >
        <span className="flex items-center gap-1" suppressHydrationWarning>
          {isSubmitting
            ? mounted
              ? t('auth.resettingPassword')
              : 'Resetting password...'
            : mounted
              ? t('auth.resetPassword')
              : 'Reset Password'}
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
  )
}
