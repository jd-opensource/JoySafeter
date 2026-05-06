'use client'

import { AddNodePalette } from './AddNodePalette'

interface CanvasContextMenuProps {
  open: boolean
  x: number
  y: number
  onClose: () => void
  onAddNode: (node: { type: string; label: string }) => void
}

export function CanvasContextMenu({ open, x, y, onClose, onAddNode }: CanvasContextMenuProps) {
  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-[80]"
      onClick={onClose}
      onContextMenu={(event) => event.preventDefault()}
    >
      <div
        className="absolute rounded-xl border border-[var(--border)] bg-[var(--surface-elevated)] shadow-2xl"
        style={{ left: x, top: y }}
        onClick={(event) => event.stopPropagation()}
      >
        <AddNodePalette
          onSelect={(node) => {
            onAddNode(node)
            onClose()
          }}
        />
      </div>
    </div>
  )
}
