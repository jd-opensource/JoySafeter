'use client'

import CryptoJS from 'crypto-js'
import { Pencil, LogOut, KeyRound, Eye, EyeOff, Sun, Moon, Monitor } from 'lucide-react'
import { useTheme } from 'next-themes'
import React, { useState } from 'react'

import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { apiPost } from '@/lib/api-client'
import { useSession, client } from '@/lib/auth/auth-client'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { useGeneralStore } from '@/stores/settings/general/store'
import { toastSuccess, toastError } from '@/lib/utils/toast'

/**
 * Password validation rules (same as signup form)
 */
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

/**
 * Get access token from cookie
 */
function getAccessTokenFromCookie(): string | null {
  if (typeof document === 'undefined') return null

  // Try various cookie names that might contain the access token
  const cookieNames = ['auth_token', 'session-token', 'session_token', 'access_token', 'auth-token']

  for (const name of cookieNames) {
    const value = document.cookie
      .split('; ')
      .find((row) => row.startsWith(`${name}=`))
      ?.split('=')[1]

    if (value) {
      return decodeURIComponent(value)
    }
  }

  return null
}

/**
 * Get user initials
 */
function getInitials(name?: string | null, email?: string): string {
  if (name) {
    const parts = name.split(' ')
    if (parts.length >= 2) {
      return `${parts[0][0]}${parts[1][0]}`.toUpperCase()
    }
    return name.slice(0, 2).toUpperCase()
  }
  if (email) {
    return email.slice(0, 2).toUpperCase()
  }
  return 'U'
}

export function ProfilePage() {
  const { t, i18n } = useTranslation()
  const session = useSession()
  const { theme, setTheme } = useTheme()

  const user = session.data?.user
  const [isEditingName, setIsEditingName] = useState(false)
  const [displayName, setDisplayName] = useState(user?.name || '')
  const [isResetDialogOpen, setIsResetDialogOpen] = useState(false)
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [passwordErrors, setPasswordErrors] = useState<string[]>([])
  const [showValidationError, setShowValidationError] = useState(false)

  const handleLogout = async () => {
    try {
      await client.signOut()
      await new Promise((resolve) => setTimeout(resolve, 100))
      window.location.href = '/signin'
    } catch (error) {
      console.error('Logout failed:', error)
      window.location.href = '/signin'
    }
  }

  const handleResetPasswordClick = () => {
    setIsResetDialogOpen(true)
  }

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

    if (passwordValue.length > 100) {
      errors.push(t('auth.passwordMaxLength'))
    }

    return errors
  }

  const handlePasswordChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newPasswordValue = e.target.value
    setNewPassword(newPasswordValue)

    const errors = validatePassword(newPasswordValue)
    setPasswordErrors(errors)
    setShowValidationError(false)
  }

  const handleConfirmPasswordChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setConfirmPassword(e.target.value)
  }

  const handleSubmitNewPassword = async (e: React.FormEvent) => {
    e.preventDefault()

    const errors = validatePassword(newPassword)
    setPasswordErrors(errors)
    setShowValidationError(errors.length > 0)

    if (errors.length > 0) {
      toastError(errors[0])
      return
    }

    if (newPassword !== confirmPassword) {
      toastError(t('auth.passwordsNotMatch'))
      return
    }

    try {
      setIsSubmitting(true)

      // Call API to reset password for current user (no old password required)
      // Hash password using SHA-256 (same as other auth endpoints)
      const hashedPassword = CryptoJS.SHA256(newPassword).toString()

      // Get access token from cookie and add to Authorization header
      const accessToken = getAccessTokenFromCookie()
      const headers: Record<string, string> = {}
      if (accessToken) {
        headers['Authorization'] = `Bearer ${accessToken}`
      }

      await apiPost(
        'auth/me/reset-password',
        {
          new_password: hashedPassword,
        },
        {
          headers,
        },
      )

      toastSuccess(t('auth.passwordResetSuccess'))

      // Close dialog immediately
      setIsResetDialogOpen(false)
      setNewPassword('')
      setConfirmPassword('')

      // Sign out and redirect to login page
      try {
        await client.signOut()
        // Wait a short time to ensure cookies are cleared
        await new Promise((resolve) => setTimeout(resolve, 200))
        // Redirect to login page
        window.location.href = '/signin?resetSuccess=true'
      } catch (error) {
        console.error('Error during logout:', error)
        // Even if logout fails, redirect to login page
        window.location.href = '/signin?resetSuccess=true'
      }
    } catch (error) {
      console.error('Error resetting password:', error)
      const errorMessage = error instanceof Error ? error.message : t('auth.passwordResetFailed')
      toastError(errorMessage)
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleCloseDialog = () => {
    if (!isSubmitting) {
      setIsResetDialogOpen(false)
      setNewPassword('')
      setConfirmPassword('')
      setShowPassword(false)
      setShowConfirmPassword(false)
      setPasswordErrors([])
      setShowValidationError(false)
    }
  }

  const handleNameSave = () => {
    // Stub: name update API not yet implemented
    setIsEditingName(false)
  }

  const handleNameCancel = () => {
    setDisplayName(user?.name || '')
    setIsEditingName(false)
  }

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="mx-auto max-w-2xl space-y-8">
        {/* User Profile Section */}
        <div className="flex flex-col gap-6 border-b border-border pb-8 sm:flex-row sm:items-center sm:justify-between">
          {/* User Avatar and Info */}
          <div className="flex items-center gap-5">
            <Avatar className="h-16 w-16 flex-shrink-0 shadow-sm ring-1 ring-border/50">
              {user?.image && <AvatarImage src={user.image} alt={user?.name || t('user.user')} />}
              <AvatarFallback className="bg-gradient-to-br from-[var(--brand-500)] to-[var(--brand-700)] text-lg font-medium text-white">
                {getInitials(user?.name, user?.email)}
              </AvatarFallback>
            </Avatar>

            <div className="flex-1 space-y-1">
              {isEditingName ? (
                <div className="flex items-center gap-2">
                  <Input
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    onBlur={handleNameSave}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleNameSave()
                      if (e.key === 'Escape') handleNameCancel()
                    }}
                    className="h-8 text-sm"
                    autoFocus
                  />
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <span className="text-xl font-semibold tracking-tight text-foreground">
                    {displayName || user?.name || t('user.user')}
                  </span>
                  <button
                    onClick={() => setIsEditingName(true)}
                    className="rounded p-1 transition-colors hover:bg-muted"
                    aria-label="Edit name"
                  >
                    <Pencil size={14} className="text-muted-foreground" />
                  </button>
                </div>
              )}
              <p className="text-sm text-muted-foreground">{user?.email}</p>
            </div>
          </div>

          <Button variant="secondary" onClick={handleResetPasswordClick} className="gap-2 self-start sm:self-center">
            <KeyRound size={16} className="text-muted-foreground" />
            {t('auth.resetPassword')}
          </Button>
        </div>

        {/* Preferences */}
        <div className="space-y-6 pt-2">
          <div className="space-y-1">
            <h3 className="text-lg font-semibold tracking-tight text-foreground">{t('settings.preferences')}</h3>
          </div>

          <div className="flex flex-col rounded-2xl bg-muted/30 ring-1 ring-border/20 p-1">
            <div className="flex items-center justify-between rounded-xl px-4 py-3 hover:bg-muted/50 transition-colors">
              <Label className="text-sm font-medium text-foreground">{t('common.language')}</Label>
              <Select value={i18n.language} onValueChange={(lang) => i18n.changeLanguage(lang)}>
                <SelectTrigger className="w-40 bg-background border-border/50 shadow-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="en">English</SelectItem>
                  <SelectItem value="zh">中文</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="mx-4 h-px bg-border/40" />

            <div className="flex items-center justify-between rounded-xl px-4 py-3 hover:bg-muted/50 transition-colors">
              <Label className="text-sm font-medium text-foreground">{t('settings.theme')}</Label>
              <ToggleGroup
                type="single"
                value={theme ?? 'system'}
                onValueChange={(val) => {
                  if (val) {
                    setTheme(val)
                    useGeneralStore.getState().setSettings({ theme: val as 'light' | 'dark' | 'system' })
                  }
                }}
                className="bg-background border border-border/50 shadow-sm rounded-lg p-0.5"
              >
                <ToggleGroupItem value="light" aria-label={t('settings.themeLight')} className="gap-2 h-8 px-3 rounded-md">
                  <Sun size={14} />
                  <span className="text-xs font-medium">{t('settings.themeLight')}</span>
                </ToggleGroupItem>
                <ToggleGroupItem value="dark" aria-label={t('settings.themeDark')} className="gap-2 h-8 px-3 rounded-md">
                  <Moon size={14} />
                  <span className="text-xs font-medium">{t('settings.themeDark')}</span>
                </ToggleGroupItem>
                <ToggleGroupItem value="system" aria-label={t('settings.themeSystem')} className="gap-2 h-8 px-3 rounded-md">
                  <Monitor size={14} />
                  <span className="text-xs font-medium">{t('settings.themeSystem')}</span>
                </ToggleGroupItem>
              </ToggleGroup>
            </div>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center pt-8">
          <Button variant="ghost" onClick={handleLogout} className="gap-2 text-muted-foreground hover:bg-destructive/10 hover:text-destructive">
            <LogOut size={16} />
            {t('user.logout')}
          </Button>
        </div>
      </div>

      {/* Reset Password Dialog */}
      <Dialog open={isResetDialogOpen} onOpenChange={handleCloseDialog}>
        <DialogContent className="flex max-h-[85vh] flex-col gap-0 overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface-elevated)] p-0 shadow-2xl sm:max-w-[425px]">
          <DialogHeader className="flex shrink-0 flex-row items-center gap-3 border-b border-[var(--border-muted)] px-6 py-4">
            <div className="shrink-0 rounded-lg border border-[var(--surface-1)] bg-[var(--brand-50)] p-1.5 text-[var(--brand-600)] shadow-sm">
              <KeyRound size={14} />
            </div>
            <div className="flex min-w-0 flex-col">
              <DialogTitle className="text-sm font-bold leading-tight">
                {t('auth.resetPassword')}
              </DialogTitle>
              <DialogDescription className="mt-0.5 text-xs text-muted-foreground">
                {t('auth.enterNewPassword')}
              </DialogDescription>
            </div>
          </DialogHeader>
          <form onSubmit={handleSubmitNewPassword} className="flex min-h-0 flex-1 flex-col">
            <div className="max-h-[60vh] space-y-4 overflow-y-auto p-6">
              <div className="space-y-2">
                <Label htmlFor="new-password" className="text-sm font-medium">
                  {t('auth.newPassword')}
                </Label>
                <div className="relative">
                  <Input
                    id="new-password"
                    type={showPassword ? 'text' : 'password'}
                    value={newPassword}
                    onChange={handlePasswordChange}
                    placeholder={t('auth.enterNewPassword')}
                    disabled={isSubmitting}
                    className={cn(
                      'pr-10',
                      showValidationError &&
                        passwordErrors.length > 0 &&
                        'border-destructive focus:border-destructive focus:ring-destructive/20',
                    )}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    disabled={isSubmitting}
                    aria-label="Toggle password visibility"
                  >
                    {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
                {showValidationError && passwordErrors.length > 0 && (
                  <div className="space-y-1 text-xs text-destructive">
                    {passwordErrors.map((error, index) => (
                      <p key={index}>{error}</p>
                    ))}
                  </div>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="confirm-password" className="text-sm font-medium">
                  {t('auth.confirmPassword')}
                </Label>
                <div className="relative">
                  <Input
                    id="confirm-password"
                    type={showConfirmPassword ? 'text' : 'password'}
                    value={confirmPassword}
                    onChange={handleConfirmPasswordChange}
                    placeholder={t('auth.confirmNewPassword')}
                    disabled={isSubmitting}
                    className="pr-10"
                  />
                  <button
                    type="button"
                    onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    disabled={isSubmitting}
                    aria-label="Toggle confirm password visibility"
                  >
                    {showConfirmPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>
            </div>

            <div className="flex flex-col-reverse gap-2 border-t border-[var(--border-muted)] px-6 py-4 sm:flex-row sm:justify-end">
              <Button
                type="button"
                variant="outline"
                onClick={handleCloseDialog}
                disabled={isSubmitting}
              >
                {t('common.cancel')}
              </Button>
              <Button type="submit" disabled={isSubmitting || !newPassword || !confirmPassword}>
                {isSubmitting ? t('common.saving') : t('auth.resetPassword')}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
