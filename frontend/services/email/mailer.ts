import { env } from '@/lib/core/config/env'

export function hasEmailService(): boolean {
  const resendKey = env.RESEND_API_KEY
  const azureConn = env.AZURE_ACS_CONNECTION_STRING
  const hasResend = !!(resendKey && resendKey !== 'placeholder' && resendKey.trim())
  const hasAzure = !!(azureConn && azureConn.trim())
  return hasResend || hasAzure
}
