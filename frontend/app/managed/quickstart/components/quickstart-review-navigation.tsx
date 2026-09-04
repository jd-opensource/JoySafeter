'use client'

import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

import type { QuickstartFlowMode } from './quickstart-mode-toggle'

export type QuickstartReviewTab = 'blueprint' | 'advanced' | 'preview'

const TABS_BY_MODE: Readonly<Record<QuickstartFlowMode, readonly QuickstartReviewTab[]>> = {
  fast: ['blueprint', 'preview'],
  expert: ['blueprint', 'advanced', 'preview'],
}

export function QuickstartReviewNavigation({
  mode,
  activeTab,
  onChange,
}: {
  mode: QuickstartFlowMode
  activeTab: QuickstartReviewTab
  onChange: (tab: QuickstartReviewTab) => void
}) {
  const { t } = useTranslation()

  return (
    <div className="border-b border-border px-4 pt-2.5">
      <div className="flex items-end gap-5">
        {TABS_BY_MODE[mode].map((tab) => (
          <button
            key={tab}
            type="button"
            className={cn(
              'pb-2 text-sm font-semibold transition-colors',
              activeTab === tab
                ? 'border-b-2 border-foreground text-foreground'
                : 'text-muted-foreground hover:text-foreground',
            )}
            onClick={() => onChange(tab)}
          >
            {tab === 'blueprint'
              ? t('managed.quickstart.blueprint.title')
              : tab === 'advanced'
                ? t('managed.quickstart.blueprint.advanced')
                : t('managed.quickstart.preview')}
          </button>
        ))}
      </div>
    </div>
  )
}
