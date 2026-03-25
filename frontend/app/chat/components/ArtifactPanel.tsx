'use client'

import { FolderOpen } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import CodeViewer from '@/app/chat/components/CodeViewer'
import FileBrowser, { FileNode } from '@/app/chat/components/FileBrowser'
import { cn } from '@/lib/utils'
import { artifactService } from '@/services/artifactService'

// ─── Helpers ────────────────────────────────────────────────────────────────


function fileTreeToNodes(
  tree: Record<string, { action: string; size?: number; timestamp?: number }>,
): FileNode[] {
  const root: FileNode[] = []

  // Sort paths so parent dirs come first
  const paths = Object.keys(tree).sort()

  for (const fullPath of paths) {
    const parts = fullPath.split('/').filter(Boolean)
    let current = root

    for (let i = 0; i < parts.length; i++) {
      const name = parts[i]
      const isLast = i === parts.length - 1

      if (isLast) {
        // Leaf file node
        const ext = name.includes('.') ? (name.split('.').pop() ?? '') : ''
        current.push({ name, path: fullPath, type: 'file', extension: ext })
      } else {
        // Directory node — find or create
        const dirPath = parts.slice(0, i + 1).join('/')
        let dir = current.find(n => n.type === 'directory' && n.path === dirPath)
        if (!dir) {
          dir = { name, path: dirPath, type: 'directory', children: [] }
          current.push(dir)
        }
        current = dir.children!
      }
    }
  }

  // Sort: directories first, then alphabetically
  const sortNodes = (nodes: FileNode[]) => {
    nodes.sort((a, b) => {
      if (a.type !== b.type) return a.type === 'directory' ? -1 : 1
      return a.name.localeCompare(b.name)
    })
    nodes.filter(n => n.children).forEach(n => sortNodes(n.children!))
  }
  sortNodes(root)

  return root
}

function findFileNode(nodes: FileNode[], path: string): FileNode | null {
  for (const n of nodes) {
    if (n.path === path) return n
    if (n.children) {
      const found = findFileNode(n.children, path)
      if (found) return found
    }
  }
  return null
}

// ─── Component ──────────────────────────────────────────────────────────────

interface ArtifactPanelProps {
  threadId: string
  fileTree?: Record<string, { action: string; size?: number; timestamp?: number }>
  className?: string
  /** Maps a display path (fileTree key) to the actual path passed to liveReadFile. Defaults to identity. */
  filePathResolver?: (displayPath: string) => string
  /** When true, automatically selects and previews the most recently modified file on each file_event. */
  autoPreview?: boolean
}

export function ArtifactPanel({ threadId, fileTree, className, filePathResolver, autoPreview }: ArtifactPanelProps) {
  const files = useMemo(() => {
    if (fileTree && Object.keys(fileTree).length > 0) {
      return fileTreeToNodes(fileTree)
    }
    return []
  }, [fileTree])
  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const [previewContent, setPreviewContent] = useState<string | null>(null)

  // Refs for auto-preview debounce and previous fileTree snapshot
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const prevFileTreeRef = useRef<typeof fileTree>(undefined)
  const selectedPathRef = useRef<string | null>(null)
  selectedPathRef.current = selectedPath

  const fetchContent = useCallback(
    async (path: string) => {
      setSelectedPath(path)
      setPreviewContent(null)
      if (!threadId) return
      try {
        const resolvedPath = filePathResolver ? filePathResolver(path) : path
        const text = await artifactService.liveReadFile(threadId, resolvedPath)
        setPreviewContent(text)
      } catch {
        setPreviewContent('(Failed to load preview)')
      }
    },
    [threadId, filePathResolver],
  )

  const handleSelectFile = useCallback((path: string) => fetchContent(path), [fetchContent])

  // Auto-preview: detect changed files on each fileTree update, debounce fetch
  useEffect(() => {
    if (!autoPreview || !fileTree) return

    const prev = prevFileTreeRef.current
    prevFileTreeRef.current = fileTree

    // Find files whose timestamp changed (newly written or edited)
    const changedPaths = Object.keys(fileTree).filter((p) => {
      const prevEntry = prev?.[p]
      const currEntry = fileTree[p]
      // New file, or same file with updated timestamp
      return !prevEntry || prevEntry.timestamp !== currEntry.timestamp
    })

    if (changedPaths.length === 0) return

    // Pick the file with the latest timestamp among changed paths
    const latestPath = changedPaths.reduce((a, b) =>
      (fileTree[a]?.timestamp ?? 0) >= (fileTree[b]?.timestamp ?? 0) ? a : b,
    )

    // Only auto-switch if nothing is selected, or if the currently selected file was just modified
    const current = selectedPathRef.current
    if (current !== null && current !== latestPath) return

    // Debounce: agent may write many small chunks; wait for a quiet moment
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current)
    refreshTimerRef.current = setTimeout(() => fetchContent(latestPath), 600)
  }, [fileTree, autoPreview, fetchContent])

  // Cleanup debounce timer on unmount
  useEffect(() => () => {
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current)
  }, [])

  const selectedFile = selectedPath ? findFileNode(files, selectedPath) : null
  const ext = selectedFile?.extension?.toLowerCase() ?? ''

  return (
    <div className={cn('flex flex-col bg-[var(--surface-1)] text-[var(--text-primary)]', className)}>
      <div className="flex min-h-0 flex-1">
        <div className="custom-scrollbar w-[168px] flex-shrink-0 overflow-y-auto border-r border-[var(--border)]">
          <FileBrowser files={files} selectedPath={selectedPath} onSelect={handleSelectFile} />
        </div>
        <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
          {selectedPath && (
            <div className="flex shrink-0 items-center gap-2 border-b border-[var(--border-muted)] bg-[var(--surface-1)] p-3">
              <span className="flex-1 truncate text-sm">{selectedPath}</span>
            </div>
          )}
          <div className="custom-scrollbar flex-1 overflow-auto p-3">
            {previewContent !== null && (
              <CodeViewer
                code={previewContent}
                language={ext || 'text'}
                filename={selectedPath ?? undefined}
                showLineNumbers
              />
            )}
            {!selectedPath && (
              <div className="flex flex-col items-center justify-center py-8 text-sm text-[var(--text-muted)]">
                <FolderOpen className="mb-2 h-10 w-10 opacity-50" />
                Select a file to preview
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default ArtifactPanel
