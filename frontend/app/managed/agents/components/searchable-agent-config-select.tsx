'use client'

import { useMemo, useState } from 'react'
import { Plus, Search, X } from 'lucide-react'

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

export interface SearchableConfigOption {
  value: string
  label: string
  searchText?: string
}

interface SearchableAgentConfigSelectProps {
  value: string
  options: SearchableConfigOption[]
  placeholder: string
  noneLabel: string
  searchPlaceholder: string
  emptyText: string
  createLabel: string
  clearSearchLabel: string
  onChange: (value: string) => void
  onCreate: () => void
}

const NONE_VALUE = '__none__'
const CREATE_VALUE = '__create__'

export function SearchableAgentConfigSelect({
  value,
  options,
  placeholder,
  noneLabel,
  searchPlaceholder,
  emptyText,
  createLabel,
  clearSearchLabel,
  onChange,
  onCreate,
}: SearchableAgentConfigSelectProps) {
  const [search, setSearch] = useState('')
  const filteredOptions = useMemo(() => {
    const query = search.trim().toLowerCase()
    if (!query) return options
    return options.filter((option) =>
      `${option.label} ${option.searchText || ''}`.toLowerCase().includes(query),
    )
  }, [options, search])

  return (
    <Select
      value={value || NONE_VALUE}
      onValueChange={(nextValue) => {
        if (nextValue === CREATE_VALUE) {
          onCreate()
          return
        }
        onChange(nextValue === NONE_VALUE ? '' : nextValue)
      }}
    >
      <SelectTrigger className="w-full">
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent className="max-h-80">
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
                className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground/60 hover:bg-accent hover:text-foreground"
                aria-label={clearSearchLabel}
              >
                <X className="h-3 w-3" />
              </button>
            ) : null}
          </div>
        </div>
        <SelectItem value={NONE_VALUE}>{noneLabel}</SelectItem>
        {filteredOptions.length > 0 ? (
          filteredOptions.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))
        ) : (
          <div className="px-3 py-6 text-center text-xs text-muted-foreground">{emptyText}</div>
        )}
        <SelectItem value={CREATE_VALUE} className="text-primary">
          <span className="flex items-center gap-1.5">
            <Plus className="h-3.5 w-3.5" />
            {createLabel}
          </span>
        </SelectItem>
      </SelectContent>
    </Select>
  )
}
