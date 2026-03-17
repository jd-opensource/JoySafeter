'use client'

import { Download, FolderOpen, Loader2 } from 'lucide-react'
import React, { useCallback, useEffect, useState } from 'react'

import CodeViewer from '@/app/chat/components/CodeViewer'
import FileBrowser, { FileNode } from '@/app/chat/components/FileBrowser'
import { Button } from '@/components/ui/button'
import {
  artifactService,
  type FileInfo,
  type RunInfo,
} from '@/services/artifactService'
import { cn } from '@/lib/core/utils/cn'

function fileInfoToNode(f: FileInfo): FileNode {
  const ext = f.name.includes('.') ? f.name.split('.').pop() ?? '' : ''
  return {
    name: f.name,
    path: f.path,
    type: f.type as 'file' | 'directory',
    children: f.children?.map(fileInfoToNode),
    extension: ext,
  }
}

function flattenNodes(nodes: FileNode[]): FileNode[] {
  return nodes.flatMap((n) => (n.children?.length ? [n, ...flattenNodes(n.children)] : [n]))
}

interface ArtifactPanelProps {
  threadId: string
  runId?: string | null
  className?: string
}

export const ArtifactPanel: React.FC<ArtifactPanelProps> = ({
  threadId,
  runId: initialRunId,
  className,
}) => {
  const [runs, setRuns] = useState<RunInfo[]>([])
  const [selectedRunId, setSelectedRunId] = useState<string | null>(initialRunId ?? null)
  const [files, setFiles] = useState<FileNode[]>([])
  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const [previewContent, setPreviewContent] = useState<string | null>(null)
  const [previewBlobUrl, setPreviewBlobUrl] = useState<string | null>(null)
  const [loadingRuns, setLoadingRuns] = useState(true)
  const [loadingFiles, setLoadingFiles] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadRuns = useCallback(async () => {
    if (!threadId) return
    setLoadingRuns(true)
    setError(null)
    try {
      const list = await artifactService.listRuns(threadId)
      setRuns(list)
      if (list.length && !selectedRunId) setSelectedRunId(list[0].run_id)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load runs')
    } finally {
      setLoadingRuns(false)
    }
  }, [threadId, selectedRunId])

  useEffect(() => {
    loadRuns()
  }, [loadRuns])

  useEffect(() => {
    if (initialRunId) setSelectedRunId(initialRunId)
  }, [initialRunId])

  useEffect(() => {
    if (!threadId || !selectedRunId) {
      setFiles([])
      return
    }
    setLoadingFiles(true)
    setError(null)
    artifactService
      .listRunFiles(threadId, selectedRunId)
      .then((list) => setFiles(list.map(fileInfoToNode)))
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load files'))
      .finally(() => setLoadingFiles(false))
  }, [threadId, selectedRunId])

  const handleSelectFile = useCallback(
    async (path: string) => {
      setSelectedPath(path)
      setPreviewContent(null)
      if (previewBlobUrl) {
        URL.revokeObjectURL(previewBlobUrl)
        setPreviewBlobUrl(null)
      }
      if (!threadId || !selectedRunId) return
      const node = flattenNodes(files).find((n) => n.path === path)
      if (!node || node.type === 'directory') return
      const ext = (node.extension ?? '').toLowerCase()
      const textLike = ['txt', 'md', 'json', 'py', 'js', 'ts', 'tsx', 'jsx', 'html', 'css', 'yaml', 'yml', 'sh', 'sql', 'xml'].includes(ext)
      try {
        const blob = await artifactService.downloadFile(threadId, selectedRunId, path)
        if (textLike) {
          const text = await blob.text()
          setPreviewContent(text)
        } else {
          const url = URL.createObjectURL(blob)
          setPreviewBlobUrl(url)
        }
      } catch {
        setPreviewContent('(Failed to load preview)')
      }
    },
    [threadId, selectedRunId, files, previewBlobUrl]
  )

  const handleDownload = useCallback(async () => {
    if (!selectedPath || !threadId || !selectedRunId) return
    try {
      const blob = await artifactService.downloadFile(threadId, selectedRunId, selectedPath)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = selectedPath.split('/').pop() ?? 'file'
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      setError('Download failed')
    }
  }, [threadId, selectedRunId, selectedPath])

  const selectedFile = selectedPath ? flattenNodes(files).find((n) => n.path === selectedPath) : null
  const ext = selectedFile?.extension?.toLowerCase() ?? ''

  return (
    <div className={cn('flex flex-col border rounded-lg bg-background', className)}>
      <div className="flex items-center justify-between gap-2 p-2 border-b">
        <span className="text-sm font-medium">Run artifacts</span>
        <div className="flex items-center gap-2">
          <select
            className="text-sm border rounded px-2 py-1 bg-background"
            value={selectedRunId ?? ''}
            onChange={(e) => setSelectedRunId(e.target.value || null)}
            disabled={loadingRuns}
          >
            {loadingRuns && (
              <option value="">Loading…</option>
            )}
            {!loadingRuns && runs.length === 0 && (
              <option value="">No runs</option>
            )}
            {runs.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                {r.run_id.slice(0, 8)}… ({r.file_count} files)
              </option>
            ))}
          </select>
        </div>
      </div>
      {error && (
        <div className="px-2 py-1 text-sm text-destructive">
          {error}
        </div>
      )}
      <div className="flex flex-1 min-h-0">
        <div className="w-56 border-r overflow-y-auto flex-shrink-0">
          {loadingFiles ? (
            <div className="flex items-center justify-center p-4">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
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
            <div className="flex items-center gap-2 p-2 border-b">
              <span className="text-sm truncate flex-1">{selectedPath}</span>
              <Button variant="outline" size="sm" onClick={handleDownload}>
                <Download className="h-4 w-4 mr-1" />
                Download
              </Button>
            </div>
          )}
          <div className="flex-1 overflow-auto p-2">
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
              <div className="flex flex-col items-center justify-center text-muted-foreground text-sm py-8">
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
