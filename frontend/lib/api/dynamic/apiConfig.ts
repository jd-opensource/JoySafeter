/**
 * API base URL helpers
 * Updated for Next.js: removed /dynamic prefix, uses NEXT_PUBLIC_API_URL
 */
import { env as runtimeEnv } from 'next-runtime-env'

export function getApiBaseUrl(fallback: string = '/dynamic'): string {
  const base = runtimeEnv('NEXT_PUBLIC_API_URL') || process.env.NEXT_PUBLIC_API_URL

  if (!base || base === '/') {
    return '/dynamic';
  }

  const normalized = base.endsWith('/') ? base.slice(0, -1) : base;

  return normalized.endsWith('/dynamic') ? normalized : `${normalized}/dynamic`;
}
