'use client'

import Link from 'next/link'
import { Filter } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/i18n'
import {
  formatCompactNumber,
  formatDuration,
  formatPercent,
} from '@/lib/managed/analytics/formatters'
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from '@/components/ui/tooltip'
import type { AgentRankingItem } from '@/lib/managed/analytics/types'

interface AgentRankingCardProps {
  data: AgentRankingItem[]
  loading?: boolean
}

export function AgentRankingCard({ data, loading }: AgentRankingCardProps) {
  const { t } = useTranslation()

  if (loading) {
    return (
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="mb-4 h-4 w-32 animate-pulse rounded bg-muted" />
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="mb-2 h-8 animate-pulse rounded bg-muted" />
        ))}
      </div>
    )
  }

  if (!data.length) return null

  // Sort so unused agents appear at the bottom
  const sorted = [...data].sort((a, b) => {
    if (a.activity_status === 'unused' && b.activity_status !== 'unused') return 1
    if (a.activity_status !== 'unused' && b.activity_status === 'unused') return -1
    return 0
  })

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h3 className="mb-3 text-sm font-medium text-foreground">
        {t('analytics.agentRanking.title')}
      </h3>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-muted/30 text-xs text-muted-foreground">
              <th className="py-2 text-left font-medium">{t('analytics.agentRanking.agent')}</th>
              <th className="w-8 py-2" />
              <th className="py-2 text-right font-medium">{t('analytics.agentRanking.tasks')}</th>
              <th className="py-2 text-right font-medium">
                {t('analytics.agentRanking.successRate')}
              </th>
              <th className="py-2 text-right font-medium">
                {t('analytics.agentRanking.avgDuration')}
              </th>
              <th className="py-2 text-right font-medium">{t('analytics.agentRanking.tokens')}</th>
            </tr>
          </thead>
          <tbody>
            {sorted.slice(0, 6).map((agent, index) => (
              <tr
                key={agent.agent_id}
                className={cn(
                  'border-b border-border last:border-0 hover:bg-accent/30',
                  agent.activity_status === 'unused' && 'opacity-50',
                )}
              >
                <td className="py-2 pr-2">
                  <div className="flex items-center gap-2">
                    <span className="w-4 text-xs tabular-nums text-muted-foreground">
                      {index + 1}
                    </span>
                    <Link
                      href={`/managed/agents/${agent.agent_id}`}
                      className="max-w-[140px] truncate text-sm transition-colors hover:text-foreground"
                    >
                      {agent.agent_name}
                    </Link>
                  </div>
                </td>
                <td className="w-8 py-2">
                  <div className="flex items-center gap-1.5">
                    <TooltipProvider delayDuration={200}>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Link
                            href={`/managed/analytics/calls?agent_id=${agent.agent_id}`}
                            className="text-muted-foreground transition-colors hover:text-foreground"
                          >
                            <Filter className="h-3 w-3" />
                          </Link>
                        </TooltipTrigger>
                        <TooltipContent side="top" className="text-xs">
                          {t('analytics.agentRanking.viewCalls')}
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                    <TooltipProvider delayDuration={200}>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <span
                            className={cn(
                              'inline-block h-1.5 w-1.5 cursor-help rounded-full',
                              agent.activity_status === 'active'
                                ? 'bg-emerald-500'
                                : agent.activity_status === 'idle'
                                  ? 'bg-amber-500'
                                  : 'bg-gray-300',
                            )}
                          />
                        </TooltipTrigger>
                        <TooltipContent side="top" className="text-xs">
                          {t(`analytics.agentRanking.${agent.activity_status}`)}
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  </div>
                </td>
                <td className="py-2 text-right tabular-nums">{agent.total_tasks}</td>
                <td className="py-2 text-right">
                  <div className="flex items-center justify-end gap-1.5">
                    <div className="h-1.5 w-12 overflow-hidden rounded-full bg-muted/30">
                      <div
                        className={cn(
                          'h-full rounded-full',
                          agent.success_rate >= 0.95
                            ? 'bg-emerald-500'
                            : agent.success_rate >= 0.8
                              ? 'bg-amber-500'
                              : 'bg-red-500',
                        )}
                        style={{ width: `${agent.success_rate * 100}%` }}
                      />
                    </div>
                    <span
                      className={cn(
                        'text-xs font-medium tabular-nums',
                        agent.success_rate >= 0.95
                          ? 'text-emerald-600 dark:text-emerald-400'
                          : agent.success_rate >= 0.8
                            ? 'text-amber-600 dark:text-amber-400'
                            : 'text-red-600 dark:text-red-400',
                      )}
                    >
                      {formatPercent(agent.success_rate)}
                    </span>
                  </div>
                </td>
                <td className="py-2 text-right tabular-nums text-muted-foreground">
                  {formatDuration(agent.avg_duration_ms)}
                </td>
                <td className="py-2 text-right tabular-nums text-muted-foreground">
                  {formatCompactNumber(agent.total_tokens)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
