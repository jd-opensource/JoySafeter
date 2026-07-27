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

export function TokenSummaryCard({ tokenSummary, engineShare, suggestions, loading }: TokenSummaryCardProps) {
  const { t } = useTranslation()

  if (loading || !tokenSummary) {
    return (
      <div className="rounded-lg border border-border bg-card p-4 space-y-4">
        <div className="h-4 w-24 animate-pulse rounded bg-muted" />
        <div className="h-8 w-20 animate-pulse rounded bg-muted" />
        <div className="h-3 w-full animate-pulse rounded bg-muted" />
        <div className="h-3 w-3/4 animate-pulse rounded bg-muted" />
      </div>
    )
  }

  const cacheHitPct = tokenSummary.cache_hit_rate * 100

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-4">
      {/* Token totals */}
      <div>
        <h3 className="text-sm font-medium text-foreground mb-3">
          {t('analytics.tokenSummary.title')}
        </h3>
        <p className="text-xl font-semibold text-foreground">
          {formatCompactNumber(tokenSummary.total)}
        </p>
        <div className="mt-2 flex items-center gap-4 text-xs text-muted-foreground">
          <span>{t('analytics.tokenSummary.input')}: <strong className="text-foreground">{formatCompactNumber(tokenSummary.input)}</strong></span>
          <span>{t('analytics.tokenSummary.output')}: <strong className="text-foreground">{formatCompactNumber(tokenSummary.output)}</strong></span>
        </div>
      </div>

      {/* Cache hit rate */}
      <div>
        <div className="flex items-center justify-between text-xs mb-1.5">
          <span className="text-muted-foreground">{t('analytics.tokenSummary.cacheHitRate')}</span>
          <span className="font-medium text-foreground">{formatPercent(tokenSummary.cache_hit_rate)}</span>
        </div>
        <div className="h-2 w-full rounded-full bg-muted/30 overflow-hidden">
          <div
            className="h-full rounded-full bg-emerald-500 dark:bg-emerald-400 transition-all"
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
          <h4 className="text-xs font-medium text-muted-foreground mb-2">
            {t('analytics.tokenSummary.engineDistribution')}
          </h4>

          {/* Mini stacked bar */}
          <div className="flex h-2 rounded-full overflow-hidden gap-px">
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
                <div key={item.engine} className="flex items-center gap-1 text-xs text-muted-foreground">
                  <div
                    className="h-2 w-2 rounded-full shrink-0"
                    style={{ backgroundColor: CHART_COLORS[colorIdx] }}
                  />
                  <span>{label} {item.percentage}%</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Optimization suggestions */}
      {suggestions && suggestions.length > 0 && (
        <div className="pt-3 border-t border-border">
          <h4 className="text-xs font-medium text-muted-foreground mb-2">
            {t('analytics.tokenSummary.suggestions')}
          </h4>
          <div className="space-y-1.5">
            {suggestions.map((s, i) => (
              <div key={i} className="flex items-start gap-2 text-xs">
                <Lightbulb className="h-3 w-3 text-amber-500 shrink-0 mt-0.5" />
                <span className="text-muted-foreground">{t(suggestionMessageKey(s.type), s.params)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
