'use client'

import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { Search, X } from 'lucide-react'

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

export interface ScheduleSelectOption {
  value: string
  label: ReactNode
  searchText: string
}

interface SearchableSelectProps {
  value: string
  options: ScheduleSelectOption[]
  onChange: (value: string) => void
  placeholder?: string
  searchPlaceholder: string
  emptyText: string
  clearSearchLabel: string
  disabled?: boolean
  contentClassName?: string
}

export function SearchableSelect({
  value,
  options,
  onChange,
  placeholder,
  searchPlaceholder,
  emptyText,
  clearSearchLabel,
  disabled,
  contentClassName,
}: SearchableSelectProps) {
  const [search, setSearch] = useState('')
  const filteredOptions = useMemo(() => {
    const query = search.trim().toLowerCase()
    if (!query) return options
    return options.filter((option) => option.searchText.toLowerCase().includes(query))
  }, [options, search])

  return (
    <Select value={value} onValueChange={onChange} disabled={disabled}>
      <SelectTrigger>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent className={contentClassName || 'max-h-80'}>
        <div className="sticky top-0 z-10 border-b border-border bg-popover p-2">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              type="text"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              onKeyDown={(event) => event.stopPropagation()}
              placeholder={searchPlaceholder}
              className="w-full rounded-md border border-border bg-background py-1.5 pl-7 pr-7 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
            />
            {search ? (
              <button
                type="button"
                onClick={() => setSearch('')}
                onMouseDown={(event) => event.preventDefault()}
                aria-label={clearSearchLabel}
                className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground/60 hover:bg-accent hover:text-foreground"
              >
                <X className="h-3 w-3" />
              </button>
            ) : null}
          </div>
        </div>
        {filteredOptions.length > 0 ? (
          filteredOptions.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))
        ) : (
          <div className="px-3 py-6 text-center text-xs text-muted-foreground">{emptyText}</div>
        )}
      </SelectContent>
    </Select>
  )
}
