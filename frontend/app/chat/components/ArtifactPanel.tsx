'use client'

import { Download, FolderOpen, Loader2 } from 'lucide-react'
import React, { useCallback, useEffect, useState } from 'react'

import CodeViewer from '@/app/chat/components/CodeViewer'
import FileBrowser, { FileNode } from '@/app/chat/components/FileBrowser'
import { Button } from '@/components/ui/button'
import {
  artifactService,
  type FileInfo,
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
  runId,
  className,
}) => {
  const [files, setFiles] = useState<FileNode[]>([])
  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const [previewContent, setPreviewContent] = useState<string | null>(null)
  const [previewBlobUrl, setPreviewBlobUrl] = useState<string | null>(null)
  const [loadingFiles, setLoadingFiles] = useState(false)
  const [error, setError] = useState<string | null>(null)

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
      if (previewBlobUrl) {
        URL.revokeObjectURL(previewBlobUrl)
        setPreviewBlobUrl(null)
      }
      if (!threadId || !runId) return
      const node = flattenNodes(files).find((n) => n.path === path)
      if (!node || node.type === 'directory') return
      const ext = (node.extension ?? '').toLowerCase()
      const textLike = ['txt', 'md', 'json', 'py', 'js', 'ts', 'tsx', 'jsx', 'html', 'css', 'yaml', 'yml', 'sh', 'sql', 'xml'].includes(ext)
      try {
        const blob = await artifactService.downloadFile(threadId, runId, path)
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
    [threadId, runId, files, previewBlobUrl]
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

  const selectedFile = selectedPath ? flattenNodes(files).find((n) => n.path === selectedPath) : null
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
