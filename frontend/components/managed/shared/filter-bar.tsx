'use client'

import type { ReactNode } from 'react'
import { useTranslation } from '@/lib/i18n'
import { Search } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import {
  Select,
  SelectTrigger,
  SelectContent,
  SelectItem,
  SelectValue,
} from '@/components/ui/select'

export interface FilterDef {
  key: string
  label: string
  options: { value: string; label: string }[]
  value: string
  onChange: (value: string) => void
}

interface FilterBarProps {
  searchPlaceholder?: string
  onSearch?: (id: string) => void
  searchValue?: string
  onSearchChange?: (value: string) => void
  filters?: FilterDef[]
  showArchived?: boolean
  onArchivedChange?: (v: boolean) => void
  trailing?: ReactNode
}

export function FilterBar({
  searchPlaceholder = 'Go to ID',
  onSearch,
  searchValue,
  onSearchChange,
  filters,
  showArchived,
  onArchivedChange,
  trailing,
}: FilterBarProps) {
  const { t } = useTranslation()
  return (
    <div
      data-testid="filter-bar"
      className="mb-4 flex flex-col items-stretch gap-3 sm:flex-row sm:flex-wrap sm:items-center"
    >
      {(onSearch || onSearchChange) && (
        <div className="relative w-full sm:w-auto">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder={searchPlaceholder}
            value={searchValue}
            onChange={(e) => onSearchChange?.(e.currentTarget.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') onSearch?.(e.currentTarget.value)
            }}
            className="w-full pl-8 sm:w-[240px]"
          />
        </div>
      )}

      {filters?.map((f) => (
        <Select key={f.key} value={f.value} onValueChange={f.onChange}>
          <SelectTrigger className="w-full min-w-[140px] sm:w-auto">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {f.options.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ))}

      {onArchivedChange !== undefined && (
        <label className="flex w-full cursor-pointer items-center justify-between gap-2 text-sm text-muted-foreground sm:w-auto sm:justify-start">
          {t('managed.filters.showArchived')}
          <Switch checked={showArchived} onCheckedChange={onArchivedChange} />
        </label>
      )}

      {trailing && <div className="w-full sm:ml-auto sm:w-auto">{trailing}</div>}
    </div>
  )
}
