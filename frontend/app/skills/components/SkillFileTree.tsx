'use client'

import {
  Folder,
  FolderOpen,
  ChevronRight,
  ChevronDown,
  Plus,
  Pencil,
  Trash2,
  FileText,
  FileCode,
  Terminal,
} from 'lucide-react'
import { useState } from 'react'

import { cn } from '@/lib/utils'
import { getFilenameFromPath } from '@/services/skillService'
import { SkillFile, FileTreeNode } from '@/types'

interface SkillFileTreeProps {
  fileTree: { skillMdFile: SkillFile | null; tree: FileTreeNode[] }
  activeFilePath: string | null
  onSelectFile: (path: string) => void
  onDeleteFile: (file: SkillFile) => void
  onRenameFile: (file: SkillFile) => void
  onAddFile: (directory: string) => void
}

/**
 * Get file icon based on file path and type
 * Exported for use in other components
 */
export const getFileIcon = (path: string, fileType: string) => {
  const filename = getFilenameFromPath(path)

  if (filename === 'SKILL.md') return <FileText size={14} className="text-emerald-500" />
  if (filename.endsWith('.md')) return <FileText size={14} className="text-blue-400" />
  if (filename.endsWith('.py')) return <Terminal size={14} className="text-yellow-500" />
  if (filename.endsWith('.js') || filename.endsWith('.ts'))
    return <FileCode size={14} className="text-amber-500" />
  if (filename.endsWith('.json')) return <FileCode size={14} className="text-green-500" />
  if (filename.endsWith('.sh')) return <Terminal size={14} className="text-gray-500" />
  if (filename.endsWith('.yaml') || filename.endsWith('.yml'))
    return <FileCode size={14} className="text-purple-400" />
  if (filename.endsWith('.html') || filename.endsWith('.css'))
    return <FileCode size={14} className="text-pink-500" />

  return <FileCode size={14} className="text-gray-400" />
}

interface FileTreeNodeComponentProps {
  node: FileTreeNode
  activeFilePath: string | null
  onSelectFile: (path: string) => void
  onDeleteFile: (file: SkillFile) => void
  onRenameFile: (file: SkillFile) => void
  onAddFile: (directory: string) => void
  depth?: number
}

function FileTreeNodeComponent({
  node,
  activeFilePath,
  onSelectFile,
  onDeleteFile,
  onRenameFile,
  onAddFile,
  depth = 0,
}: FileTreeNodeComponentProps) {
  const [isExpanded, setIsExpanded] = useState(true)

  if (node.isDirectory) {
    return (
      <div className="mb-0.5">
        <div
          className="group flex cursor-pointer items-center justify-between rounded-lg px-2 py-1 hover:bg-gray-50"
          onClick={() => setIsExpanded(!isExpanded)}
          style={{ paddingLeft: `${depth * 12 + 8}px` }}
        >
          <div className="flex items-center gap-1.5 text-[10px] font-medium text-gray-600">
            {isExpanded ? (
              <ChevronDown size={12} className="text-gray-400" />
            ) : (
              <ChevronRight size={12} className="text-gray-400" />
            )}
            {isExpanded ? (
              <FolderOpen size={12} className="text-amber-500" />
            ) : (
              <Folder size={12} className="text-amber-500" />
            )}
            <span>{node.name}/</span>
          </div>
          <button
            onClick={(e) => {
              e.stopPropagation()
              onAddFile(node.path)
            }}
            className="p-0.5 text-gray-400 opacity-0 transition-opacity hover:text-emerald-600 group-hover:opacity-100"
            title="Add file"
          >
            <Plus size={10} />
          </button>
        </div>

        {isExpanded && node.children && node.children.length > 0 && (
          <div>
            {node.children.map((child) => (
              <FileTreeNodeComponent
                key={child.path}
                node={child}
                activeFilePath={activeFilePath}
                onSelectFile={onSelectFile}
                onDeleteFile={onDeleteFile}
                onRenameFile={onRenameFile}
                onAddFile={onAddFile}
                depth={depth + 1}
              />
            ))}
          </div>
        )}
      </div>
    )
  }

  // File node
  return (
    <div
      onClick={() => onSelectFile(node.path)}
      className={cn(
        'group/file flex cursor-pointer items-center justify-between gap-1 rounded-lg px-2 py-1 text-xs transition-colors',
        activeFilePath === node.path
          ? 'bg-emerald-50 font-medium text-emerald-700'
          : 'text-gray-600 hover:bg-gray-50',
      )}
      style={{ paddingLeft: `${depth * 12 + 8}px` }}
    >
      <div className="flex min-w-0 flex-1 items-center gap-2">
        {getFileIcon(node.path, node.file?.file_type || '')}
        <span className="truncate">{node.name}</span>
      </div>
      {node.file && (
        <div className="flex items-center gap-0.5 opacity-0 transition-opacity group-hover/file:opacity-100">
          <button
            onClick={(e) => {
              e.stopPropagation()
              onRenameFile(node.file!)
            }}
            className="p-0.5 text-gray-400 hover:text-blue-600"
            title="Rename"
          >
            <Pencil size={10} />
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation()
              onDeleteFile(node.file!)
            }}
            className="p-0.5 text-gray-400 hover:text-red-600"
            title="Delete"
          >
            <Trash2 size={10} />
          </button>
        </div>
      )}
    </div>
  )
}

export function SkillFileTree({
  fileTree,
  activeFilePath,
  onSelectFile,
  onDeleteFile,
  onRenameFile,
  onAddFile,
}: SkillFileTreeProps) {
  return (
    <div className="custom-scrollbar flex-1 overflow-y-auto p-2">
      {/* SKILL.md - Always displayed first and prominently */}
      {fileTree.skillMdFile && (
        <div
          onClick={() => onSelectFile('SKILL.md')}
          className={cn(
            'mb-2 flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-xs transition-colors',
            activeFilePath === 'SKILL.md'
              ? 'border border-emerald-200 bg-emerald-50 font-medium text-emerald-700'
              : 'border border-transparent text-gray-700 hover:bg-gray-50',
          )}
        >
          <FileText size={14} className="text-emerald-500" />
          <span className="font-medium">SKILL.md</span>
        </div>
      )}

      {/* File Tree */}
      {fileTree.tree.length > 0 && (
        <div className="mt-1 border-t border-gray-100 pt-2">
          {fileTree.tree.map((node) => (
            <FileTreeNodeComponent
              key={node.path}
              node={node}
              activeFilePath={activeFilePath}
              onSelectFile={onSelectFile}
              onDeleteFile={onDeleteFile}
              onRenameFile={onRenameFile}
              onAddFile={onAddFile}
            />
          ))}
        </div>
      )}

      {/* Empty state */}
      {!fileTree.skillMdFile && fileTree.tree.length === 0 && (
        <div className="py-4 text-center text-xs text-gray-400">No files yet</div>
      )}
    </div>
  )
}
