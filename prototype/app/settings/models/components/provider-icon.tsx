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
      <div className={cn('relative w-8 h-8 flex items-center justify-center bg-gray-50 rounded-lg overflow-hidden border border-gray-100 shadow-sm', className)}>
        <img
          alt={t('settings.providerIconAlt', { provider: provider.display_name, defaultValue: `${provider.display_name} icon` })}
          src={provider.icon}
          className="w-5 h-5 object-contain"
          onError={(e) => {
            e.currentTarget.style.display = 'none'
          }}
        />
      </div>
    )
  }

  // Fallback icon based on display name
  const firstLetter = provider.display_name?.charAt(0).toUpperCase() || '?'
  const bgColors = [
    'bg-blue-100 text-blue-600 border-blue-200',
    'bg-indigo-100 text-indigo-600 border-indigo-200',
    'bg-violet-100 text-violet-600 border-violet-200',
    'bg-purple-100 text-purple-600 border-purple-200',
    'bg-fuchsia-100 text-fuchsia-600 border-fuchsia-200',
  ]
  const colorIndex = (provider.display_name?.length || 0) % bgColors.length
  const colorClass = isCustom ? 'bg-violet-100 text-violet-600 border-violet-200' : bgColors[colorIndex]

  return (
    <div className={cn('relative w-8 h-8 flex items-center justify-center rounded-lg border shadow-sm font-bold text-sm', colorClass, className)}>
      {firstLetter}
    </div>
  )
}
