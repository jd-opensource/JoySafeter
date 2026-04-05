import type { NextRequest } from 'next/server'
import { NextResponse } from 'next/server'

import { createLogger } from '@/lib/logs/console/logger'
import { generateNonce } from '@/lib/utils/uuid'

const logger = createLogger('Middleware')

// Necessary third-party domains (for CSP)
const NECESSARY_DOMAIN = process.env.NEXT_PUBLIC_CSP_NECESSARY_DOMAIN || 'http://localhost:* http://127.0.0.1:*'

// Paths allowed to be embedded in iframe (whitelist)
const EMBEDDABLE_PATHS = ['']

// Allowed redirect paths (prevent open redirect attacks)
const ALLOWED_REDIRECT_PATHS = [
  '/chat',
  '/workspace',
  '/dashboard',
  '/signin',
  '/signup',
  '/verify',
  '/reset-password',
]

/**
 * Validate if callback URL is safe
 * Prevent open redirect attacks
 */
function validateCallbackUrl(url: string | null): boolean {
  if (!url) return true // Empty URL is considered valid (use default value)

  try {
    // Only allow relative paths
    if (!url.startsWith('/')) {
      logger.warn('Invalid callback URL: not a relative path', { url })
      return false
    }

    // Prevent path traversal attacks
    if (url.includes('..') || url.includes('//')) {
      logger.warn('Invalid callback URL: path traversal detected', { url })
      return false
    }

    // Prevent dangerous protocols
    if (url.match(/^(javascript|data|vbscript|file):/i)) {
      logger.warn('Invalid callback URL: dangerous protocol detected', { url })
      return false
    }

    // Check if in whitelist
    const isAllowed = ALLOWED_REDIRECT_PATHS.some((path) => url.startsWith(path))
    if (!isAllowed) {
      logger.warn('Invalid callback URL: not in whitelist', { url })
      return false
    }

    return true
  } catch (error) {
    logger.error('Error validating callback URL', { error, url })
    return false
  }
}

/**
 * Wrap response and add X-Frame-Options header
 * Prevent clickjacking attacks
 */
function wrapResponseWithXFrameOptions(response: NextResponse, pathname: string): NextResponse {
  // Some pages allow iframe embedding (feature requirement)
  const isEmbeddable = EMBEDDABLE_PATHS.some((path) => pathname.startsWith(path))
  const allowEmbed = process.env.NEXT_PUBLIC_ALLOW_EMBED === 'true'

  if (!allowEmbed && !isEmbeddable) {
    response.headers.set('X-Frame-Options', 'DENY')
  } else if (allowEmbed || isEmbeddable) {
    // When allowing embed, use SAMEORIGIN instead of fully allowing
    response.headers.set('X-Frame-Options', 'SAMEORIGIN')
  }

  return response
}

/**
 * Add all security headers
 */
function addSecurityHeaders(
  response: NextResponse,
  request: NextRequest,
  nonce?: string,
): NextResponse {
  const isProduction = process.env.NODE_ENV === 'production'
  const isHttps = request.nextUrl.protocol === 'https:'

  // 1. X-Content-Type-Options: Prevent MIME type sniffing
  response.headers.set('X-Content-Type-Options', 'nosniff')

  // 2. X-XSS-Protection: Enable browser XSS filter (though obsolete, still has compatibility value)
  response.headers.set('X-XSS-Protection', '1; mode=block')

  // 3. Referrer-Policy: Control referrer information
  response.headers.set('Referrer-Policy', 'strict-origin-when-cross-origin')

  // 4. Permissions-Policy: Control browser features
  response.headers.set(
    'Permissions-Policy',
    'geolocation=(), microphone=(), camera=(), payment=(), usb=(), magnetometer=(), gyroscope=(), accelerometer=()',
  )

  // 5. Strict-Transport-Security (HSTS): Force HTTPS (only in production and when using HTTPS)
  if (isProduction && isHttps) {
    response.headers.set(
      'Strict-Transport-Security',
      'max-age=31536000; includeSubDomains; preload',
    )
  }

  // 6. If nonce is provided, add to response headers (for CSP)
  if (nonce) {
    response.headers.set('x-nonce', nonce)
  }

  return response
}

/**
 * Extract backend API domain from NEXT_PUBLIC_API_URL env var.
 * Used for CSP connect-src / frame-src directives.
 *
 * Auto-generated rules:
 * 1. Exact match for the backend API URL (with port) across http/https/ws/wss variants
 * 2. Wildcard port on the same hostname, covering MCP and related services
 *
 * To add domains on a different host, use NEXT_PUBLIC_CSP_CONNECT_SRC_EXTRA / NEXT_PUBLIC_CSP_FRAME_SRC_EXTRA
 */
function getBackendApiDomains(): string {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL
  if (!apiUrl) return ''

  try {
    const url = new URL(apiUrl)
    const hostname = url.hostname // without port
    const host = url.host // with port

    // exact match + wildcard port, covering http/https/ws/wss protocols
    if (url.protocol === 'https:') {
      return `https://${host} wss://${host} https://${hostname}:* wss://${hostname}:*`
    } else {
      return `http://${host} https://${host} ws://${host} wss://${host} http://${hostname}:* https://${hostname}:* ws://${hostname}:* wss://${hostname}:*`
    }
  } catch {
    // URL parsing failed, return original value directly
    return apiUrl
  }
}

/**
 * Generate Content Security Policy header.
 * Strict mode: removes unsafe-inline, restricts img-src, adds tighter controls.
 */
function generateCSPHeader(whiteList: string, nonce: string, isProduction: boolean): string {
  const csp = `'nonce-${nonce}'`
  // Remove filesystem: because it's not a standard secure scheme
  const schemeSource = 'data: mediastream: blob:'

  // Next.js and third-party library inline script hashes
  // PublicEnvScript (next-runtime-env) inline script hash
  const inlineScriptHashes = [
    "'sha256-z0nb1PpkFco8UDVc/Xq/SKYGByn8TQYxeliFAv309DM='",
    "'sha256-hweB5ft6P5GckAdddQeQ/oIE/5wsGJGlNDKQmAvF9CU='",
  ]

  // derive backend domains from NEXT_PUBLIC_API_URL (wildcard port covers MCP etc.)
  const backendApiDomains = getBackendApiDomains()

  // extra connect-src domains (for external services on non-backend hosts)
  const connectSrcExtra = process.env.NEXT_PUBLIC_CSP_CONNECT_SRC_EXTRA || ''

  // extra frame-src domains (for external iframe embeds on non-backend hosts)
  const frameSrcExtra = process.env.NEXT_PUBLIC_CSP_FRAME_SRC_EXTRA || ''

  // Enhanced strict CSP policy
  // Only enable upgrade-insecure-requests in production and when HTTPS is explicitly enabled
  const upgradeInsecureRequests =
    isProduction && process.env.NEXT_PUBLIC_FORCE_HTTPS === 'true'
      ? 'upgrade-insecure-requests;'
      : ''

  let cspHeader = `
    default-src 'self' ${csp} ${whiteList};
    connect-src 'self' ${schemeSource} ${backendApiDomains} ${whiteList} ${connectSrcExtra};
    script-src 'self' ${csp} ${inlineScriptHashes.join(' ')} ${whiteList} 'strict-dynamic';
    style-src 'self' 'unsafe-inline' ${whiteList};
    style-src-attr 'unsafe-inline';
    worker-src 'self' blob:;
    media-src 'self' ${schemeSource} ${whiteList};
    img-src 'self' data: blob: https://*.githubusercontent.com https://*.gravatar.com;
    font-src 'self' data: blob:;
    object-src 'none';
    base-uri 'self';
    form-action 'self';
    frame-ancestors 'self';
    frame-src 'self' ${backendApiDomains} ${whiteList} ${frameSrcExtra};
    ${upgradeInsecureRequests}
  `

  // Add CSP violation reports in production
  if (isProduction && process.env.NEXT_PUBLIC_CSP_REPORT_URI) {
    cspHeader += `
      report-uri ${process.env.NEXT_PUBLIC_CSP_REPORT_URI};
      report-to csp-endpoint;
    `
  }

  // Clean up extra spaces and newlines
  return cspHeader.replace(/\s{2,}/g, ' ').trim()
}

/**
 * Next.js middleware.
 * Handles security headers, CSP, X-Frame-Options, etc.
 */
export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl
  const requestHeaders = new Headers(request.headers)

  // Validate and clean callback URL (prevent open redirect attacks)
  const url = request.nextUrl.clone()
  const callbackUrl = url.searchParams.get('callbackUrl')

  if (callbackUrl && !validateCallbackUrl(callbackUrl)) {
    // Remove insecure callback URL and redirect
    url.searchParams.delete('callbackUrl')
    logger.warn('Removed unsafe callback URL', { callbackUrl, pathname })
    const redirectResponse = NextResponse.redirect(url)
    return addSecurityHeaders(redirectResponse, request)
  }

  // Create response
  const response = NextResponse.next({
    request: {
      headers: requestHeaders,
    },
  })

  // Check if CSP is enabled (always enabled in production, controlled by env var in development)
  const isProduction = process.env.NODE_ENV === 'production'
  const enableCSP = isProduction || process.env.NEXT_PUBLIC_ENABLE_CSP_IN_DEV === 'true'
  const isWhiteListEnabled = !!process.env.NEXT_PUBLIC_CSP_WHITELIST

  if (enableCSP) {
    const nonce = generateNonce()

    // Build CSP whitelist (use configured whitelist in production, lenient config in development)
    let whiteList = ''

    if (isProduction && isWhiteListEnabled) {
      whiteList = `${process.env.NEXT_PUBLIC_CSP_WHITELIST} ${NECESSARY_DOMAIN}`
    } else if (!isProduction) {
      // Development environment: allow local development servers
      whiteList = `${NECESSARY_DOMAIN} ws://localhost:* ws://127.0.0.1:*`
    }

    // Generate CSP header
    const cspHeader = generateCSPHeader(whiteList, nonce, isProduction)

    // Set CSP header
    requestHeaders.set('Content-Security-Policy', cspHeader)
    response.headers.set('Content-Security-Policy', cspHeader)
    requestHeaders.set('x-nonce', nonce)

    // Add all security headers
    addSecurityHeaders(response, request, nonce)
  } else {
    // If CSP is not enabled, still add basic security headers
    addSecurityHeaders(response, request)

    // Log warning in development environment
    if (isProduction) {
      logger.warn('CSP is disabled in production environment!')
    }
  }

  // Add X-Frame-Options
  return wrapResponseWithXFrameOptions(response, pathname)
}

/**
 * Middleware configuration.
 * Define which paths should be processed by the middleware.
 */
export const config = {
  matcher: [
    /*
     * Match all request paths except:
     * - _next/static (static files)
     * - _next/image (image optimization)
     * - favicon.ico (site icon)
     * - static assets (.png, .jpg, .jpeg, .gif, .svg, .ico, .webp, .woff, .woff2, .ttf, .eot)
     */
    {
      source:
        '/((?!_next/static|_next/image|favicon.ico|.*\\.(?:png|jpg|jpeg|gif|svg|ico|webp|woff|woff2|ttf|eot)).*)',
    },
  ],
}
