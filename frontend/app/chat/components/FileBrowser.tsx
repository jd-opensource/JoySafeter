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
  Image,
} from 'lucide-react'
import React, { useState } from 'react'

import { cn } from '@/lib/core/utils/cn'

export interface FileNode {
  name: string
  path: string
  type: 'file' | 'directory'
  children?: FileNode[]
  extension?: string
}

interface FileBrowserProps {
  files: FileNode[]
  selectedPath: string | null
  onSelect: (path: string) => void
  className?: string
}

const FileBrowser: React.FC<FileBrowserProps> = ({
  files,
  selectedPath,
  onSelect,
  className,
}) => {
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
        <FolderOpen size={16} className="text-blue-500" />
      ) : (
        <Folder size={16} className="text-blue-500" />
      )
    }

    const ext = node.extension?.toLowerCase() || ''
    if (['ts', 'tsx', 'js', 'jsx'].includes(ext)) {
      return <FileCode size={16} className="text-blue-400" />
    }
    if (['json'].includes(ext)) {
      return <FileJson size={16} className="text-yellow-500" />
    }
    if (['md', 'txt'].includes(ext)) {
      return <FileText size={16} className="text-gray-500" />
    }
    if (['png', 'jpg', 'jpeg', 'gif', 'svg'].includes(ext)) {
      return <Image size={16} className="text-purple-500" />
    }
    return <File size={16} className="text-gray-400" />
  }

  const renderNode = (node: FileNode, level: number = 0): React.ReactNode => {
    const isExpanded = expandedDirs.has(node.path)
    const isSelected = selectedPath === node.path
    const paddingLeft = level * 16 + 12

    return (
      <div key={node.path}>
        <div
          className={cn(
            'flex items-center gap-1.5 py-1.5 cursor-pointer hover:bg-gray-100 transition-colors text-sm',
            isSelected && 'bg-blue-50 hover:bg-blue-100'
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
          <span className={cn('flex-1 truncate', isSelected && 'text-blue-700 font-medium')}>
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
        <div className="text-center text-gray-400 text-sm mt-8">
          No files available
        </div>
      ) : (
        <div className="py-2">
          {files.map((file) => renderNode(file))}
        </div>
      )}
    </div>
  )
}

export default FileBrowser
