'use client'

import {
  Folder,
  FolderOpen,
  ChevronRight,
  ChevronDown,
  FileText,
  FileCode,
  Terminal,
} from 'lucide-react'
import React, { useState } from 'react'

import { cn } from '@/lib/utils'

/**
 * File entry from the preview_skill tool output.
 */
export interface PreviewFile {
  path: string
  content: string
  file_type: string
  size: number
}

/**
 * Tree node used to build the hierarchical view.
 */
interface TreeNode {
  name: string
  path: string
  isDirectory: boolean
  children?: TreeNode[]
  file?: PreviewFile
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getFilenameFromPath(path: string): string {
  if (!path.includes('/')) return path
  return path.split('/').pop() || path
}

function getFileIcon(path: string) {
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

/**
 * Build a tree from a flat list of PreviewFile entries.
 */
export function buildPreviewTree(files: PreviewFile[]): {
  skillMdFile: PreviewFile | null
  tree: TreeNode[]
} {
  const skillMdFile = files.find((f) => f.path === 'SKILL.md') || null
  const otherFiles = files.filter((f) => f.path !== 'SKILL.md')

  const root: TreeNode[] = []

  const findOrCreate = (
    nodes: TreeNode[],
    name: string,
    path: string,
    isDir: boolean,
    file?: PreviewFile,
  ): TreeNode => {
    let node = nodes.find((n) => n.name === name)
    if (!node) {
      node = {
        name,
        path,
        isDirectory: isDir,
        children: isDir ? [] : undefined,
        file: isDir ? undefined : file,
      }
      nodes.push(node)
    }
    return node
  }

  for (const file of otherFiles) {
    const parts = file.path.split('/')
    let currentNodes = root
    let currentPath = ''

    for (let i = 0; i < parts.length; i++) {
      const part = parts[i]
      currentPath = currentPath ? `${currentPath}/${part}` : part
      const isLast = i === parts.length - 1

      const node = findOrCreate(currentNodes, part, currentPath, !isLast, isLast ? file : undefined)

      if (!isLast) {
        if (!node.children) node.children = []
        currentNodes = node.children
      }
    }
  }

  // Sort: directories first, then alphabetical
  const sortNodes = (nodes: TreeNode[]): TreeNode[] =>
    nodes
      .sort((a, b) => {
        if (a.isDirectory && !b.isDirectory) return -1
        if (!a.isDirectory && b.isDirectory) return 1
        return a.name.localeCompare(b.name)
      })
      .map((n) => ({ ...n, children: n.children ? sortNodes(n.children) : undefined }))

  return { skillMdFile, tree: sortNodes(root) }
}

// ---------------------------------------------------------------------------
// Tree node renderer
// ---------------------------------------------------------------------------

interface TreeNodeComponentProps {
  node: TreeNode
  activeFilePath: string | null
  onSelectFile: (path: string) => void
  depth?: number
}

function TreeNodeComponent({
  node,
  activeFilePath,
  onSelectFile,
  depth = 0,
}: TreeNodeComponentProps) {
  const [isExpanded, setIsExpanded] = useState(true)

  if (node.isDirectory) {
    return (
      <div className="mb-0.5">
        <div
          className="flex cursor-pointer items-center rounded-lg px-2 py-1 hover:bg-gray-50"
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
        </div>

        {isExpanded && node.children && node.children.length > 0 && (
          <div>
            {node.children.map((child) => (
              <TreeNodeComponent
                key={child.path}
                node={child}
                activeFilePath={activeFilePath}
                onSelectFile={onSelectFile}
                depth={depth + 1}
              />
            ))}
          </div>
        )}
      </div>
    )
  }

  return (
    <div
      onClick={() => onSelectFile(node.path)}
      className={cn(
        'flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1 text-xs transition-colors',
        activeFilePath === node.path
          ? 'bg-emerald-50 font-medium text-emerald-700'
          : 'text-gray-600 hover:bg-gray-50',
      )}
      style={{ paddingLeft: `${depth * 12 + 8}px` }}
    >
      {getFileIcon(node.path)}
      <span className="truncate">{node.name}</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface SkillFileTreeProps {
  files: PreviewFile[]
  activeFilePath: string | null
  onSelectFile: (path: string) => void
}

export default function SkillFileTree({ files, activeFilePath, onSelectFile }: SkillFileTreeProps) {
  const { skillMdFile, tree } = React.useMemo(() => buildPreviewTree(files), [files])

  return (
    <div className="flex-1 overflow-y-auto p-2">
      {/* SKILL.md always at top */}
      {skillMdFile && (
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

      {/* Rest of the tree */}
      {tree.length > 0 && (
        <div className="mt-1 border-t border-gray-100 pt-2">
          {tree.map((node) => (
            <TreeNodeComponent
              key={node.path}
              node={node}
              activeFilePath={activeFilePath}
              onSelectFile={onSelectFile}
            />
          ))}
        </div>
      )}

      {/* Empty state */}
      {!skillMdFile && tree.length === 0 && (
        <div className="py-4 text-center text-xs text-gray-400">No files yet</div>
      )}
    </div>
  )
}
