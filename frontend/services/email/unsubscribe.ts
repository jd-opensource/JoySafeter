import { apiGet, apiPost } from '@/lib/api-client'
import { createLogger } from '@/lib/logs/console/logger'

const logger = createLogger('Unsubscribe')

// API endpoint
const EMAIL_API_BASE = '/api/v1/email'

export interface EmailPreferences {
  unsubscribeAll?: boolean
  unsubscribeMarketing?: boolean
  unsubscribeUpdates?: boolean
  unsubscribeNotifications?: boolean
}

/**
 * Generate a secure unsubscribe token for an email address
 *
 * Generate unsubscribe token via backend API
 */
export async function generateUnsubscribeToken(
  email: string,
  emailType = 'marketing',
): Promise<string> {
  try {
    const result = await apiPost<{ token: string }>(`${EMAIL_API_BASE}/generate-token`, {
      email,
      email_type: emailType,
    })
    return result.token
  } catch (error) {
    logger.error('Error generating unsubscribe token:', error)
    // If API call fails, throw error (should not happen, but for compatibility)
    throw error
  }
}

/**
 * Check if user has unsubscribed from a specific email type
 *
 * Check if user has unsubscribed via backend API
 */
export async function isUnsubscribed(
  email: string,
  emailType: 'all' | 'marketing' | 'updates' | 'notifications' = 'all',
): Promise<boolean> {
  try {
    const result = await apiGet<{ is_unsubscribed: boolean }>(
      `${EMAIL_API_BASE}/check-unsubscribed?email=${encodeURIComponent(email)}&email_type=${emailType}`,
    )
    return result?.is_unsubscribed || false
  } catch (error) {
    logger.error('Error checking unsubscribe status:', error)
    return false
  }
}
