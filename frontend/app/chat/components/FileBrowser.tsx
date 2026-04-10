'use client'

import {
  File,
  Folder,
  FolderOpen,
  ChevronRight,
  ChevronDown,
  FileCode,
  FileJson,
  FileText,
  Image as ImageIcon,
} from 'lucide-react'
import React, { useState } from 'react'

import { cn } from '@/lib/utils'

export interface FileNode {
  name: string
  path: string
  type: 'file' | 'directory'
  children?: FileNode[]
  extension?: string
  /** MIME content_type propagated from backend (e.g. "text/plain", "image/png") */
  contentType?: string
}

interface FileBrowserProps {
  files: FileNode[]
  selectedPath: string | null
  onSelect: (path: string) => void
  className?: string
}

export default function FileBrowser({
  files,
  selectedPath,
  onSelect,
  className,
}: FileBrowserProps) {
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set())

  const toggleDir = (path: string) => {
    setExpandedDirs((prev) => {
      const next = new Set(prev)
      if (next.has(path)) {
        next.delete(path)
      } else {
        next.add(path)
      }
      return next
    })
  }

  const getFileIcon = (node: FileNode) => {
    if (node.type === 'directory') {
      return expandedDirs.has(node.path) ? (
        <FolderOpen size={16} className="text-[var(--brand-500)]" />
      ) : (
        <Folder size={16} className="text-[var(--brand-500)]" />
      )
    }

    const ext = node.extension?.toLowerCase() || ''
    if (['ts', 'tsx', 'js', 'jsx'].includes(ext)) {
      return <FileCode size={16} className="text-[var(--brand-400)]" />
    }
    if (['json'].includes(ext)) {
      return <FileJson size={16} className="text-[var(--status-warning)]" />
    }
    if (['md', 'txt'].includes(ext)) {
      return <FileText size={16} className="text-[var(--text-tertiary)]" />
    }
    if (['png', 'jpg', 'jpeg', 'gif', 'svg'].includes(ext)) {
      return <ImageIcon size={16} className="text-[var(--brand-600)]" />
    }
    return <File size={16} className="text-[var(--text-muted)]" />
  }

  const renderNode = (node: FileNode, level: number = 0): React.ReactNode => {
    const isExpanded = expandedDirs.has(node.path)
    const isSelected = selectedPath === node.path
    const paddingLeft = level * 16 + 12

    return (
      <div key={node.path}>
        <div
          className={cn(
            'flex cursor-pointer items-center gap-1.5 py-1.5 text-sm transition-colors hover:bg-[var(--surface-3)]',
            isSelected && 'bg-[var(--brand-50)] hover:bg-[var(--brand-100)]',
          )}
          style={{ paddingLeft: `${paddingLeft}px` }}
          onClick={() => {
            if (node.type === 'directory') {
              toggleDir(node.path)
            } else {
              onSelect(node.path)
            }
          }}
        >
          {node.type === 'directory' && (
            <span className="flex-shrink-0">
              {isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            </span>
          )}
          <span className="flex-shrink-0">{getFileIcon(node)}</span>
          <span className={cn('flex-1 truncate', isSelected && 'font-medium text-[var(--brand-700)]')}>
            {node.name}
          </span>
        </div>
        {node.type === 'directory' && isExpanded && node.children && (
          <div>{node.children.map((child) => renderNode(child, level + 1))}</div>
        )}
      </div>
    )
  }

  return (
    <div className={cn('h-full overflow-y-auto', className)}>
      {files.length === 0 ? (
        <div className="mt-8 text-center text-sm text-[var(--text-muted)]">No files available</div>
      ) : (
        <div className="py-2">{files.map((file) => renderNode(file))}</div>
      )}
    </div>
  )
}
