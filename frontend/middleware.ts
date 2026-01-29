import type { NextRequest } from 'next/server'
import { NextResponse } from 'next/server'

import { createLogger } from '@/lib/logs/console/logger'

const logger = createLogger('Middleware')

// Necessary third-party domains (for CSP)
const NECESSARY_DOMAIN = '*.jd.com http://localhost:* http://127.0.0.1:*'

// Paths allowed to be embedded in iframe (whitelist)
const EMBEDDABLE_PATHS = ['']

// Allowed redirect paths (prevent open redirect attacks)
const ALLOWED_REDIRECT_PATHS = [
  '/chat',
  '/workspace',
  '/dashboard',
  '/dynamic',
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
function wrapResponseWithXFrameOptions(
  response: NextResponse,
  pathname: string
): NextResponse {
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
  nonce?: string
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
    'geolocation=(), microphone=(), camera=(), payment=(), usb=(), magnetometer=(), gyroscope=(), accelerometer=()'
  )

  // 5. Strict-Transport-Security (HSTS): Force HTTPS (only in production and when using HTTPS)
  if (isProduction && isHttps) {
    response.headers.set(
      'Strict-Transport-Security',
      'max-age=31536000; includeSubDomains; preload'
    )
  }

  // 6. If nonce is provided, add to response headers (for CSP)
  if (nonce) {
    response.headers.set('x-nonce', nonce)
  }

  return response
}

/**
 * 从 NEXT_PUBLIC_API_URL 环境变量提取后端 API 域名
 * 用于 CSP connect-src 指令
 */
function getBackendApiDomains(): string {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL
  if (!apiUrl) return ''

  try {
    const url = new URL(apiUrl)
    const host = url.host

    // Return both HTTP and HTTPS protocols (CSP needs explicit protocol specification)
    // Also support ws:// and wss:// WebSocket connections
    if (url.protocol === 'https:') {
      return `https://${host} wss://${host}`
    } else {
      return `http://${host} https://${host} ws://${host} wss://${host}`
    }
  } catch {
    // URL parsing failed, return original value directly
    return apiUrl
  }
}

/**
 * 生成 Content Security Policy 头
 * 增强版：移除 unsafe-inline，限制 img-src，添加更严格的控制
 */
function generateCSPHeader(
  whiteList: string,
  nonce: string,
  isProduction: boolean
): string {
  const csp = `'nonce-${nonce}'`
  // Remove filesystem: because it's not a standard secure scheme
  const schemeSource = 'data: mediastream: blob:'

  // Next.js and third-party library inline script hashes
  // PublicEnvScript (next-runtime-env) inline script hash
  const inlineScriptHashes = [
    "'sha256-z0nb1PpkFco8UDVc/Xq/SKYGByn8TQYxeliFAv309DM='",
  ]

  // Get backend API domain from environment variables (for connect-src)
  const backendApiDomains = getBackendApiDomains()

  // Enhanced strict CSP policy
  // Only enable upgrade-insecure-requests in production and when HTTPS is explicitly enabled
  const upgradeInsecureRequests = isProduction && process.env.NEXT_PUBLIC_FORCE_HTTPS === 'true' ? 'upgrade-insecure-requests;' : ''

  let cspHeader = `
    default-src 'self' ${csp} ${whiteList};
    connect-src 'self' ${schemeSource} ${backendApiDomains} ${whiteList} http://*.jd.com https://*.jd.com;
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
    frame-src 'none';
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
 * Next.js 中间件
 * 处理安全头、CSP、X-Frame-Options 等
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
    // Generate nonce (for CSP)
    const nonce = Buffer.from(crypto.randomUUID()).toString('base64')

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
 * 中间件配置
 * 定义哪些路径需要经过中间件处理
 */
export const config = {
  matcher: [
    /*
     * 匹配所有请求路径，除了：
     * - _next/static (静态文件)
     * - _next/image (图片优化文件)
     * - favicon.ico (网站图标)
     * - 静态资源文件 (.png, .jpg, .jpeg, .gif, .svg, .ico, .webp, .woff, .woff2, .ttf, .eot)
     */
    {
      source: '/((?!_next/static|_next/image|favicon.ico|.*\\.(?:png|jpg|jpeg|gif|svg|ico|webp|woff|woff2|ttf|eot)).*)',
    },
  ],
}
