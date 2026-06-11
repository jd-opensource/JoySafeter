'use client'

import { Check } from "lucide-react"
import { useTranslation } from "@/lib/i18n"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu"

interface EventFilterProps {
  selected: Set<string>
  onChange: (selected: Set<string>) => void
  availableTypes: string[]
}

export function EventFilter({ selected, onChange, availableTypes }: EventFilterProps) {
  const { t } = useTranslation()
  const allSelected = selected.size >= availableTypes.length
  const noneSelected = selected.size === 0
  const label = allSelected
    ? t("managed.sessions.allEvents")
    : noneSelected
      ? t("managed.sessions.noFilter")
      : t("managed.sessions.filteredEvents", { count: selected.size })

  const toggleType = (type: string) => {
    const next = new Set(selected)
    if (next.has(type)) {
      next.delete(type)
    } else {
      next.add(type)
    }
    onChange(next)
  }

  const selectAll = () => {
    onChange(new Set(availableTypes))
  }

  const deselectAll = () => {
    onChange(new Set())
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="h-7 text-xs">
          {label} ▾
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="min-w-[240px] max-h-[400px] overflow-y-auto">
        <div className="px-2 py-1.5 flex items-center justify-between">
          <span className="text-xs text-muted-foreground">{t("managed.sessions.filterByType")}</span>
          <div className="flex gap-1">
            <button
              onClick={(e) => { e.stopPropagation(); selectAll() }}
              className="text-[11px] text-primary hover:underline"
            >
              {t("common.all")}
            </button>
            <span className="text-muted-foreground text-[11px]">/</span>
            <button
              onClick={(e) => { e.stopPropagation(); deselectAll() }}
              className="text-[11px] text-primary hover:underline"
            >
              {t("managed.sessions.none")}
            </button>
          </div>
        </div>
        <DropdownMenuSeparator />
        {availableTypes.map((type) => (
          <DropdownMenuItem
            key={type}
            onSelect={(e) => { e.preventDefault(); toggleType(type) }}
            className="gap-2"
          >
            <span className={`w-4 h-4 flex items-center justify-center rounded border ${selected.has(type) ? "bg-primary border-primary" : "border-border"}`}>
              {selected.has(type) && <Check className="w-3 h-3 text-primary-foreground" />}
            </span>
            <span className="font-mono text-xs">{type}</span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
