import { apiGet, apiPost, apiPut } from '@/lib/api-client'
import { createLogger } from '@/lib/logs/console/logger'

import type { EmailType } from './mailer'

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
  emailType = 'marketing'
): Promise<string> {
  try {
    const result = await apiPost<{ token: string }>(
      `${EMAIL_API_BASE}/generate-token`,
      { email, email_type: emailType }
    )
    return result.token
  } catch (error) {
    logger.error('Error generating unsubscribe token:', error)
    // If API call fails, throw error (should not happen, but for compatibility)
    throw error
  }
}

/**
 * Verify an unsubscribe token for an email address and return email type
 *
 * Verify token via backend API
 */
export async function verifyUnsubscribeToken(
  email: string,
  token: string
): Promise<{ valid: boolean; emailType?: string }> {
  try {
    const result = await apiPost<{ valid: boolean; email_type?: string }>(
      `${EMAIL_API_BASE}/verify-token`,
      { email, token }
    )
    return {
      valid: result.valid,
      emailType: result.email_type,
    }
  } catch (error) {
    logger.error('Error verifying unsubscribe token:', error)
    return { valid: false }
  }
}

/**
 * Check if an email type is transactional
 */
export function isTransactionalEmail(emailType: EmailType): boolean {
  return emailType === ('transactional' as EmailType)
}

/**
 * Get user's email preferences
 *
 * Get email preferences via backend API
 */
export async function getEmailPreferences(email: string): Promise<EmailPreferences | null> {
  try {
    const result = await apiGet<EmailPreferences>(
      `${EMAIL_API_BASE}/preferences?email=${encodeURIComponent(email)}`
    )
    return result || null
  } catch (error) {
    logger.error('Error getting email preferences:', error)
    return null
  }
}

/**
 * Update user's email preferences
 *
 * Update email preferences via backend API
 */
export async function updateEmailPreferences(
  email: string,
  preferences: EmailPreferences
): Promise<boolean> {
  try {
    await apiPut(
      `${EMAIL_API_BASE}/preferences?email=${encodeURIComponent(email)}`,
      preferences
    )
    logger.info(`Updated email preferences for user: ${email}`)
    return true
  } catch (error) {
    logger.error('Error updating email preferences:', error)
    return false
  }
}

/**
 * Check if user has unsubscribed from a specific email type
 *
 * Check if user has unsubscribed via backend API
 */
export async function isUnsubscribed(
  email: string,
  emailType: 'all' | 'marketing' | 'updates' | 'notifications' = 'all'
): Promise<boolean> {
  try {
    const result = await apiGet<{ is_unsubscribed: boolean }>(
      `${EMAIL_API_BASE}/check-unsubscribed?email=${encodeURIComponent(email)}&email_type=${emailType}`
    )
    return result?.is_unsubscribed || false
  } catch (error) {
    logger.error('Error checking unsubscribe status:', error)
    return false
  }
}

/**
 * Unsubscribe user from all emails
 *
 * Unsubscribe from all emails via backend API
 */
export async function unsubscribeFromAll(email: string): Promise<boolean> {
  try {
    await apiPost(
      `${EMAIL_API_BASE}/unsubscribe/all?email=${encodeURIComponent(email)}`
    )
    return true
  } catch (error) {
    logger.error('Error unsubscribing from all emails:', error)
    return false
  }
}

/**
 * Unsubscribe user by token (from email link)
 *
 * Unsubscribe via token from email link
 */
export async function unsubscribeByToken(email: string, token: string): Promise<boolean> {
  try {
    await apiPost(
      `${EMAIL_API_BASE}/unsubscribe`,
      { email, token }
    )
    return true
  } catch (error) {
    logger.error('Error unsubscribing by token:', error)
    return false
  }
}

/**
 * Resubscribe user (remove all unsubscribe flags)
 *
 * Resubscribe to all emails via backend API
 */
export async function resubscribe(email: string): Promise<boolean> {
  try {
    await apiPost(
      `${EMAIL_API_BASE}/resubscribe?email=${encodeURIComponent(email)}`
    )
    return true
  } catch (error) {
    logger.error('Error resubscribing:', error)
    return false
  }
}
