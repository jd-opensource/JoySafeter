'use client'

import { Download, FolderOpen, Loader2 } from 'lucide-react'
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import CodeViewer from '@/app/chat/components/CodeViewer'
import FileBrowser, { FileNode } from '@/app/chat/components/FileBrowser'
import { Button } from '@/components/ui/button'
import {
  artifactService,
  type FileInfo,
} from '@/services/artifactService'
import { cn } from '@/lib/core/utils/cn'

// ─── Helpers ────────────────────────────────────────────────────────────────

function fileInfoToNode(f: FileInfo): FileNode {
  const ext = f.name.includes('.') ? f.name.split('.').pop() ?? '' : ''
  return {
    name: f.name,
    path: f.path,
    type: f.type as 'file' | 'directory',
    children: f.children?.map(fileInfoToNode),
    extension: ext,
    // Propagate content_type from backend for smarter preview detection
    contentType: f.content_type,
  }
}

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
  const ct = (node as any).contentType as string | undefined
  if (ct) {
    if (TEXT_MIME_PREFIXES.some((p) => ct.startsWith(p))) return true
    if (TEXT_MIME_EXACT.has(ct)) return true
  }
  // Fallback: check extension for files whose backend didn't return content_type
  const ext = (node.extension ?? '').toLowerCase()
  return ['txt', 'md', 'json', 'py', 'js', 'ts', 'tsx', 'jsx', 'html', 'css', 'yaml', 'yml', 'sh', 'sql', 'xml', 'log', 'csv', 'toml', 'ini', 'cfg', 'env', 'rs', 'go', 'java', 'c', 'h', 'cpp'].includes(ext)
}

// ─── Component ──────────────────────────────────────────────────────────────

interface ArtifactPanelProps {
  threadId: string
  runId?: string | null
  className?: string
}

export const ArtifactPanel: React.FC<ArtifactPanelProps> = ({
  threadId,
  runId,
  className,
}) => {
  const [files, setFiles] = useState<FileNode[]>([])
  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const [previewContent, setPreviewContent] = useState<string | null>(null)
  const [previewBlobUrl, setPreviewBlobUrl] = useState<string | null>(null)
  const [loadingFiles, setLoadingFiles] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Keep a ref to the latest blob URL so cleanup on unmount works
  const blobUrlRef = useRef<string | null>(null)

  // Build path→node map once when files change (O(1) lookup instead of O(n))
  const nodeMap = useMemo(() => {
    const map = new Map<string, FileNode>()
    const walk = (nodes: FileNode[]) => {
      for (const n of nodes) {
        map.set(n.path, n)
        if (n.children) walk(n.children)
      }
    }
    walk(files)
    return map
  }, [files])

  // Cleanup blob URL on unmount to prevent memory leak
  useEffect(() => {
    return () => {
      if (blobUrlRef.current) {
        URL.revokeObjectURL(blobUrlRef.current)
      }
    }
  }, [])

  useEffect(() => {
    if (!threadId || !runId) {
      setFiles([])
      return
    }
    setLoadingFiles(true)
    setError(null)
    artifactService
      .listRunFiles(threadId, runId)
      .then((list) => setFiles(list.map(fileInfoToNode)))
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load files'))
      .finally(() => setLoadingFiles(false))
  }, [threadId, runId])

  const handleSelectFile = useCallback(
    async (path: string) => {
      setSelectedPath(path)
      setPreviewContent(null)
      // Revoke previous blob URL
      if (blobUrlRef.current) {
        URL.revokeObjectURL(blobUrlRef.current)
        blobUrlRef.current = null
        setPreviewBlobUrl(null)
      }
      if (!threadId || !runId) return
      const node = nodeMap.get(path)
      if (!node || node.type === 'directory') return
      try {
        const blob = await artifactService.downloadFile(threadId, runId, path)
        if (isTextPreviewable(node)) {
          const text = await blob.text()
          setPreviewContent(text)
        } else {
          const url = URL.createObjectURL(blob)
          blobUrlRef.current = url
          setPreviewBlobUrl(url)
        }
      } catch {
        setPreviewContent('(Failed to load preview)')
      }
    },
    [threadId, runId, nodeMap]
  )

  const handleDownload = useCallback(async () => {
    if (!selectedPath || !threadId || !runId) return
    try {
      const blob = await artifactService.downloadFile(threadId, runId, selectedPath)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = selectedPath.split('/').pop() ?? 'file'
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      setError('Download failed')
    }
  }, [threadId, runId, selectedPath])

  const selectedFile = selectedPath ? nodeMap.get(selectedPath) : null
  const ext = selectedFile?.extension?.toLowerCase() ?? ''

  return (
    <div className={cn('flex flex-col bg-white text-gray-900', className)}>
      {error && (
        <div className="px-3 py-2 text-sm text-red-600 border-b border-gray-100">
          {error}
        </div>
      )}
      <div className="flex flex-1 min-h-0">
        <div className="w-[168px] border-r border-gray-200 overflow-y-auto flex-shrink-0 custom-scrollbar">
          {loadingFiles ? (
            <div className="flex items-center justify-center p-4">
              <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
            </div>
          ) : (
            <FileBrowser
              files={files}
              selectedPath={selectedPath}
              onSelect={handleSelectFile}
            />
          )}
        </div>
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          {selectedPath && (
            <div className="flex items-center gap-2 p-3 border-b border-gray-100 bg-white shrink-0">
              <span className="text-sm truncate flex-1">{selectedPath}</span>
              <Button variant="outline" size="sm" onClick={handleDownload}>
                <Download className="h-4 w-4 mr-1" />
                Download
              </Button>
            </div>
          )}
          <div className="flex-1 overflow-auto p-3 custom-scrollbar">
            {previewContent !== null && (
              <CodeViewer
                code={previewContent}
                language={ext || 'text'}
                filename={selectedPath ?? undefined}
                showLineNumbers
              />
            )}
            {previewBlobUrl && !previewContent && (
              <div className="flex items-center justify-center p-4">
                <img
                  src={previewBlobUrl}
                  alt={selectedPath ?? 'Preview'}
                  className="max-w-full max-h-[70vh] object-contain"
                />
              </div>
            )}
            {!selectedPath && !loadingFiles && (
              <div className="flex flex-col items-center justify-center text-gray-400 text-sm py-8">
                <FolderOpen className="h-10 w-10 mb-2 opacity-50" />
                Select a file to preview or download
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default ArtifactPanel
