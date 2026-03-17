'use client'

import { Compass } from 'lucide-react'

import { useTranslation } from '@/lib/i18n'

export default function DiscoverPage() {
  const { t } = useTranslation()

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex-shrink-0 border-b border-[var(--border)] bg-[var(--surface-1)] px-6 py-4">
        <div className="flex items-center gap-3">
          <Compass className="h-6 w-6 text-[var(--text-primary)]" />
          <h1 className="text-2xl font-semibold text-[var(--text-primary)]">
            {t('sidebar.discover')}
          </h1>
        </div>
      </div>

      {/* Content */}
      <div className="flex flex-1 items-center justify-center p-8">
        <div className="text-center">
          <Compass className="mx-auto h-16 w-16 text-[var(--text-tertiary)] mb-4" />
          <h2 className="text-xl font-medium text-[var(--text-primary)] mb-2">
            {t('sidebar.discover')}
          </h2>
          <p className="text-[var(--text-secondary)] max-w-md">
            {t('sidebar.discoverComingSoon')}
          </p>
        </div>
      </div>
    </div>
  )
}
