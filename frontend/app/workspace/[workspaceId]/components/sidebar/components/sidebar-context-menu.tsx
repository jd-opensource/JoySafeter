'use client'

import React from 'react'
import { cn } from '@/lib/utils'

export interface MenuItemConfig {
  label: string
  icon?: React.ReactNode
  onClick: () => void
  variant?: 'default' | 'destructive'
  separator?: boolean // show separator BEFORE this item
}

interface SidebarContextMenuProps {
  items: MenuItemConfig[]
  onClose: () => void
  position?: { x: number; y: number } // for fixed positioning (right-click)
  className?: string // for absolute positioning (button-triggered)
}

export function SidebarContextMenu({ items, onClose, position, className }: SidebarContextMenuProps) {
  return (
    <>
      <div className="fixed inset-0 z-[100]" onClick={onClose} />
      <div
        className={cn(
          'z-[101] min-w-[120px] rounded-lg border border-[var(--border)] bg-[var(--surface-1)] p-1 shadow-lg',
          position ? 'fixed' : 'absolute',
          className,
        )}
        style={position ? { left: `${position.x}px`, top: `${position.y}px` } : undefined}
      >
        {items.map((item, i) => (
          <React.Fragment key={i}>
            {item.separator && <div className="my-1 h-px bg-[var(--border)]" />}
            <button
              type="button"
              className={cn(
                'flex w-full items-center gap-1.5 rounded-md px-1.5 py-[5px] text-sm font-medium transition-colors hover:bg-[var(--surface-5)]',
                item.variant === 'destructive'
                  ? 'text-[var(--status-error)]'
                  : 'text-[var(--text-secondary)]',
              )}
              onClick={() => { item.onClick(); onClose() }}
            >
              {item.icon}
              {item.label}
            </button>
          </React.Fragment>
        ))}
      </div>
    </>
  )
}
