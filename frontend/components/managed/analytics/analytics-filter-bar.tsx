'use client'

import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/i18n'
import type { AnalyticsFilters, TimeRange } from '@/lib/managed/analytics/types'
import { TIME_RANGE_OPTIONS, CALL_STATUS_OPTIONS } from './constants'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

interface AnalyticsFilterBarProps {
  filters: AnalyticsFilters
  onFiltersChange: (filters: AnalyticsFilters) => void
  engines?: string[]
  models?: string[]
  agents?: { id: string; name: string }[]
  showStatusFilter?: boolean
}

function TimeRangePills({
  value,
  onChange,
}: {
  value: TimeRange
  onChange: (v: TimeRange) => void
}) {
  const { t } = useTranslation()

  return (
    <div className="flex items-center gap-1">
      {TIME_RANGE_OPTIONS.map((opt) => (
        <button
          key={opt.value}
          type="button"
          aria-pressed={opt.value === value}
          onClick={() => onChange(opt.value)}
          className={cn(
            'rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
            opt.value === value
              ? 'bg-primary text-primary-foreground'
              : 'bg-secondary text-secondary-foreground hover:bg-secondary/80',
          )}
        >
          {opt.labelKey ? t(opt.labelKey) : opt.label}
        </button>
      ))}
    </div>
  )
}

export function AnalyticsFilterBar({
  filters,
  onFiltersChange,
  engines,
  models,
  agents,
  showStatusFilter = false,
}: AnalyticsFilterBarProps) {
  const { t } = useTranslation()
  const update = (patch: Partial<AnalyticsFilters>) =>
    onFiltersChange({ ...filters, ...patch })

  return (
    <div className="mb-4 flex flex-wrap items-center gap-3">
      <TimeRangePills
        value={filters.range}
        onChange={(range) => update({ range })}
      />

      {engines && engines.length > 0 && (
        <Select
          value={filters.engine ?? '__all__'}
          onValueChange={(v) => update({ engine: v === '__all__' ? null : v })}
        >
          <SelectTrigger className="w-auto min-w-[140px]">
            <SelectValue placeholder={t('analytics.filters.engine')} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">{t('analytics.filters.allEngines')}</SelectItem>
            {engines.map((e) => (
              <SelectItem key={e} value={e}>
                {e}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}

      {models && models.length > 0 && (
        <Select
          value={filters.model ?? '__all__'}
          onValueChange={(v) => update({ model: v === '__all__' ? null : v })}
        >
          <SelectTrigger className="w-auto min-w-[140px]">
            <SelectValue placeholder={t('analytics.filters.model')} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">{t('analytics.filters.allModels')}</SelectItem>
            {models.map((m) => (
              <SelectItem key={m} value={m}>
                {m}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}

      {showStatusFilter && (
        <Select
          value={filters.status ?? '__all__'}
          onValueChange={(v) =>
            update({ status: v === '__all__' ? null : (v as AnalyticsFilters['status']) })
          }
        >
          <SelectTrigger className="w-auto min-w-[140px]">
            <SelectValue placeholder={t('analytics.filters.status')} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">{t('analytics.filters.allStatuses')}</SelectItem>
            {CALL_STATUS_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {t(opt.labelKey)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}

      {agents && agents.length > 0 && (
        <Select
          value={filters.agent_id ?? '__all__'}
          onValueChange={(v) =>
            update({ agent_id: v === '__all__' ? null : v })
          }
        >
          <SelectTrigger className="w-auto min-w-[140px]">
            <SelectValue placeholder={t('analytics.filters.agent')} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">{t('analytics.filters.allAgents')}</SelectItem>
            {agents.map((a) => (
              <SelectItem key={a.id} value={a.id}>
                {a.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
    </div>
  )
}
