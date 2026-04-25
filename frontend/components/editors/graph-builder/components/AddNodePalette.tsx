'use client'

import { Search } from 'lucide-react'
import { useMemo, useState } from 'react'

import { Input } from '@/components/ui/input'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

import { nodeRegistry } from '../services/nodeRegistry'

interface AddNodePaletteProps {
  onSelect: (node: { type: string; label: string }) => void
  className?: string
}

export function AddNodePalette({ onSelect, className }: AddNodePaletteProps) {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  const groupedTools = nodeRegistry.getGrouped()

  const filteredGroups = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase()
    return Object.entries(groupedTools)
      .map(([category, items]) => ({
        category,
        items: items.filter((item) => {
          if (!normalizedQuery) return true
          return [item.label, item.subLabel, item.type]
            .filter(Boolean)
            .some((value) => String(value).toLowerCase().includes(normalizedQuery))
        }),
      }))
      .filter((group) => group.items.length > 0)
  }, [groupedTools, query])

  return (
    <div className={cn('flex max-h-[520px] w-80 flex-col overflow-hidden', className)}>
      <div className="border-b border-[var(--border)] p-3">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-[var(--text-muted)]" />
          <Input
            autoFocus
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t('agents.studio.addNode.search', { defaultValue: 'Search nodes...' })}
            className="pl-8"
          />
        </div>
      </div>
      <div className="custom-scrollbar flex-1 overflow-y-auto p-2">
        {filteredGroups.length === 0 ? (
          <p className="px-2 py-6 text-center text-sm text-[var(--text-muted)]">
            {t('agents.studio.addNode.empty', { defaultValue: 'No nodes found' })}
          </p>
        ) : (
          filteredGroups.map((group) => (
            <div key={group.category} className="mb-3">
              <p className="px-2 py-1 text-xs font-bold uppercase tracking-wider text-[var(--text-muted)]">
                {group.category}
              </p>
              <div className="space-y-1">
                {group.items.map((item) => {
                  const Icon = item.icon
                  return (
                    <button
                      key={item.type}
                      type="button"
                      onClick={() => onSelect({ type: item.type, label: item.label })}
                      className="flex w-full items-center gap-3 rounded-xl px-2 py-2 text-left hover:bg-[var(--surface-3)]"
                    >
                      <span className={cn('rounded-lg p-1.5', item.style.bg, item.style.color)}>
                        <Icon size={16} />
                      </span>
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-semibold text-[var(--text-primary)]">
                          {item.label}
                        </span>
                        {item.subLabel && (
                          <span className="block truncate text-xs text-[var(--text-muted)]">
                            {item.subLabel}
                          </span>
                        )}
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
