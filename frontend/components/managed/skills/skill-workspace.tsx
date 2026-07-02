'use client'
/**
 * Shared skill workspace + file tree primitives.
 *
 * Extracted from ``app/managed/skills/page.tsx`` so the AI authoring page
 * (``app/managed/skills/new-ai/page.tsx``) can render the same left-side
 * file tree it does on the detail page. No behavior change — these are the
 * same components, just exported from a stable module path.
 *
 * Components / helpers:
 *   - ``TreeNode``        — folder + file tree model
 *   - ``buildFileTree``   — turn flat ``SkillFile[]`` into a TreeNode
 *   - ``FileTreeNode``    — recursive renderer for one tree node
 *   - ``SkillWorkspace``  — the full 260px left panel (SKILL.md + tree)
 *   - ``formatBytes``     — pretty file size
 */
import { useState } from 'react'

import {
  ChevronDown,
  ChevronRight,
  FileText,
  FolderOpen,
  FolderPlus,
  Plus,
  Trash2,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import { useTranslation } from '@/lib/i18n'
import type { SkillFileRecord } from '@/types/managed'

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export interface TreeNode {
  name: string
  fullPath: string
  file?: SkillFileRecord
  children: TreeNode[]
}

export function buildFileTree(files: SkillFileRecord[]): TreeNode {
  const root: TreeNode = { name: '', fullPath: '', children: [] }

  for (const f of files) {
    const parts = f.path.split('/').filter(Boolean)

    let current = root
    for (const part of parts) {
      let child = current.children.find((c) => c.name === part && !c.file)
      if (!child) {
        const prefix = current.fullPath
        child = { name: part, fullPath: prefix + part + '/', children: [] }
        current.children.push(child)
      }
      current = child
    }
    current.children.push({
      name: f.file_name,
      fullPath: f.path + f.file_name,
      file: f,
      children: [],
    })
  }

  const sortTree = (node: TreeNode) => {
    node.children.sort((a, b) => {
      if (a.file && !b.file) return 1
      if (!a.file && b.file) return -1
      return a.name.localeCompare(b.name)
    })
    node.children.forEach(sortTree)
  }
  sortTree(root)
  return root
}

export function FileTreeNode({
  node,
  depth,
  selectedFileId,
  onSelectFile,
  onDeleteFile,
  onDeleteFolder,
  onAddToFolder,
  onMove,
}: {
  node: TreeNode
  depth: number
  selectedFileId: string | null
  onSelectFile: (id: string) => void
  onDeleteFile: (id: string) => void
  onDeleteFolder: (folderPath: string) => void
  onAddToFolder: (folderPath: string) => void
  /** When provided, nodes become draggable and folders accept drops.
   * ``sourcePath`` is a file's full path or a folder's ``fullPath`` (trailing
   * ``/``); ``destFolderPath`` is the target folder's ``fullPath`` or ``''``. */
  onMove?: (sourcePath: string, destFolderPath: string) => void
}) {
  const [open, setOpen] = useState(true)
  const [dragOver, setDragOver] = useState(false)
  const paddingLeft = 12 + depth * 16
  const dndEnabled = !!onMove

  if (node.file) {
    if (node.name === '.gitkeep') return null
    return (
      <div
        onClick={() => onSelectFile(node.file!.id)}
        draggable={dndEnabled}
        onDragStart={
          dndEnabled
            ? (e) => {
                e.dataTransfer.setData('text/plain', node.file!.id)
                e.dataTransfer.effectAllowed = 'move'
              }
            : undefined
        }
        className={`group flex cursor-pointer items-center gap-2 py-1.5 pr-3 transition-colors hover:bg-muted/50 ${
          selectedFileId === node.file!.id ? 'bg-muted font-medium' : ''
        }`}
        style={{ paddingLeft }}
      >
        <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <span className="flex-1 truncate">{node.name}</span>
        <span className="shrink-0 text-[10px] text-muted-foreground/50">
          {formatBytes(node.file!.size)}
        </span>
        <button
          onClick={(e) => {
            e.stopPropagation()
            onDeleteFile(node.file!.id)
          }}
          className="hidden shrink-0 text-muted-foreground hover:text-destructive group-hover:block"
        >
          <Trash2 className="h-3 w-3" />
        </button>
      </div>
    )
  }

  return (
    <>
      <div
        onClick={() => setOpen(!open)}
        draggable={dndEnabled}
        onDragStart={
          dndEnabled
            ? (e) => {
                e.stopPropagation()
                e.dataTransfer.setData('text/plain', node.fullPath)
                e.dataTransfer.effectAllowed = 'move'
              }
            : undefined
        }
        onDragOver={
          dndEnabled
            ? (e) => {
                e.preventDefault()
                e.dataTransfer.dropEffect = 'move'
                if (!dragOver) setDragOver(true)
              }
            : undefined
        }
        onDragLeave={dndEnabled ? () => setDragOver(false) : undefined}
        onDrop={
          dndEnabled
            ? (e) => {
                e.preventDefault()
                e.stopPropagation()
                setDragOver(false)
                const source = e.dataTransfer.getData('text/plain')
                if (source) onMove!(source, node.fullPath)
              }
            : undefined
        }
        className={`group flex cursor-pointer items-center gap-1 py-1.5 pr-3 text-muted-foreground hover:text-foreground ${
          dragOver ? 'bg-primary/10 ring-1 ring-inset ring-primary/40' : ''
        }`}
        style={{ paddingLeft }}
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5" />
        )}
        <FolderOpen className="h-4 w-4" />
        <span className="ml-1 flex-1">{node.name}/</span>
        <button
          onClick={(e) => {
            e.stopPropagation()
            onAddToFolder(node.fullPath)
          }}
          className="hidden shrink-0 text-muted-foreground hover:text-foreground group-hover:block"
        >
          <Plus className="h-3 w-3" />
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation()
            onDeleteFolder(node.fullPath)
          }}
          className="hidden shrink-0 text-muted-foreground hover:text-destructive group-hover:block"
        >
          <Trash2 className="h-3 w-3" />
        </button>
      </div>
      {open &&
        node.children.map((child, i) => (
          <FileTreeNode
            key={child.file?.id ?? child.fullPath + i}
            node={child}
            depth={depth + 1}
            selectedFileId={selectedFileId}
            onSelectFile={onSelectFile}
            onDeleteFile={onDeleteFile}
            onDeleteFolder={onDeleteFolder}
            onAddToFolder={onAddToFolder}
            onMove={onMove}
          />
        ))}
    </>
  )
}

export function SkillWorkspace({
  files,
  selectedFileId,
  onSelectFile,
  onSelectMain,
  onAddFolder,
  onAddToFolder,
  onDeleteFile,
  onDeleteFolder,
  isMainSelected,
}: {
  files: SkillFileRecord[]
  selectedFileId: string | null
  onSelectFile: (id: string) => void
  onSelectMain: () => void
  onAddFolder: () => void
  onAddToFolder: (folderPath: string) => void
  onDeleteFile: (id: string) => void
  onDeleteFolder: (folderPath: string) => void
  isMainSelected: boolean
}) {
  const { t } = useTranslation()
  const filteredFiles = files.filter(
    (f) => !(f.path === '' && f.file_name.toLowerCase() === 'skill.md'),
  )
  const tree = buildFileTree(filteredFiles)

  return (
    <div className="flex h-full w-[260px] shrink-0 flex-col border-r border-border">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <span className="text-sm font-medium">{t('managed.skills.workspace')}</span>
        <Button
          variant="ghost"
          size="sm"
          className="h-6 w-6 p-0"
          onClick={onAddFolder}
          title={t('managed.skills.newFolder')}
        >
          <FolderPlus className="h-4 w-4" />
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto text-sm">
        {/* SKILL.md -- always first */}
        <div
          onClick={onSelectMain}
          className={`flex cursor-pointer items-center gap-2 px-3 py-1.5 transition-colors hover:bg-muted/50 ${
            isMainSelected ? 'bg-muted font-medium' : ''
          }`}
        >
          <FileText className="h-4 w-4 text-blue-500" />
          <span>SKILL.md</span>
        </div>

        {/* File tree */}
        {tree.children.length > 0 ? (
          tree.children.map((child, i) => (
            <FileTreeNode
              key={child.file?.id ?? child.fullPath + i}
              node={child}
              depth={0}
              selectedFileId={selectedFileId}
              onSelectFile={onSelectFile}
              onDeleteFile={onDeleteFile}
              onDeleteFolder={onDeleteFolder}
              onAddToFolder={onAddToFolder}
            />
          ))
        ) : (
          <div className="px-3 py-4 text-center text-xs text-muted-foreground/60">
            {t('managed.skills.emptyWorkspace')}
          </div>
        )}
      </div>
    </div>
  )
}
