'use client'

import {
  Copy,
  Pencil,
  Trash2,
} from 'lucide-react'

import { useTranslation } from '@/lib/i18n'

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

  return (
    <>
      <div className="fixed inset-0 z-[100]" onClick={onClose} />
      <div
        className="fixed z-[101] min-w-[120px] rounded-lg border border-[var(--border)] bg-[var(--surface-1)] p-[4px] shadow-lg"
        style={{
          left: `${menuPosition.x}px`,
          top: `${menuPosition.y}px`,
        }}
      >
        {onRename && (
          <button
            type="button"
            className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-[5px] text-xs-plus font-medium text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-5)]"
            onClick={onRename}
          >
            <Pencil className="h-3 w-3" />
            {t('workspace.rename')}
          </button>
        )}
        {onDuplicate && (
          <button
            type="button"
            className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-[5px] text-xs-plus font-medium text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-5)]"
            onClick={onDuplicate}
          >
            <Copy className="h-3 w-3" />
            {t('workspace.duplicate')}
          </button>
        )}
        {onDelete && (
          <>
            <div className="my-[4px] h-[1px] bg-[var(--border)]" />
            <button
              type="button"
              className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-[5px] text-xs-plus font-medium text-[var(--status-error)] transition-colors hover:bg-[var(--surface-5)]"
              onClick={onDelete}
            >
              <Trash2 className="h-3 w-3" />
              {t('workspace.delete')}
            </button>
          </>
        )}
      </div>
    </>
  )
}
