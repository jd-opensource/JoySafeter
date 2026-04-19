import { EmailClient } from '@azure/communication-email'
import { Resend } from 'resend'

import { env } from '@/lib/core/config/env'

const resendApiKey = env.RESEND_API_KEY
const azureConnectionString = env.AZURE_ACS_CONNECTION_STRING

const resend =
  resendApiKey && resendApiKey !== 'placeholder' && resendApiKey.trim() !== ''
    ? new Resend(resendApiKey)
    : null

const azureEmailClient =
  azureConnectionString && azureConnectionString.trim() !== ''
    ? new EmailClient(azureConnectionString)
    : null

export function hasEmailService(): boolean {
  return !!(resend || azureEmailClient)
}
