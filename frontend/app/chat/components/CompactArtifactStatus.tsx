'use client'

import { FolderOpen, Maximize2 } from 'lucide-react'

import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/i18n'

interface CompactArtifactStatusProps {
  onClick: () => void
}

export default function CompactArtifactStatus({ onClick }: CompactArtifactStatusProps) {
  const { t } = useTranslation()

  return (
    <div
      onClick={onClick}
      className={cn(
        'flex cursor-pointer items-center justify-between rounded-xl border px-4 py-3 shadow-sm transition-all duration-200 hover:shadow-md',
        'border-gray-200 bg-white hover:bg-gray-50',
      )}
    >
      {/* Left: Icon + Label */}
      <div className="flex items-center gap-3">
        <div className="flex-shrink-0 rounded-md bg-blue-50 p-1 text-blue-600">
          <FolderOpen size={16} />
        </div>
        <span className="text-base font-medium text-gray-800">
          {t('chat.artifacts', { defaultValue: 'Artifacts' })}
        </span>
      </div>

      {/* Right: Badge + Expand Icon */}
      <div className="flex items-center gap-3">
        <span className="inline-flex items-center rounded-full border border-blue-300 bg-blue-100 px-3 py-1 text-xs font-semibold text-blue-700">
          {t('chat.artifactsReady', { defaultValue: 'Ready' })}
        </span>
        <Maximize2 size={16} className="flex-shrink-0 text-gray-400" />
      </div>
    </div>
  )
}
