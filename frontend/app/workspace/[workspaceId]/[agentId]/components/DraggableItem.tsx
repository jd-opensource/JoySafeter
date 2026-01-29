'use client'

import { GripVertical, LucideIcon } from 'lucide-react'
import React from 'react'

import { useTranslation } from '@/lib/i18n'

interface NodeDefinition {
  type: string
  label: string
  icon: LucideIcon
  style: {
    color: string
    bg: string
  }
}

export const DraggableItem = ({ def }: { def: NodeDefinition }) => {
  const { t } = useTranslation()
  const Icon = def.icon

  // Get translated label
  const getNodeLabel = (type: string) => {
    const key = `workspace.nodeTypes.${type}`
    try {
      const translated = t(key)
      if (translated && translated !== key) {
        return translated
      }
    } catch {
      // Translation key doesn't exist, use default
    }
    return def.label
  }

  const translatedLabel = getNodeLabel(def.type)

  const onDragStart = (event: React.DragEvent, nodeType: string, label: string) => {
    event.dataTransfer.setData('application/reactflow', nodeType)
    event.dataTransfer.setData('application/label', label)
    event.dataTransfer.effectAllowed = 'move'
  }

  return (
    <div
      className={`
                flex items-center gap-2 p-2 rounded-xl border border-transparent
                hover:bg-gray-100/80 hover:border-gray-200 hover:shadow-sm
                cursor-grab active:cursor-grabbing transition-all group
                select-none bg-white
            `}
      onDragStart={(event) => onDragStart(event, def.type, def.label)}
      draggable
    >
      <div
        className={`p-1.5 rounded-lg ${def.style.bg} ${def.style.color} group-hover:scale-105 transition-transform`}
      >
        <Icon size={16} />
      </div>
      <div className="flex flex-col min-w-0">
        <span className="text-[13px] font-semibold text-gray-700 truncate">{translatedLabel}</span>
        <span className="text-[10px] text-gray-400 truncate">{t('workspace.dragToAdd')}</span>
      </div>
      <GripVertical
        size={12}
        className="ml-auto text-gray-300 group-hover:text-gray-400 flex-shrink-0"
      />
    </div>
  )
}

