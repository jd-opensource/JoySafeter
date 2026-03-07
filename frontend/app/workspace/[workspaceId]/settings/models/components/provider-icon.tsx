'use client'

import React from 'react'

import type { ModelProvider } from '@/hooks/queries/models'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/core/utils/cn'

interface ProviderIconProps {
  provider: ModelProvider
  className?: string
}

export function ProviderIcon({ provider, className = '' }: ProviderIconProps) {
  const { t } = useTranslation()
  const isCustom = provider.provider_name === 'custom'

  if (provider.icon) {
    return (
      <img
        alt={t('settings.providerIconAlt', { provider: provider.display_name, defaultValue: `${provider.display_name} icon` })}
        src={provider.icon}
        className={`w-auto h-6 ${className}`}
        onError={(e) => {
          e.currentTarget.style.display = 'none'
        }}
      />
    )
  }

  return (
    <div className={cn('inline-flex items-center', className)}>
      <div
        className={cn(
          'text-sm font-semibold',
          isCustom ? 'text-violet-700' : 'text-gray-900'
        )}
      >
        {provider.display_name}
      </div>
    </div>
  )
}
