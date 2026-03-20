'use client'

import React, { useState } from 'react'
import { X, FolderTree, Wrench } from 'lucide-react'

import { useChatState } from '../ChatProvider'

import FileTreePreview from './FileTreePreview'

export default function PreviewPanel() {
  const { state, dispatch } = useChatState()
  const { preview, ui, threadId } = state
  const [activeTab, setActiveTab] = useState<'files' | 'tool'>('files')

  const hasFiles = Object.keys(preview.fileTree).length > 0
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
              Files ({Object.keys(preview.fileTree).length})
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
          <FileTreePreview threadId={threadId} fileTree={preview.fileTree} />
        )}
        {activeTab === 'tool' && ui.selectedTool && (
          <div className="overflow-auto p-4">
            <h3 className="mb-2 text-sm font-medium">{ui.selectedTool.name}</h3>
            <div className="mb-3">
              <p className="mb-1 text-xs text-gray-500">Input</p>
              <pre className="rounded bg-gray-50 p-2 text-xs whitespace-pre-wrap">
                {JSON.stringify(ui.selectedTool.args, null, 2)}
              </pre>
            </div>
            {ui.selectedTool.result && (
              <div>
                <p className="mb-1 text-xs text-gray-500">Output</p>
                <pre className="rounded bg-gray-50 p-2 text-xs whitespace-pre-wrap">
                  {typeof ui.selectedTool.result === 'string'
                    ? ui.selectedTool.result
                    : JSON.stringify(ui.selectedTool.result, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
