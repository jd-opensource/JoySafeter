import { getEnv } from '@/lib/core/config/env'
import { isProd } from '@/lib/core/config/environment'

/**
 * Returns the base URL of the application from NEXT_PUBLIC_APP_URL
 * This ensures webhooks, callbacks, and other integrations always use the correct public URL
 * @returns The base URL string (e.g., 'http://localhost:3000' or 'https://example.com')
 * Falls back to localhost:3000 in development if not configured
 */
export function getBaseUrl(): string {
  const baseUrl = getEnv('NEXT_PUBLIC_APP_URL')

  if (!baseUrl) {
    if (typeof window !== 'undefined') {
      return window.location.origin
    }
    return isProd ? 'https://localhost:3000' : 'http://localhost:3000'
  }

  if (baseUrl.startsWith('http://') || baseUrl.startsWith('https://')) {
    return baseUrl
  }

  const protocol = isProd ? 'https://' : 'http://'
  return `${protocol}${baseUrl}`
}

/**
 * Returns just the domain and port part of the application URL
 * @returns The domain with port if applicable (e.g., 'localhost:3000' or 'jd.ai')
 */
export function getBaseDomain(): string {
  try {
    const url = new URL(getBaseUrl())
    return url.host
  } catch (_e) {
    const fallbackUrl = getEnv('NEXT_PUBLIC_APP_URL') || 'http://localhost:8000'
    try {
      return new URL(fallbackUrl).host
    } catch {
      return isProd ? 'jd.ai' : 'localhost:3000'
    }
  }
}

/**
 * Returns the domain for email addresses, stripping www subdomain for Resend compatibility
 * @returns The email domain
 */
export function getEmailDomain(): string {
  try {
    const baseDomain = getBaseDomain()
    return baseDomain.startsWith('www.') ? baseDomain.substring(4) : baseDomain
  } catch (_e) {
    return isProd ? 'jd.ai' : 'localhost:3000'
  }
}
