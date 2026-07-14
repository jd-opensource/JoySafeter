'use client'

import { useState } from 'react'
import { useTranslation } from '@/lib/i18n'
import type { AnalyticsFilters } from '@/lib/managed/analytics/types'
import { useAgentComparison } from '@/lib/managed/analytics/hooks'
import { AnalyticsFilterBar } from '@/components/managed/analytics/analytics-filter-bar'
import { AgentComparison } from '@/components/managed/analytics/agent-comparison'
import { ChartContainer } from '@/components/managed/analytics/chart-container'

export default function AgentComparisonPage() {
  const { t } = useTranslation()
  const [filters, setFilters] = useState<AnalyticsFilters>({
    range: '7d',
    engine: null,
    model: null,
    status: null,
    agent_id: null,
  })

  const comparison = useAgentComparison(filters)

  return (
    <div>
      <AnalyticsFilterBar filters={filters} onFiltersChange={setFilters} />

      <ChartContainer
        title={t('analytics.agentComparison.title')}
        subtitle={t('analytics.agentComparison.subtitle')}
        loading={comparison.isLoading}
        fetching={comparison.isFetching}
        empty={!comparison.data?.length}
        error={comparison.error as Error | null}
      >
        <AgentComparison
          data={comparison.data ?? []}
          loading={comparison.isLoading}
          fetching={comparison.isFetching}
        />
      </ChartContainer>
    </div>
  )
}
