'use client'

import { useQuery } from '@tanstack/react-query'
import { Chrome, Github, Globe, Key, Shield } from 'lucide-react'
import { useEffect, useRef } from 'react'

import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { managedGet, ApiError } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { createLogger } from '@/lib/logs/console/logger'
import { toastError } from '@/lib/utils/toast'

const logger = createLogger('OAuthButtons')

// icon mapping
const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  github: Github,
  google: Chrome,
  microsoft: Globe,
  gitlab: Globe,
  key: Key,
  shield: Shield,
  building: Globe,
  lock: Key,
}

interface OAuthProvider {
  id: string
  display_name: string
  icon: string
}

interface OAuthProvidersResponse {
  providers: OAuthProvider[]
  login_mode: 'chooser' | 'redirect'
}

interface OAuthAuthorizationResponse {
  authorization_url: string
  state: string
}

/**
 * Fetch the list of OAuth providers
 */
async function fetchOAuthProviders(): Promise<OAuthProvider[]> {
  const data = await managedGet<OAuthProvidersResponse>('auth/oauth/providers', {
    withAuth: false,
    skipManagedContext: true,
  })
  return data.providers
}

interface OAuthButtonsProps {
  /**
   * Callback URL after successful login
   */
  callbackUrl?: string
  /**
   * Whether to show the divider
   */
  showDivider?: boolean
}

/**
 * OAuth/SSO login button component
 *
 * Dynamically fetches enabled OAuth providers from the backend and renders login buttons.
 */
export function OAuthButtons({
  callbackUrl = '/managed/quickstart',
  showDivider = true,
}: OAuthButtonsProps) {
  const { t } = useTranslation()
  const requestRunRef = useRef(0)
  const mountedRef = useRef(true)

  useEffect(
    () => () => {
      mountedRef.current = false
      requestRunRef.current += 1
    },
    [],
  )

  const {
    data: providers,
    isLoading,
    error,
  } = useQuery<OAuthProvider[]>({
    queryKey: ['oauth-providers'],
    queryFn: fetchOAuthProviders,
    staleTime: 5 * 60 * 1000, // 5-minute cache
    retry: 1,
  })

  // if no providers or loading error, render nothing
  if (error) {
    logger.warn('Failed to fetch OAuth providers:', error)
    return null
  }

  if (isLoading) {
    return (
      <div className="mt-6 space-y-4">
        <div className="relative">
          <div className="absolute inset-0 flex items-center">
            <span className="w-full border-t" />
          </div>
          <div className="relative flex justify-center text-xs uppercase">
            <span className="bg-background px-2 text-muted-foreground">
              {t('auth.orContinueWith')}
            </span>
          </div>
        </div>
        <div className="space-y-2">
          <Skeleton className="h-10 w-full" />
        </div>
      </div>
    )
  }

  // if no enabled providers, render nothing
  if (!providers?.length) {
    return null
  }

  const getOAuthErrorMessage = (error: unknown): string => {
    if (error instanceof ApiError) {
      switch (error.code) {
        case 'OAUTH_PROVIDER_NOT_FOUND':
          return t('auth.oauthProviderNotFound')
        case 'OAUTH_DISCOVERY_FAILED':
        case 'OAUTH_TOKEN_ENDPOINT_DISCOVERY_FAILED':
        case 'OAUTH_USERINFO_ENDPOINT_DISCOVERY_FAILED':
          return t('auth.oauthDiscoveryFailed')
        case 'OAUTH_AUTHORIZE_URL_MISSING':
          return t('auth.oauthAuthorizeUrlMissing')
        case 'NETWORK_ERROR':
        case 'REQUEST_TIMEOUT':
          return t('auth.networkError')
        default:
          return error.message || t('auth.oauthFailed')
      }
    }

    if (error instanceof Error) {
      return error.message
    }

    return t('auth.oauthFailed')
  }

  const handleOAuthLogin = async (providerId: string) => {
    const runId = requestRunRef.current + 1
    requestRunRef.current = runId
    const isCurrentRequest = () => mountedRef.current && requestRunRef.current === runId

    try {
      const params = new URLSearchParams()
      if (callbackUrl) {
        params.set('callback_url', callbackUrl)
      }
      const queryString = params.toString()
      const path = `auth/oauth/${providerId}${queryString ? `?${queryString}` : ''}`

      logger.info('Initiating OAuth login:', { provider: providerId, callbackUrl })
      const response = await managedGet<OAuthAuthorizationResponse>(path, {
        withAuth: false,
        skipManagedContext: true,
      })
      if (!isCurrentRequest()) return
      window.location.href = response.authorization_url
    } catch (error) {
      if (!isCurrentRequest()) return
      logger.error('Failed to initiate OAuth login:', { providerId, error })
      toastError(getOAuthErrorMessage(error))
    }
  }

  return (
    <div className="mt-6 space-y-4">
      {showDivider && (
        <div className="relative">
          <div className="absolute inset-0 flex items-center">
            <span className="w-full border-t" />
          </div>
          <div className="relative flex justify-center text-xs uppercase">
            <span className="bg-background px-2 text-muted-foreground">
              {t('auth.orContinueWith')}
            </span>
          </div>
        </div>
      )}

      <div className="grid gap-2">
        {providers.map((provider) => {
          const Icon = ICON_MAP[provider.icon] || ICON_MAP.globe || Globe
          return (
            <Button
              key={provider.id}
              variant="outline"
              className="w-full"
              onClick={() => void handleOAuthLogin(provider.id)}
            >
              <Icon className="mr-2 h-4 w-4" />
              {t('auth.signInWith', { provider: provider.display_name })}
            </Button>
          )
        })}
      </div>
    </div>
  )
}
