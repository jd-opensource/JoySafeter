'use client'

import { useState, useMemo } from 'react'
import Link from 'next/link'
import { ArrowRight } from 'lucide-react'
import { useTranslation } from '@/lib/i18n'
import type { AnalyticsFilters, AlertConfig } from '@/lib/managed/analytics/types'
import {
  useCallsTimeseries,
  useTokensTimeseries,
  useLatencyTimeseries,
  useEngineShare,
  useHealthCheck,
  useAgentsForFilters,
  useAgentRanking,
  useErrorSummary,
  useLatencyStats,
} from '@/lib/managed/analytics/hooks'
import { AnalyticsFilterBar } from '@/components/managed/analytics/analytics-filter-bar'
import { PageHeader } from '@/components/managed/shared'
import { HealthStatusBar } from '@/components/managed/analytics/health-status-bar'
import { AlertList } from '@/components/managed/analytics/alert-list'
import { AgentRankingCard } from '@/components/managed/analytics/agent-ranking-card'
import { TokenSummaryCard } from '@/components/managed/analytics/token-summary-card'
import { ErrorSummaryCard } from '@/components/managed/analytics/error-summary-card'
import { LatencyStatsCard } from '@/components/managed/analytics/latency-stats-card'
import { CallsTrendChart } from '@/components/managed/analytics/calls-trend-chart'
import { TokenTrendChart } from '@/components/managed/analytics/token-trend-chart'
import { LatencyTrendChart } from '@/components/managed/analytics/latency-trend-chart'

const DEFAULT_ALERT_CONFIG: AlertConfig = {
  consecutive_failures: { enabled: true, threshold: 3 },
  slow_agent: { enabled: true, threshold: 10000 },
  token_spike: { enabled: true, threshold: 30 },
}

function loadAlertConfig(): AlertConfig {
  if (typeof window === 'undefined') return DEFAULT_ALERT_CONFIG
  try {
    const saved = localStorage.getItem('analytics_alert_config')
    return saved ? { ...DEFAULT_ALERT_CONFIG, ...JSON.parse(saved) } : DEFAULT_ALERT_CONFIG
  } catch {
    return DEFAULT_ALERT_CONFIG
  }
}

export default function AnalyticsOverviewPage() {
  const { t } = useTranslation()
  const [filters, setFilters] = useState<AnalyticsFilters>({
    range: '7d',
    engine: null,
    model: null,
    status: null,
    agent_id: null,
  })
  const [alertConfig, setAlertConfig] = useState<AlertConfig>(loadAlertConfig)

  const handleAlertConfigChange = (config: AlertConfig) => {
    setAlertConfig(config)
    localStorage.setItem('analytics_alert_config', JSON.stringify(config))
  }

  const health = useHealthCheck(filters, alertConfig)
  const callsTs = useCallsTimeseries(filters)
  const tokensTs = useTokensTimeseries(filters)
  const latencyTs = useLatencyTimeseries(filters)
  const engineShare = useEngineShare(filters)
  const agentsList = useAgentsForFilters()
  const agentRanking = useAgentRanking(filters)
  const errorSummary = useErrorSummary(filters)
  const latencyStats = useLatencyStats(filters)

  const engines = useMemo(() => {
    if (!agentsList.data) return undefined
    return [...new Set(agentsList.data.map((a) => a.engine_kind).filter(Boolean))]
  }, [agentsList.data])

  return (
    <div className="space-y-5">
      <PageHeader title={t('analytics.tabs.overview')} subtitle={t('analytics.subtitle')} />
      <AnalyticsFilterBar filters={filters} onFiltersChange={setFilters} />

      <HealthStatusBar data={health.data} loading={health.isLoading} />

      {/* Main content: charts left, sidebar right */}
      <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-[1fr_280px]">
        {/* Left: charts */}
        <div className="space-y-5">
          <CallsTrendChart
            data={callsTs.data ?? []}
            range={filters.range}
            loading={callsTs.isLoading}
            fetching={callsTs.isFetching}
          />
          <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
            <TokenTrendChart
              data={tokensTs.data ?? []}
              range={filters.range}
              loading={tokensTs.isLoading}
              fetching={tokensTs.isFetching}
            />
            <LatencyTrendChart
              data={latencyTs.data ?? []}
              range={filters.range}
              loading={latencyTs.isLoading}
              fetching={latencyTs.isFetching}
            />
          </div>
          {/* Error distribution + Duration distribution */}
          <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
            <ErrorSummaryCard data={errorSummary.data} loading={errorSummary.isLoading} />
            <LatencyStatsCard data={latencyStats.data} loading={latencyStats.isLoading} />
          </div>
        </div>

        {/* Right: token summary + alerts */}
        <div className="space-y-4 lg:sticky lg:top-4">
          <TokenSummaryCard
            tokenSummary={health.data?.token_summary}
            engineShare={engineShare.data ?? []}
            suggestions={health.data?.suggestions}
            loading={health.isLoading || engineShare.isLoading}
          />
          <AlertList
            alerts={health.data?.alerts ?? []}
            loading={health.isLoading}
            config={alertConfig}
            onConfigChange={handleAlertConfigChange}
          />
        </div>
      </div>

      {/* Agent ranking */}
      <AgentRankingCard data={agentRanking.data ?? []} loading={agentRanking.isLoading} />

      {/* Footer link */}
      <div className="flex justify-end">
        <Link
          href="/managed/analytics/calls"
          className="flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          {t('analytics.viewAllCalls')}
          <ArrowRight className="h-4 w-4" />
        </Link>
      </div>
    </div>
  )
}
