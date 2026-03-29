'use client'

import { Wrench } from 'lucide-react'

import { useTranslation } from '@/lib/i18n'

import { nodeRegistry } from '../services/nodeRegistry'
import { useBuilderStore } from '../stores/builderStore'

import { DraggableItem } from './DraggableItem'

interface ComponentsSidebarProps {
  showHeader?: boolean
}

export function ComponentsSidebar({ showHeader = true }: ComponentsSidebarProps) {
  const { t } = useTranslation()
  const groupedTools = nodeRegistry.getGrouped()

  return (
    <div className="flex h-full flex-col bg-[var(--surface-2)]">
      {/* Header */}
      {showHeader && (
        <div className="flex items-center gap-2 border-b border-[var(--border-muted)] px-3 py-3">
          <Wrench size={14} className="text-[var(--text-tertiary)]" />
          <span className="text-[13px] font-medium text-[var(--text-secondary)]">{t('workspace.components')}</span>
        </div>
      )}

      {/* Component List */}
      <div className="custom-scrollbar flex-1 space-y-4 overflow-y-auto px-2 py-3">
        {Object.entries(groupedTools).map(([category, items]) => {
          if (items.length === 0) return null

          let categoryKey = 'workspace.nodeCategories.actions'
          if (category === 'Agents') categoryKey = 'workspace.nodeCategories.agents'
          else if (category === 'Flow Control') categoryKey = 'workspace.nodeCategories.flowControl'
          else if (category === 'State Management')
            categoryKey = 'workspace.nodeCategories.stateManagement'
          else if (category === 'Aggregation') categoryKey = 'workspace.nodeCategories.aggregation'

          return (
            <div key={category} className="space-y-2">
              <div className="pl-1 text-[10px] font-bold uppercase tracking-wider text-[var(--text-muted)]">
                {t(categoryKey)}
              </div>
              {items.map((def) => (
                <DraggableItem key={def.type} def={def} />
              ))}
            </div>
          )
        })}
      </div>
    </div>
  )
}
