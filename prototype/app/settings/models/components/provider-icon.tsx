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
      <div className={cn('relative flex h-8 w-8 items-center justify-center overflow-hidden rounded-xl border border-[var(--divider)] bg-white/80 shadow-sm', className)}>
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
    'bg-[rgba(54,93,130,0.1)] text-[var(--status-running)] border-[rgba(54,93,130,0.16)]',
    'bg-[rgba(111,129,148,0.1)] text-[var(--brand-indigo)] border-[rgba(111,129,148,0.16)]',
    'bg-[rgba(36,56,77,0.1)] text-[var(--brand-500)] border-[rgba(36,56,77,0.16)]',
    'bg-[rgba(53,111,97,0.1)] text-[var(--status-healthy)] border-[rgba(53,111,97,0.16)]',
    'bg-[rgba(155,106,45,0.1)] text-[var(--warning)] border-[rgba(155,106,45,0.16)]',
  ]
  const colorIndex = (provider.display_name?.length || 0) % bgColors.length
  const colorClass = isCustom
    ? 'bg-[rgba(36,56,77,0.1)] text-[var(--brand-500)] border-[rgba(36,56,77,0.16)]'
    : bgColors[colorIndex]

  return (
    <div className={cn('relative flex h-8 w-8 items-center justify-center rounded-xl border text-sm font-bold shadow-sm', colorClass, className)}>
      {firstLetter}
    </div>
  )
}
