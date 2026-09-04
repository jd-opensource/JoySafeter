'use client'

import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

export type QuickstartFlowMode = 'fast' | 'expert'

export function QuickstartModeToggle({
  mode,
  onChange,
}: {
  mode: QuickstartFlowMode
  onChange: (mode: QuickstartFlowMode) => void
}) {
  const { t } = useTranslation()

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-muted-foreground">{t('managed.quickstart.mode.label')}</span>
      <div
        className="inline-flex rounded-lg border border-border bg-muted p-0.5"
        role="group"
        aria-label={t('managed.quickstart.mode.label')}
      >
        {(['fast', 'expert'] as const).map((optionMode) => (
          <button
            key={optionMode}
            type="button"
            onClick={() => onChange(optionMode)}
            aria-pressed={mode === optionMode}
            title={t(`managed.quickstart.mode.${optionMode}Hint`)}
            className={cn(
              'rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
              mode === optionMode
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {t(`managed.quickstart.mode.${optionMode}`)}
          </button>
        ))}
      </div>
    </div>
  )
}
