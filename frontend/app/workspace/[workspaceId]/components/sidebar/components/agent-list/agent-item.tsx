'use client'

import {
  Bot,
  GripVertical,
  MoreHorizontal,
} from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import React, { useCallback, useState } from 'react'

import type { AgentMetadata } from '@/app/workspace/[workspaceId]/components/sidebar/sidebar'
import { InlineRenameInput } from '@/components/ui/inline-rename-input'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

import { useInlineRename } from '../inline-rename-input'
import { AgentContextMenu } from './agent-context-menu'

/**
 * Agent item component with drag support and context menu
 */
interface AgentItemProps {
  agent: AgentMetadata
  active: boolean
  indented?: boolean
  indentLevel?: number
  onDragStart?: (agentId: string) => void
  onDragEnd?: () => void
  onRename?: (id: string, newName: string) => void
  onDelete?: (id: string) => void
  onDuplicate?: (id: string) => void
  canEdit?: boolean
}

const AgentItem = React.memo(function AgentItem({
  agent,
  active,
  indented = false,
  indentLevel = 0,
  onDragStart,
  onDragEnd,
  onRename,
  onDelete,
  onDuplicate,
  canEdit: _canEdit = true,
}: AgentItemProps) {
  const params = useParams()
  const workspaceId = params.workspaceId as string
  const [isDragging, setIsDragging] = useState(false)
  const [showMenu, setShowMenu] = useState(false)
  const [menuPosition, setMenuPosition] = useState({ x: 0, y: 0 })

  const handleRename = useCallback((newName: string) => {
    onRename?.(agent.id, newName)
  }, [agent.id, onRename])

  const { isEditing, editName, setEditName, startEditing, handleSave: handleSaveRename, handleCancel: handleCancelRename } = useInlineRename(agent.name, handleRename)

  const handleDragStart = (e: React.DragEvent) => {
    if (isEditing) {
      e.preventDefault()
      return
    }
    e.dataTransfer.setData('agentId', agent.id)
    e.dataTransfer.effectAllowed = 'move'
    setIsDragging(true)
    onDragStart?.(agent.id)
  }

  const handleDragEnd = () => {
    setIsDragging(false)
    onDragEnd?.()
  }

  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setMenuPosition({ x: e.clientX, y: e.clientY })
    setShowMenu(true)
  }, [])

  const handleStartRename = useCallback(() => {
    setShowMenu(false)
    startEditing()
  }, [startEditing])

  const handleDelete = useCallback(() => {
    setShowMenu(false)
    onDelete?.(agent.id)
  }, [agent.id, onDelete])

  const handleDuplicate = useCallback(() => {
    setShowMenu(false)
    onDuplicate?.(agent.id)
  }, [agent.id, onDuplicate])

  const indentPadding = indented ? (indentLevel > 0 ? indentLevel * 12 : 16) : 0

  return (
    <>
      <div
        draggable={!isEditing}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
        onContextMenu={handleContextMenu}
        className={cn(
          'group flex items-center rounded-md transition-colors duration-100',
          isDragging && 'opacity-50',
          active
            ? 'bg-[var(--surface-muted)] text-[var(--text-primary)]'
            : 'text-[var(--text-secondary)] hover:bg-[var(--surface-5)]',
        )}
        style={{ marginLeft: `${indentPadding}px` }}
      >
        <div className="flex cursor-grab items-center px-[4px] py-1.5 opacity-0 transition-opacity group-hover:opacity-100">
          <GripVertical className="h-3 w-3 text-[var(--text-tertiary)]" />
        </div>

        {isEditing ? (
          <div className="flex flex-1 items-center gap-1.5 py-[3px] pr-[6px]">
            <Bot className="ml-[2px] h-3.5 w-3.5 flex-shrink-0 text-[var(--brand-500)]" />
            <InlineRenameInput
              value={editName}
              onChange={setEditName}
              onSave={handleSaveRename}
              onCancel={handleCancelRename}
              placeholder="Enter name..."
            />
          </div>
        ) : (
          <TooltipProvider delayDuration={400}>
            <Tooltip>
              <TooltipTrigger asChild>
                <Link
                  href={`/workspace/${workspaceId}/${agent.id}`}
                  className="flex min-w-0 flex-1 items-center py-[5px] pr-[6px]"
                  onClick={(e) => isDragging && e.preventDefault()}
                  onDoubleClick={(e) => {
                    e.preventDefault()
                    handleStartRename()
                  }}
                >
                  <Bot className="mr-[6px] h-3.5 w-3.5 flex-shrink-0 text-[var(--brand-500)]" />
                  <span className="truncate text-xs-plus font-medium">{agent.name}</span>
                  {agent.graphMode === 'code' && (
                    <span className="ml-1.5 flex-shrink-0 rounded bg-primary/10 px-1 py-0.5 text-xxs font-semibold uppercase leading-none text-primary">
                      Code
                    </span>
                  )}
                </Link>
              </TooltipTrigger>
              <TooltipContent
                side="bottom"
                className="max-w-[280px] break-words border border-[var(--border)] bg-[var(--surface-1)] text-[var(--text-primary)] shadow-lg"
              >
                {agent.name}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        )}

        {/* Menu Button */}
        {!isEditing && (
          <button
            type="button"
            className="mr-[4px] rounded-sm p-[4px] opacity-0 transition-opacity hover:bg-[var(--surface-muted)] group-hover:opacity-100"
            onClick={(e) => {
              e.stopPropagation()
              e.preventDefault()
              setMenuPosition({ x: e.clientX, y: e.clientY })
              setShowMenu(!showMenu)
            }}
          >
            <MoreHorizontal className="h-3 w-3 text-[var(--text-tertiary)]" />
          </button>
        )}
      </div>

      {/* Context Menu */}
      {showMenu && (
        <AgentContextMenu
          menuPosition={menuPosition}
          onClose={() => setShowMenu(false)}
          onRename={onRename ? handleStartRename : undefined}
          onDuplicate={onDuplicate ? handleDuplicate : undefined}
          onDelete={onDelete ? handleDelete : undefined}
        />
      )}
    </>
  )
})

AgentItem.displayName = 'AgentItem'

export { AgentItem }
export type { AgentItemProps }
