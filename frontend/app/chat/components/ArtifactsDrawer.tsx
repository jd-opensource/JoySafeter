'use client'

import { FolderOpen, X } from 'lucide-react'

import ArtifactPanel from '@/app/chat/components/ArtifactPanel'
import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/i18n'
import { Button } from '@/components/ui/button'

interface ArtifactsDrawerProps {
  isOpen: boolean
  onClose: () => void
  threadId: string
  fileTree?: Record<string, { action: string; size?: number; timestamp?: number }>
}

export default function ArtifactsDrawer({
  isOpen,
  onClose,
  threadId,
  fileTree,
}: ArtifactsDrawerProps) {
  const { t } = useTranslation()
  if (!isOpen) return null

  const fileCount = fileTree ? Object.keys(fileTree).length : 0

  return (
    <div className={cn('h-full overflow-hidden', 'flex flex-col bg-white')}>
      <div className="flex shrink-0 items-center justify-between border-b border-gray-100 bg-white px-4 py-3.5">
        <div className="flex min-w-0 items-center gap-3 overflow-hidden text-gray-900">
          <div className="shrink-0 rounded-lg border border-gray-50 bg-blue-50 p-1.5 text-blue-600 shadow-sm">
            <FolderOpen size={14} />
          </div>
          <h3 className="truncate text-sm font-bold leading-tight">
            {t('chat.artifacts', { defaultValue: 'Artifacts' })}
            {fileCount > 0 && <span className="ml-1 font-normal text-gray-400">({fileCount})</span>}
          </h3>
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={onClose}
          className="h-7 w-7 text-gray-300 hover:bg-gray-100 hover:text-gray-600"
          aria-label={t('chat.closeArtifacts', { defaultValue: 'Close artifacts' })}
        >
          <X size={16} />
        </Button>
      </div>
      <ArtifactPanel threadId={threadId} fileTree={fileTree} className="min-h-0 flex-1" />
    </div>
  )
}
