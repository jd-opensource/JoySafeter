'use client'

import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { Suspense, useEffect, useState } from 'react'

import { SetNewPasswordForm } from '@/app/(auth)/reset-password/reset-password-form'
import { authApi } from '@/lib/auth/api-client'
import { createLogger } from '@/lib/logs/console/logger'
import { inter } from '@/styles/fonts/inter/inter'
import { soehne } from '@/styles/fonts/soehne/soehne'

const logger = createLogger('ResetPasswordPage')

function ResetPasswordContent() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const token = searchParams.get('token')

  const [isSubmitting, setIsSubmitting] = useState(false)
  const [statusMessage, setStatusMessage] = useState<{
    type: 'success' | 'error' | null
    text: string
  }>({
    type: null,
    text: '',
  })

  useEffect(() => {
    if (!token) {
      setStatusMessage({
        type: 'error',
        text: 'Invalid or missing reset token. Please request a new password reset link.',
      })
    }
  }, [token])

  const handleResetPassword = async (password: string) => {
    if (!token) {
      setStatusMessage({
        type: 'error',
        text: 'Invalid or missing reset token',
      })
      return
    }

    try {
      setIsSubmitting(true)
      setStatusMessage({ type: null, text: '' })

      // Use API client, automatically performs SHA-256 hashing
      await authApi.resetPassword({
        token,
        newPassword: password,
      })

      setStatusMessage({
        type: 'success',
        text: 'Password reset successful! Redirecting to login...',
      })

      setTimeout(() => {
        router.push('/signin?resetSuccess=true')
      }, 1500)
    } catch (error) {
      logger.error('Error resetting password:', { error })
      setStatusMessage({
        type: 'error',
        text: error instanceof Error ? error.message : 'Failed to reset password',
      })
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <>
      <div className='space-y-1 text-center'>
        <h1 className={`${soehne.className} font-medium text-[32px] text-black tracking-tight`}>
          Reset your password
        </h1>
        <p className={`${inter.className} font-[380] text-[16px] text-muted-foreground`}>
          Enter a new password for your account
        </p>
      </div>

      <div className={`${inter.className} mt-8`}>
        <SetNewPasswordForm
          token={token}
          onSubmit={handleResetPassword}
          isSubmitting={isSubmitting}
          statusType={statusMessage.type}
          statusMessage={statusMessage.text}
        />
      </div>

      <div className={`${inter.className} pt-6 text-center font-light text-[14px]`}>
        <Link
          href='/signin'
          className='font-medium text-[var(--brand-accent-hex)] underline-offset-4 transition hover:text-[var(--brand-accent-hover-hex)] hover:underline'
        >
          Back to signin
        </Link>
      </div>
    </>
  )
}

export default function ResetPasswordPage() {
  return (
    <Suspense
      fallback={<div className='flex h-screen items-center justify-center'>Loading...</div>}
    >
      <ResetPasswordContent />
    </Suspense>
  )
}
