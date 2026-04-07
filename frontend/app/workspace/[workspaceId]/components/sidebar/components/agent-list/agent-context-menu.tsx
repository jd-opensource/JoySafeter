'use client'

import {
  Copy,
  Pencil,
  Trash2,
} from 'lucide-react'

import { useTranslation } from '@/lib/i18n'

import { SidebarContextMenu, type MenuItemConfig } from '../sidebar-context-menu'

interface AgentContextMenuProps {
  menuPosition: { x: number; y: number }
  onClose: () => void
  onRename?: () => void
  onDuplicate?: () => void
  onDelete?: () => void
}

export function AgentContextMenu({
  menuPosition,
  onClose,
  onRename,
  onDuplicate,
  onDelete,
}: AgentContextMenuProps) {
  const { t } = useTranslation()

  const items: MenuItemConfig[] = []
  if (onRename) items.push({ label: t('workspace.rename'), icon: <Pencil className="h-3 w-3" />, onClick: onRename })
  if (onDuplicate) items.push({ label: t('workspace.duplicate'), icon: <Copy className="h-3 w-3" />, onClick: onDuplicate })
  if (onDelete) items.push({ label: t('workspace.delete'), icon: <Trash2 className="h-3 w-3" />, onClick: onDelete, variant: 'destructive', separator: true })

  return (
    <SidebarContextMenu
      items={items}
      onClose={onClose}
      position={menuPosition}
    />
  )
}
