'use client'

import { Lightbulb } from 'lucide-react'

import { useTranslation } from '@/lib/i18n'
import { formatCompactNumber, formatPercent } from '@/lib/managed/analytics/formatters'
import { suggestionMessageKey } from '@/lib/managed/analytics/health-presenter'
import type { TokenSummary, EngineShareItem, SuggestionItem } from '@/lib/managed/analytics/types'

import { CHART_COLORS, ENGINE_COLOR_MAP, ENGINE_LABELS } from './constants'

interface TokenSummaryCardProps {
  tokenSummary: TokenSummary | undefined
  engineShare: EngineShareItem[]
  suggestions?: SuggestionItem[]
  loading?: boolean
}

export function TokenSummaryCard({
  tokenSummary,
  engineShare,
  suggestions,
  loading,
}: TokenSummaryCardProps) {
  const { t } = useTranslation()

  if (loading || !tokenSummary) {
    return (
      <div className="space-y-4 rounded-lg border border-border bg-card p-4">
        <div className="h-4 w-24 animate-pulse rounded bg-muted" />
        <div className="h-8 w-20 animate-pulse rounded bg-muted" />
        <div className="h-3 w-full animate-pulse rounded bg-muted" />
        <div className="h-3 w-3/4 animate-pulse rounded bg-muted" />
      </div>
    )
  }

  const cacheHitPct = tokenSummary.cache_hit_rate * 100

  return (
    <div className="space-y-4 rounded-lg border border-border bg-card p-4">
      {/* Token totals */}
      <div>
        <h3 className="mb-3 text-sm font-medium text-foreground">
          {t('analytics.tokenSummary.title')}
        </h3>
        <p className="text-xl font-semibold text-foreground">
          {formatCompactNumber(tokenSummary.total)}
        </p>
        <div className="mt-2 flex items-center gap-4 text-xs text-muted-foreground">
          <span>
            {t('analytics.tokenSummary.input')}:{' '}
            <strong className="text-foreground">{formatCompactNumber(tokenSummary.input)}</strong>
          </span>
          <span>
            {t('analytics.tokenSummary.output')}:{' '}
            <strong className="text-foreground">{formatCompactNumber(tokenSummary.output)}</strong>
          </span>
        </div>
      </div>

      {/* Cache hit rate */}
      <div>
        <div className="mb-1.5 flex items-center justify-between text-xs">
          <span className="text-muted-foreground">{t('analytics.tokenSummary.cacheHitRate')}</span>
          <span className="font-medium text-foreground">
            {formatPercent(tokenSummary.cache_hit_rate)}
          </span>
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-muted/30">
          <div
            className="h-full rounded-full bg-emerald-500 transition-all dark:bg-emerald-400"
            style={{ width: `${Math.min(cacheHitPct, 100)}%` }}
          />
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          {t('analytics.tokenSummary.cacheRead')}: {formatCompactNumber(tokenSummary.cache_read)}
        </p>
      </div>

      {/* Mini engine distribution */}
      {engineShare.length > 0 && (
        <div>
          <h4 className="mb-2 text-xs font-medium text-muted-foreground">
            {t('analytics.tokenSummary.engineDistribution')}
          </h4>

          {/* Mini stacked bar */}
          <div className="flex h-2 gap-px overflow-hidden rounded-full">
            {engineShare.map((item) => {
              const colorIdx = ENGINE_COLOR_MAP[item.engine as keyof typeof ENGINE_COLOR_MAP] ?? 7
              return (
                <div
                  key={item.engine}
                  className="h-full first:rounded-l-full last:rounded-r-full"
                  style={{
                    width: `${item.percentage}%`,
                    backgroundColor: CHART_COLORS[colorIdx],
                    minWidth: '3px',
                  }}
                />
              )
            })}
          </div>

          {/* Legend */}
          <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
            {engineShare.map((item) => {
              const colorIdx = ENGINE_COLOR_MAP[item.engine as keyof typeof ENGINE_COLOR_MAP] ?? 7
              const label = ENGINE_LABELS[item.engine as keyof typeof ENGINE_LABELS] ?? item.engine
              return (
                <div
                  key={item.engine}
                  className="flex items-center gap-1 text-xs text-muted-foreground"
                >
                  <div
                    className="h-2 w-2 shrink-0 rounded-full"
                    style={{ backgroundColor: CHART_COLORS[colorIdx] }}
                  />
                  <span>
                    {label} {item.percentage}%
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Optimization suggestions */}
      {suggestions && suggestions.length > 0 && (
        <div className="border-t border-border pt-3">
          <h4 className="mb-2 text-xs font-medium text-muted-foreground">
            {t('analytics.tokenSummary.suggestions')}
          </h4>
          <div className="space-y-1.5">
            {suggestions.map((s, i) => (
              <div key={i} className="flex items-start gap-2 text-xs">
                <Lightbulb className="mt-0.5 h-3 w-3 shrink-0 text-amber-500" />
                <span className="text-muted-foreground">
                  {t(suggestionMessageKey(s.type), s.params)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
