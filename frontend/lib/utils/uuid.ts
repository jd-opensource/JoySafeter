/**
 * Generate a UUID v4 string.
 * Uses crypto.randomUUID() when available, falls back to crypto.getRandomValues(),
 * and finally Math.random() as a last resort for environments without crypto support.
 */
export function generateUUID(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID() // eslint-disable-line no-restricted-syntax -- this IS the fallback wrapper
  }
  // Fallback: crypto.getRandomValues (works in Edge Runtime, browsers, Node)
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    const bytes = new Uint8Array(16)
    crypto.getRandomValues(bytes)
    bytes[6] = (bytes[6] & 0x0f) | 0x40 // version 4
    bytes[8] = (bytes[8] & 0x3f) | 0x80 // variant 10
    const hex = [...bytes].map(b => b.toString(16).padStart(2, '0')).join('')
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
  }
  // Last resort: Math.random (not cryptographically secure)
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    const v = c === 'x' ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}

/**
 * Generate a base64-encoded random nonce for CSP headers.
 * Uses crypto.getRandomValues() directly — no UUID formatting overhead.
 */
export function generateNonce(size = 16): string {
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    const bytes = new Uint8Array(size)
    crypto.getRandomValues(bytes)
    if (typeof Buffer !== 'undefined') {
      return Buffer.from(bytes).toString('base64')
    }
    return btoa(String.fromCharCode(...bytes))
  }
  return Array.from({ length: size }, () => Math.floor(Math.random() * 256).toString(16).padStart(2, '0')).join('')
}
