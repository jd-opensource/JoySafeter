/**
 * URL validation utilities for frontend forms.
 *
 * Ensures URLs use http:// or https:// scheme before submitting to the backend.
 * This is a user-experience guard — the backend has its own SSRF protection.
 */

/**
 * Validate that a URL uses http:// or https:// scheme.
 * Returns an error message string if invalid, or null if valid.
 */
export function validateUrlScheme(url: string | undefined | null): string | null {
  if (!url || url.trim() === '') return null // empty is OK (optional fields)

  const trimmed = url.trim()

  try {
    const parsed = new URL(trimmed)
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      return `URL must use http:// or https:// (got ${parsed.protocol})`
    }
    return null
  } catch {
    // Not a valid URL at all
    if (!trimmed.startsWith('http://') && !trimmed.startsWith('https://')) {
      return 'URL must start with http:// or https://'
    }
    return 'Invalid URL format'
  }
}

/**
 * Check if a URL string is a valid http/https URL.
 */
export function isValidUrl(url: string | undefined | null): boolean {
  return validateUrlScheme(url) === null
}
