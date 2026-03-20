'use client'

import { FolderOpen } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import CodeViewer from '@/app/chat/components/CodeViewer'
import FileBrowser, { FileNode } from '@/app/chat/components/FileBrowser'
import { artifactService } from '@/services/artifactService'
import { cn } from '@/lib/utils'

// ─── Helpers ────────────────────────────────────────────────────────────────

/** MIME types treated as previewable text */
const TEXT_MIME_PREFIXES = ['text/']
const TEXT_MIME_EXACT = new Set([
  'application/json',
  'application/xml',
  'application/javascript',
  'application/typescript',
  'application/x-yaml',
  'application/x-sh',
  'application/sql',
  'application/x-python',
])

function isTextPreviewable(node: FileNode): boolean {
  const ct = node.contentType
  if (ct) {
    if (TEXT_MIME_PREFIXES.some((p) => ct.startsWith(p))) return true
    if (TEXT_MIME_EXACT.has(ct)) return true
  }
  // Fallback: check extension for files whose backend didn't return content_type
  const ext = (node.extension ?? '').toLowerCase()
  return [
    'txt',
    'md',
    'json',
    'py',
    'js',
    'ts',
    'tsx',
    'jsx',
    'html',
    'css',
    'yaml',
    'yml',
    'sh',
    'sql',
    'xml',
    'log',
    'csv',
    'toml',
    'ini',
    'cfg',
    'env',
    'rs',
    'go',
    'java',
    'c',
    'h',
    'cpp',
  ].includes(ext)
}

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
}

export function ArtifactPanel({ threadId, fileTree, className }: ArtifactPanelProps) {
  const [files, setFiles] = useState<FileNode[]>([])
  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const [previewContent, setPreviewContent] = useState<string | null>(null)

  useEffect(() => {
    if (fileTree && Object.keys(fileTree).length > 0) {
      setFiles(fileTreeToNodes(fileTree))
    } else {
      setFiles([])
    }
  }, [fileTree])

  const handleSelectFile = useCallback(
    async (path: string) => {
      setSelectedPath(path)
      setPreviewContent(null)
      if (!threadId) return
      try {
        const text = await artifactService.liveReadFile(threadId, path)
        setPreviewContent(text)
      } catch {
        setPreviewContent('(Failed to load preview)')
      }
    },
    [threadId],
  )

  const selectedFile = selectedPath ? findFileNode(files, selectedPath) : null
  const ext = selectedFile?.extension?.toLowerCase() ?? ''

  // Suppress unused variable warning — isTextPreviewable kept for future use
  void isTextPreviewable

  return (
    <div className={cn('flex flex-col bg-white text-gray-900', className)}>
      <div className="flex min-h-0 flex-1">
        <div className="custom-scrollbar w-[168px] flex-shrink-0 overflow-y-auto border-r border-gray-200">
          <FileBrowser files={files} selectedPath={selectedPath} onSelect={handleSelectFile} />
        </div>
        <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
          {selectedPath && (
            <div className="flex shrink-0 items-center gap-2 border-b border-gray-100 bg-white p-3">
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
              <div className="flex flex-col items-center justify-center py-8 text-sm text-gray-400">
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
