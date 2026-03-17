import { VerifyContent } from '@/app/(auth)/verify/verify-content'
import { isEmailVerificationEnabled, isProd } from '@/lib/core/config/environment'
import { hasEmailService } from '@/services/email/mailer'

export const dynamic = 'force-dynamic'

export default function VerifyPage() {
  const emailServiceConfigured = hasEmailService()

  return (
    <VerifyContent
      hasEmailService={emailServiceConfigured}
      isProduction={isProd}
      isEmailVerificationEnabled={isEmailVerificationEnabled}
    />
  )
}
