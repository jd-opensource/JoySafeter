'use client'

import { useState, useRef, useEffect } from 'react'
import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/i18n'
import { Search, ChevronDown, Check } from 'lucide-react'
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
  const update = (patch: Partial<AnalyticsFilters>) => onFiltersChange({ ...filters, ...patch })

  return (
    <div className="mb-4 flex flex-wrap items-center gap-3">
      <TimeRangePills value={filters.range} onChange={(range) => update({ range })} />

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
        <SearchableAgentSelect
          agents={agents}
          value={filters.agent_id}
          onChange={(v) => update({ agent_id: v })}
          placeholder={t('analytics.filters.allAgents')}
          searchPlaceholder={t('analytics.filters.searchAgent')}
        />
      )}
    </div>
  )
}

function SearchableAgentSelect({
  agents,
  value,
  onChange,
  placeholder,
  searchPlaceholder,
}: {
  agents: { id: string; name: string }[]
  value: string | null
  onChange: (v: string | null) => void
  placeholder: string
  searchPlaceholder: string
}) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const filtered = search
    ? agents.filter((a) => a.name.toLowerCase().includes(search.toLowerCase()))
    : agents

  const selectedName = value ? agents.find((a) => a.id === value)?.name : null

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => {
          setOpen(!open)
          setSearch('')
        }}
        className="flex min-w-[140px] items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-sm transition-colors hover:bg-accent/50"
      >
        <span className={cn('max-w-[180px] truncate', !selectedName && 'text-muted-foreground')}>
          {selectedName || placeholder}
        </span>
        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      </button>

      {open && (
        <div className="absolute left-0 top-full z-50 mt-1 w-[260px] rounded-md border border-border bg-card shadow-lg">
          <div className="border-b border-border p-1.5">
            <div className="flex items-center gap-1.5 rounded-md bg-muted/30 px-2 py-1">
              <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={searchPlaceholder}
                className="w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                autoFocus
              />
            </div>
          </div>
          <div className="max-h-[240px] overflow-y-auto p-1">
            <button
              type="button"
              onClick={() => {
                onChange(null)
                setOpen(false)
              }}
              className={cn(
                'flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm transition-colors hover:bg-accent/50',
                !value && 'font-medium',
              )}
            >
              <Check
                className={cn('h-3.5 w-3.5 shrink-0', value ? 'invisible' : 'text-foreground')}
              />
              {placeholder}
            </button>
            {filtered.map((a) => (
              <button
                key={a.id}
                type="button"
                onClick={() => {
                  onChange(a.id)
                  setOpen(false)
                }}
                className={cn(
                  'flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm transition-colors hover:bg-accent/50',
                  value === a.id && 'font-medium',
                )}
              >
                <Check
                  className={cn(
                    'h-3.5 w-3.5 shrink-0',
                    value === a.id ? 'text-foreground' : 'invisible',
                  )}
                />
                <span className="truncate">{a.name}</span>
              </button>
            ))}
            {filtered.length === 0 && (
              <p className="px-2 py-3 text-center text-xs text-muted-foreground">
                {searchPlaceholder}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
