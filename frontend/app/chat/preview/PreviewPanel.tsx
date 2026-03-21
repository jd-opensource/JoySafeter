'use client'

import React, { useState, useMemo } from 'react'
import { X, FolderTree, Wrench } from 'lucide-react'

import { useChatState } from '../ChatProvider'
import { ToolCallDetail } from '../shared/ToolCallDisplay'

import ArtifactPanel from '../components/ArtifactPanel'

export default function PreviewPanel() {
  const { state, dispatch } = useChatState()
  const { preview, ui, threadId } = state
  const [activeTab, setActiveTab] = useState<'files' | 'tool'>('files')

  const fileKeys = useMemo(() => Object.keys(preview.fileTree), [preview.fileTree])
  const hasFiles = fileKeys.length > 0
  const hasTool = !!ui.selectedTool

  return (
    <div className="flex h-full flex-col bg-white">
      {/* Header with tabs */}
      <div className="flex items-center justify-between border-b px-3 py-2">
        <div className="flex gap-1">
          {hasFiles && (
            <button
              onClick={() => setActiveTab('files')}
              className={`flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm ${
                activeTab === 'files'
                  ? 'bg-gray-100 font-medium'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              <FolderTree size={14} />
              Files ({fileKeys.length})
            </button>
          )}
          {hasTool && (
            <button
              onClick={() => setActiveTab('tool')}
              className={`flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm ${
                activeTab === 'tool'
                  ? 'bg-gray-100 font-medium'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              <Wrench size={14} />
              {ui.selectedTool?.name}
            </button>
          )}
        </div>
        <button
          onClick={() => dispatch({ type: 'HIDE_PREVIEW' })}
          className="rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
        >
          <X size={16} />
        </button>
      </div>

      {/* Content */}
      <div className="min-h-0 flex-1 overflow-hidden">
        {activeTab === 'files' && threadId && (
          <ArtifactPanel threadId={threadId} fileTree={preview.fileTree} />
        )}
        {activeTab === 'tool' && ui.selectedTool && (
          <div className="overflow-auto">
            <ToolCallDetail
              name={ui.selectedTool.name}
              args={ui.selectedTool.args}
              status={ui.selectedTool.status}
              result={ui.selectedTool.result}
              startTime={ui.selectedTool.startTime}
              endTime={ui.selectedTool.endTime}
            />
          </div>
        )}
      </div>
    </div>
  )
}
