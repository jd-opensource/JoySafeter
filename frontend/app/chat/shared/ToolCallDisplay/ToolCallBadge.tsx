'use client'

import { Check, Loader2, Search, ListTodo, Terminal, FileText, Code2, FolderSearch } from 'lucide-react'
import React from 'react'

import { cn } from '@/lib/utils'

import { formatToolDisplay } from './toolDisplayRegistry'

interface ToolCallBadgeProps {
  name: string
  args: Record<string, any>
  status: 'running' | 'completed' | 'failed'
  onClick?: () => void
}

const toolIconMap: Record<string, React.ElementType> = {
  web_search: Search,
  search: Search,
  grep: Search,
  planner: ListTodo,
  write_todos: ListTodo,
  todo_write: ListTodo,
  read_file: FileText,
  read: FileText,
  write_file: Code2,
  write: Code2,
  create_file: Code2,
  edit_file: Code2,
  edit: Code2,
  str_replace_editor: Code2,
  glob: FolderSearch,
  find_files: FolderSearch,
  ls: FolderSearch,
  list_directory: FolderSearch,
}

export function ToolCallBadge({ name, args, status, onClick }: ToolCallBadgeProps) {
  const isCompleted = status === 'completed'
  const display = formatToolDisplay(name, args)
  const Icon = toolIconMap[name] || Terminal

  return (
    <div className="group/tool mb-2">
      <div
        onClick={onClick}
        className={cn(
          'flex w-fit items-center gap-2 rounded-lg border px-3 py-1.5 text-xs transition-all',
          isCompleted
            ? 'border-[var(--border)] bg-[var(--surface-1)] text-[var(--text-secondary)]'
            : 'border-blue-100 bg-blue-50 text-blue-700',
          onClick && 'cursor-pointer hover:shadow-sm',
        )}
      >
        <Icon size={12} />
        <span className="font-medium">{display.label}</span>

        {display.detail && (
          <span className="ml-1 hidden max-w-[200px] truncate font-mono text-[var(--text-muted)] group-hover/tool:inline">
            {display.detail}
          </span>
        )}

        <div className="ml-2 border-l border-[var(--border-strong)] pl-2">
          {isCompleted ? (
            <Check size={12} className="text-green-500" />
          ) : (
            <Loader2 size={12} className="animate-spin text-blue-500" />
          )}
        </div>
      </div>
    </div>
  )
}
