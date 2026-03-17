'use client'

import { FolderOpen, Maximize2 } from 'lucide-react'
import React from 'react'

import { cn } from '@/lib/core/utils/cn'
import { useTranslation } from '@/lib/i18n'

interface CompactArtifactStatusProps {
  onClick: () => void
}

const CompactArtifactStatus: React.FC<CompactArtifactStatusProps> = ({ onClick }) => {
  const { t } = useTranslation()

  return (
    <div
      onClick={onClick}
      className={cn(
        'flex items-center justify-between px-4 py-3 rounded-xl border cursor-pointer transition-all duration-200 shadow-sm hover:shadow-md',
        'border-gray-200 bg-white hover:bg-gray-50'
      )}
    >
      {/* Left: Icon + Label */}
      <div className="flex items-center gap-3">
        <div className="flex-shrink-0 p-1 rounded-md bg-blue-50 text-blue-600">
          <FolderOpen size={16} />
        </div>
        <span className="font-medium text-base text-gray-800">
          {t('chat.artifacts', { defaultValue: 'Artifacts' })}
        </span>
      </div>

      {/* Right: Badge + Expand Icon */}
      <div className="flex items-center gap-3">
        <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-blue-100 text-blue-700 border border-blue-300">
          {t('chat.artifactsReady', { defaultValue: 'Ready' })}
        </span>
        <Maximize2 size={16} className="text-gray-400 flex-shrink-0" />
      </div>
    </div>
  )
}

export default CompactArtifactStatus
