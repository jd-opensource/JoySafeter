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
  return Object.entries(tree).map(([path, _info]) => {
    const name = path.split('/').pop() ?? path
    const ext = name.includes('.') ? (name.split('.').pop() ?? '') : ''
    return { name, path, type: 'file' as const, extension: ext }
  })
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

  const selectedFile = selectedPath ? files.find((f) => f.path === selectedPath) : null
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
