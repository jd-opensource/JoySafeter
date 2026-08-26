'use client'
/**
 * Shared skill workspace + file tree primitives.
 *
 * This module is the single owner of the skill file-tree UI used by both
 * persisted skills and the AI-authoring draft workspace.
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
import type { SkillFileId } from '@/types/entity-id'
import type { SkillFileRecord } from '@/types/managed'

export type SkillWorkspaceFile<FileKey extends string = SkillFileId> = Pick<
  SkillFileRecord,
  'path' | 'file_name'
> & {
  key: FileKey
  size: number
}

export type SkillWorkspaceMoveSource<FileKey extends string = SkillFileId> =
  | { kind: 'file'; fileKey: FileKey; path: string }
  | { kind: 'folder'; path: string }

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export interface TreeNode<FileKey extends string = SkillFileId> {
  name: string
  fullPath: string
  file?: SkillWorkspaceFile<FileKey>
  children: TreeNode<FileKey>[]
}

export function buildFileTree<FileKey extends string>(
  files: SkillWorkspaceFile<FileKey>[],
): TreeNode<FileKey> {
  const root: TreeNode<FileKey> = { name: '', fullPath: '', children: [] }

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

  const sortTree = (node: TreeNode<FileKey>) => {
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

interface FileTreeNodeProps<FileKey extends string> {
  node: TreeNode<FileKey>
  depth: number
  selectedFileKey: FileKey | null
  onSelectFile: (fileKey: FileKey) => void
  onDeleteFile: (fileKey: FileKey) => void
  onDeleteFolder: (folderPath: string) => void
  onAddToFolder: (folderPath: string) => void
  onMove?: (source: SkillWorkspaceMoveSource<FileKey>, destFolderPath: string) => void
  canEdit?: boolean
}

export function FileTreeNode<FileKey extends string>({
  node,
  depth,
  selectedFileKey,
  onSelectFile,
  onDeleteFile,
  onDeleteFolder,
  onAddToFolder,
  onMove,
  canEdit = true,
}: FileTreeNodeProps<FileKey>) {
  const [open, setOpen] = useState(true)
  const [dragOver, setDragOver] = useState(false)
  const paddingLeft = 12 + depth * 16
  const dndEnabled = canEdit && !!onMove

  if (node.file) {
    if (node.name === '.gitkeep') return null
    return (
      <div
        onClick={() => onSelectFile(node.file!.key)}
        draggable={dndEnabled}
        onDragStart={
          dndEnabled
            ? (e) => {
                e.dataTransfer.setData(
                  'text/plain',
                  JSON.stringify({
                    kind: 'file',
                    fileKey: node.file!.key,
                    path: node.file!.path,
                  } satisfies SkillWorkspaceMoveSource<FileKey>),
                )
                e.dataTransfer.effectAllowed = 'move'
              }
            : undefined
        }
        className={`group flex cursor-pointer items-center gap-2 py-1.5 pr-3 transition-colors hover:bg-muted/50 ${
          selectedFileKey === node.file!.key ? 'bg-muted font-medium' : ''
        }`}
        style={{ paddingLeft }}
      >
        <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <span className="flex-1 truncate">{node.name}</span>
        <span className="shrink-0 text-[10px] text-muted-foreground/50">
          {formatBytes(node.file!.size)}
        </span>
        {canEdit && (
          <button
            onClick={(e) => {
              e.stopPropagation()
              onDeleteFile(node.file!.key)
            }}
            className="hidden shrink-0 text-muted-foreground hover:text-destructive group-hover:block"
          >
            <Trash2 className="h-3 w-3" />
          </button>
        )}
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
                e.dataTransfer.setData(
                  'text/plain',
                  JSON.stringify({
                    kind: 'folder',
                    path: node.fullPath,
                  } satisfies SkillWorkspaceMoveSource<FileKey>),
                )
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
                const source = parseSkillWorkspaceMoveSource<FileKey>(
                  e.dataTransfer.getData('text/plain'),
                )
                if (source) onMove!(source, node.fullPath)
              }
            : undefined
        }
        className={`group flex cursor-pointer items-center gap-1 py-1.5 pr-3 text-muted-foreground hover:text-foreground ${
          dragOver ? 'bg-primary/10 ring-1 ring-inset ring-primary/40' : ''
        }`}
        style={{ paddingLeft }}
      >
        {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        <FolderOpen className="h-4 w-4" />
        <span className="ml-1 flex-1">{node.name}/</span>
        {canEdit && (
          <>
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
          </>
        )}
      </div>
      {open &&
        node.children.map((child, i) => (
          <FileTreeNode
            key={child.file?.key ?? child.fullPath + i}
            node={child}
            depth={depth + 1}
            selectedFileKey={selectedFileKey}
            onSelectFile={onSelectFile}
            onDeleteFile={onDeleteFile}
            onDeleteFolder={onDeleteFolder}
            onAddToFolder={onAddToFolder}
            onMove={onMove}
            canEdit={canEdit}
          />
        ))}
    </>
  )
}

export function SkillWorkspace({
  skillName,
  files,
  selectedFileId,
  onSelectFile,
  onSelectMain,
  onAddFolder,
  onAddToFolder,
  onDeleteFile,
  onDeleteFolder,
  onMove,
  isMainSelected,
  canEdit = true,
}: {
  skillName: string
  files: Array<Pick<SkillFileRecord, 'id' | 'path' | 'file_name' | 'size'>>
  selectedFileId: SkillFileId | null
  onSelectFile: (id: SkillFileId) => void
  onSelectMain: () => void
  onAddFolder: () => void
  onAddToFolder: (folderPath: string) => void
  onDeleteFile: (id: SkillFileId) => void
  onDeleteFolder: (folderPath: string) => void
  onMove?: (source: SkillWorkspaceMoveSource<SkillFileId>, destFolderPath: string) => void
  isMainSelected: boolean
  canEdit?: boolean
}) {
  const { t } = useTranslation()
  const [rootOpen, setRootOpen] = useState(true)
  const filteredFiles = files
    .filter((file) => !(file.path === '' && file.file_name.toLowerCase() === 'skill.md'))
    .map((file) => ({
      key: file.id,
      path: file.path,
      file_name: file.file_name,
      size: file.size,
    }))
  const tree = buildFileTree(filteredFiles)

  return (
    <div className="flex h-full w-[260px] shrink-0 flex-col border-r border-border">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <span className="text-sm font-medium">{t('managed.skills.workspace')}</span>
        <Button
          variant="ghost"
          size="sm"
          className="h-6 w-6 p-0"
          disabled={!canEdit}
          onClick={onAddFolder}
          title={t('managed.skills.newFolder')}
        >
          <FolderPlus className="h-4 w-4" />
        </Button>
      </div>

      <div
        className="flex-1 overflow-y-auto py-1 text-sm"
        onDragOver={canEdit && onMove ? (event) => event.preventDefault() : undefined}
        onDrop={
          canEdit && onMove
            ? (event) => {
                const source = parseSkillWorkspaceMoveSource<SkillFileId>(
                  event.dataTransfer.getData('text/plain'),
                )
                if (source) onMove(source, '')
              }
            : undefined
        }
      >
        <div
          onClick={() => setRootOpen((value) => !value)}
          className="flex cursor-pointer items-center gap-1.5 px-2 py-1.5 font-medium text-foreground transition-colors hover:bg-muted/50"
        >
          {rootOpen ? (
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          )}
          <FolderOpen className="h-4 w-4 shrink-0 text-muted-foreground" />
          <span className="truncate">{skillName}</span>
        </div>

        {rootOpen && (
          <>
            <div
              onClick={onSelectMain}
              className={`flex cursor-pointer items-center gap-2 py-1.5 pr-3 transition-colors hover:bg-muted/50 ${
                isMainSelected ? 'bg-muted font-medium' : ''
              }`}
              style={{ paddingLeft: 28 }}
            >
              <FileText className="h-4 w-4 shrink-0 text-blue-500" />
              <span>SKILL.md</span>
            </div>
            {tree.children.length > 0 ? (
              tree.children.map((child, index) => (
                <FileTreeNode
                  key={child.file?.key ?? child.fullPath + index}
                  node={child}
                  depth={1}
                  selectedFileKey={selectedFileId}
                  onSelectFile={onSelectFile}
                  onDeleteFile={onDeleteFile}
                  onDeleteFolder={onDeleteFolder}
                  onAddToFolder={onAddToFolder}
                  onMove={onMove}
                  canEdit={canEdit}
                />
              ))
            ) : (
              <div className="px-3 py-4 text-center text-xs text-muted-foreground/60">
                {t('managed.skills.emptyWorkspace')}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

export function parseSkillWorkspaceMoveSource<FileKey extends string>(
  raw: string,
): SkillWorkspaceMoveSource<FileKey> | null {
  try {
    const value: unknown = JSON.parse(raw)
    if (!value || typeof value !== 'object' || Array.isArray(value)) return null
    const source = value as Record<string, unknown>
    if (source.kind === 'folder' && typeof source.path === 'string') {
      return { kind: 'folder', path: source.path }
    }
    if (
      source.kind === 'file' &&
      typeof source.fileKey === 'string' &&
      typeof source.path === 'string'
    ) {
      return {
        kind: 'file',
        fileKey: source.fileKey as FileKey,
        path: source.path,
      }
    }
    return null
  } catch {
    return null
  }
}
