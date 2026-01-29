'use client'

import CryptoJS from 'crypto-js'
import { Pencil, LogOut, KeyRound, Eye, EyeOff } from 'lucide-react'
import { useRouter } from 'next/navigation'
import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'

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
import { apiPost } from '@/lib/api-client'
import { useSession, client } from '@/lib/auth/auth-client'
import { cn } from '@/lib/utils'
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
  const cookieNames = [
    'auth_token',
    'session-token',
    'session_token',
    'access_token',
    'auth-token',
  ]

  for (const name of cookieNames) {
    const value = document.cookie
      .split('; ')
      .find(row => row.startsWith(`${name}=`))
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
  const { t } = useTranslation()
  const router = useRouter()
  const session = useSession()

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
      await new Promise(resolve => setTimeout(resolve, 100))
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

      await apiPost('auth/me/reset-password', {
        new_password: hashedPassword,
      }, {
        headers,
      })

      toastSuccess(t('auth.passwordResetSuccess'))

      // Close dialog immediately
      setIsResetDialogOpen(false)
      setNewPassword('')
      setConfirmPassword('')

      // Sign out and redirect to login page
      try {
        await client.signOut()
        // Wait a short time to ensure cookies are cleared
        await new Promise(resolve => setTimeout(resolve, 200))
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
    // TODO: Implement name update API call
    setIsEditingName(false)
    // For now, just update local state
  }

  const handleNameCancel = () => {
    setDisplayName(user?.name || '')
    setIsEditingName(false)
  }

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-2xl mx-auto space-y-8">
        {/* User Profile Section */}
        <div className="space-y-6">
          {/* User Avatar and Info */}
          <div className="flex items-center gap-4">
            <Avatar className="h-16 w-16 flex-shrink-0">
              {user?.image && <AvatarImage src={user.image} alt={user?.name || t('user.user')} />}
              <AvatarFallback className="bg-pink-500 text-white text-lg font-medium">
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
                  <span className="text-lg font-medium text-gray-900">{displayName || user?.name || t('user.user')}</span>
                  <button
                    onClick={() => setIsEditingName(true)}
                    className="p-1 hover:bg-gray-100 rounded transition-colors"
                    aria-label="Edit name"
                  >
                    <Pencil size={14} className="text-gray-500" />
                  </button>
                </div>
              )}
              <p className="text-sm text-gray-500">{user?.email}</p>
            </div>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-3 pt-6 border-t border-gray-200">
          <Button
            variant="outline"
            onClick={handleLogout}
            className="flex items-center gap-2"
          >
            <LogOut size={16} />
            {t('user.logout')}
          </Button>
          <Button
            variant="outline"
            onClick={handleResetPasswordClick}
            className="flex items-center gap-2"
          >
            <KeyRound size={16} />
            {t('auth.resetPassword')}
          </Button>
        </div>
      </div>

      {/* Reset Password Dialog */}
      <Dialog open={isResetDialogOpen} onOpenChange={handleCloseDialog}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{t('auth.resetPassword')}</DialogTitle>
            <DialogDescription>
              {t('auth.enterNewPassword')}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmitNewPassword} className="space-y-4">
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
                    "pr-10",
                    showValidationError &&
                      passwordErrors.length > 0 &&
                      'border-red-500 focus:border-red-500 focus:ring-red-100'
                  )}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-700"
                  disabled={isSubmitting}
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
              {showValidationError && passwordErrors.length > 0 && (
                <div className="space-y-1 text-xs text-red-600">
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
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-700"
                  disabled={isSubmitting}
                >
                  {showConfirmPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-4">
              <Button
                type="button"
                variant="outline"
                onClick={handleCloseDialog}
                disabled={isSubmitting}
              >
                {t('common.cancel')}
              </Button>
              <Button
                type="submit"
                disabled={isSubmitting || !newPassword || !confirmPassword}
              >
                {isSubmitting ? t('common.saving') : t('auth.resetPassword')}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
