'use client'

import { useRouter, useSearchParams } from 'next/navigation'
import { useEffect, useState } from 'react'

import { client, useSession } from '@/lib/auth/auth-client'
import { createLogger } from '@/lib/logs/console/logger'

const logger = createLogger('useVerification')

interface UseVerificationParams {
  hasEmailService: boolean
  isProduction: boolean
  isEmailVerificationEnabled: boolean
}

interface UseVerificationReturn {
  otp: string
  email: string
  isLoading: boolean
  isVerified: boolean
  isInvalidOtp: boolean
  errorMessage: string
  isOtpComplete: boolean
  hasEmailService: boolean
  isProduction: boolean
  isEmailVerificationEnabled: boolean
  verifyCode: () => Promise<void>
  resendCode: () => void
  handleOtpChange: (value: string) => void
}

export function useVerification({
  hasEmailService,
  isProduction,
  isEmailVerificationEnabled,
}: UseVerificationParams): UseVerificationReturn {
  const router = useRouter()
  const searchParams = useSearchParams()
  const { refetch: refetchSession } = useSession()
  const [otp, setOtp] = useState('')
  const [email, setEmail] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isVerified, setIsVerified] = useState(false)
  const [isSendingInitialOtp, setIsSendingInitialOtp] = useState(false)
  const [isInvalidOtp, setIsInvalidOtp] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')
  const [redirectUrl, setRedirectUrl] = useState<string | null>(null)
  const [isInviteFlow, setIsInviteFlow] = useState(false)

  /**
   * Validate if redirect URL is safe
   * Prevent open redirect attacks
   */
  const isValidRedirectUrl = (url: string | null): boolean => {
    if (!url) return false

    try {
      // Only allow relative paths
      if (!url.startsWith('/')) {
        logger.warn('Invalid redirect URL: not a relative path', { url })
        return false
      }

      // Prevent path traversal attacks
      if (url.includes('..') || url.includes('//')) {
        logger.warn('Invalid redirect URL: path traversal detected', { url })
        return false
      }

      // Prevent dangerous protocols
      if (url.match(/^(javascript|data|vbscript|file):/i)) {
        logger.warn('Invalid redirect URL: dangerous protocol detected', { url })
        return false
      }

      // Whitelist check: only allow specific paths
      const allowedPaths = ['/chat', '/workspace', '/dashboard']
      const isAllowed = allowedPaths.some(path => url.startsWith(path))

      if (!isAllowed) {
        logger.warn('Invalid redirect URL: not in whitelist', { url })
        return false
      }

      return true
    } catch (error) {
      logger.error('Error validating redirect URL', { error, url })
      return false
    }
  }

  useEffect(() => {
    if (typeof window !== 'undefined') {
      const storedEmail = sessionStorage.getItem('verificationEmail')
      if (storedEmail) {
        setEmail(storedEmail)
      }

      const storedRedirectUrl = sessionStorage.getItem('inviteRedirectUrl')
      if (storedRedirectUrl && isValidRedirectUrl(storedRedirectUrl)) {
        setRedirectUrl(storedRedirectUrl)
      }

      const storedIsInviteFlow = sessionStorage.getItem('isInviteFlow')
      if (storedIsInviteFlow === 'true') {
        setIsInviteFlow(true)
      }
    }

    const redirectParam = searchParams.get('redirectAfter')
    if (redirectParam && isValidRedirectUrl(redirectParam)) {
      setRedirectUrl(redirectParam)
    }

    const inviteFlowParam = searchParams.get('invite_flow')
    if (inviteFlowParam === 'true') {
      setIsInviteFlow(true)
    }
  }, [searchParams])

  useEffect(() => {
    if (email && !isSendingInitialOtp && hasEmailService) {
      setIsSendingInitialOtp(true)
    }
  }, [email, isSendingInitialOtp, hasEmailService])

  const isOtpComplete = otp.length === 6

  async function verifyCode() {
    if (!isOtpComplete || !email) return

    setIsLoading(true)
    setIsInvalidOtp(false)
    setErrorMessage('')

    try {
      const normalizedEmail = email.trim().toLowerCase()
      const response = await client.signIn.emailOtp({
        email: normalizedEmail,
        otp,
      })

      if (response && !response.error) {
        setIsVerified(true)

        try {
          await refetchSession()
        } catch (e) {
          logger.warn('Failed to refetch session after verification', e)
        }

        if (typeof window !== 'undefined') {
          sessionStorage.removeItem('verificationEmail')

          if (isInviteFlow) {
            sessionStorage.removeItem('inviteRedirectUrl')
            sessionStorage.removeItem('isInviteFlow')
          }
        }

        setTimeout(() => {
          if (isInviteFlow && redirectUrl) {
            window.location.href = redirectUrl
          } else {
            window.location.href = '/chat'
          }
        }, 1000)
      } else {
        logger.info('Setting invalid OTP state - API error response')
        const message = 'Invalid verification code. Please check and try again.'
        setIsInvalidOtp(true)
        setErrorMessage(message)
        logger.info('Error state after API error:', {
          isInvalidOtp: true,
          errorMessage: message,
        })
        setOtp('')
      }
    } catch (error: any) {
      let message = 'Verification failed. Please check your code and try again.'

      if (error.message?.includes('expired')) {
        message = 'The verification code has expired. Please request a new one.'
      } else if (error.message?.includes('invalid')) {
        logger.info('Setting invalid OTP state - caught error')
        message = 'Invalid verification code. Please check and try again.'
      } else if (error.message?.includes('attempts')) {
        message = 'Too many failed attempts. Please request a new code.'
      }

      setIsInvalidOtp(true)
      setErrorMessage(message)
      logger.info('Error state after caught error:', {
        isInvalidOtp: true,
        errorMessage: message,
      })

      setOtp('')
    } finally {
      setIsLoading(false)
    }
  }

  function resendCode() {
    if (!email || !hasEmailService || !isEmailVerificationEnabled) return

    setIsLoading(true)
    setErrorMessage('')

    const normalizedEmail = email.trim().toLowerCase()
    client.emailOtp
      .sendVerificationOtp({
        email: normalizedEmail,
        type: 'sign-in',
      })
      .then(() => {})
      .catch(() => {
        setErrorMessage('Failed to resend verification code. Please try again later.')
      })
      .finally(() => {
        setIsLoading(false)
      })
  }

  function handleOtpChange(value: string) {
    if (value.length === 6) {
      setIsInvalidOtp(false)
      setErrorMessage('')
    }
    setOtp(value)
  }

  useEffect(() => {
    if (otp.length === 6 && email && !isLoading && !isVerified) {
      const timeoutId = setTimeout(() => {
        verifyCode()
      }, 300)

      return () => clearTimeout(timeoutId)
    }
  }, [otp, email, isLoading, isVerified])

  useEffect(() => {
    if (typeof window !== 'undefined') {
      if (!isEmailVerificationEnabled) {
        setIsVerified(true)

        const handleRedirect = async () => {
          try {
            await refetchSession()
          } catch (error) {
            logger.warn('Failed to refetch session during verification skip:', error)
          }

          if (isInviteFlow && redirectUrl) {
            window.location.href = redirectUrl
          } else {
            router.push('/chat')
          }
        }

        handleRedirect()
      }
    }
  }, [isEmailVerificationEnabled, router, isInviteFlow, redirectUrl])

  return {
    otp,
    email,
    isLoading,
    isVerified,
    isInvalidOtp,
    errorMessage,
    isOtpComplete,
    hasEmailService,
    isProduction,
    isEmailVerificationEnabled,
    verifyCode,
    resendCode,
    handleOtpChange,
  }
}
