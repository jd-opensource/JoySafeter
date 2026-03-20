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
      className={`group flex cursor-grab select-none items-center gap-2 rounded-xl border border-transparent bg-white p-2 transition-all hover:border-gray-200 hover:bg-gray-100/80 hover:shadow-sm active:cursor-grabbing`}
      onDragStart={(event) => onDragStart(event, def.type, def.label)}
      draggable
    >
      <div
        className={`rounded-lg p-1.5 ${def.style.bg} ${def.style.color} transition-transform group-hover:scale-105`}
      >
        <Icon size={16} />
      </div>
      <div className="flex min-w-0 flex-col">
        <span className="truncate text-[13px] font-semibold text-gray-700">{translatedLabel}</span>
        <span className="truncate text-[10px] text-gray-400">{t('workspace.dragToAdd')}</span>
      </div>
      <GripVertical
        size={12}
        className="ml-auto flex-shrink-0 text-gray-300 group-hover:text-gray-400"
      />
    </div>
  )
}
