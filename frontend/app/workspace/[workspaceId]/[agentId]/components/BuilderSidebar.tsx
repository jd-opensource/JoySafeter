'use client'

import { Wrench } from 'lucide-react'
import React from 'react'

import { useTranslation } from '@/lib/i18n'

import { nodeRegistry } from '../services/nodeRegistry'

import { DraggableItem } from './DraggableItem'



interface BuilderSidebarProps {
  showHeader?: boolean
}

export const BuilderSidebar: React.FC<BuilderSidebarProps> = ({ showHeader = true }) => {
  const { t } = useTranslation()
  const groupedTools = nodeRegistry.getGrouped()

  return (
    <div className="flex flex-col h-full bg-white">
      {/* Header */}
      {showHeader && (
        <div className="flex items-center gap-2 px-3 py-3 border-b border-gray-100">
          <Wrench size={14} className="text-gray-500" />
          <span className="text-[13px] font-medium text-gray-700">
            {t('workspace.toolbox')}
          </span>
        </div>
      )}

      {/* Tool List */}
      <div className="flex-1 overflow-y-auto custom-scrollbar px-2 py-3 space-y-4">
        {Object.entries(groupedTools).map(([category, items]) => {
          const categoryKey =
            category === 'Agents'
              ? 'workspace.nodeCategories.agents'
              : category === 'Flow Control'
                ? 'workspace.nodeCategories.flowControl'
                : 'workspace.nodeCategories.actions'
          return (
            <div key={category} className="space-y-2">
              <div className="text-[10px] font-bold text-gray-400 uppercase tracking-wider pl-1">
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
