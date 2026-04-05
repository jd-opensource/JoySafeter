'use client'

import { useQuery } from '@tanstack/react-query'
import { Chrome, Github, Globe, Key, Shield } from 'lucide-react'


import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { API_BASE } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { createLogger } from '@/lib/logs/console/logger'

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
}

/**
 * Fetch the list of OAuth providers
 */
async function fetchOAuthProviders(): Promise<OAuthProvider[]> {
  const response = await fetch(`${API_BASE}/auth/oauth/providers`, {
    credentials: 'include',
  })

  if (!response.ok) {
    throw new Error('Failed to fetch OAuth providers')
  }

  const data: OAuthProvidersResponse = await response.json()
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
export function OAuthButtons({ callbackUrl = '/chat', showDivider = true }: OAuthButtonsProps) {
  const { t } = useTranslation()

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

  const handleOAuthLogin = (providerId: string) => {
    const params = new URLSearchParams()
    if (callbackUrl) {
      params.set('callback_url', callbackUrl)
    }
    const queryString = params.toString()
    const url = `${API_BASE}/auth/oauth/${providerId}${queryString ? `?${queryString}` : ''}`

    logger.info('Initiating OAuth login:', { provider: providerId, callbackUrl })
    // eslint-disable-next-line react-hooks/immutability
    window.location.href = url
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
              onClick={() => handleOAuthLogin(provider.id)}
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
