'use client'

import { CheckCircle2, Loader2, AlertCircle, Maximize2 } from 'lucide-react'
import React from 'react'

import { cn } from '@/lib/core/utils/cn'

import { ToolCall } from '../types'

interface CompactToolStatusProps {
  toolCalls: ToolCall[]
  onClick: () => void
}

const CompactToolStatus: React.FC<CompactToolStatusProps> = ({ toolCalls, onClick }) => {
  // Get the latest tool call status
  const latestTool = toolCalls[toolCalls.length - 1]

  if (!latestTool) return null

  const getStatusIcon = (status?: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle2 size={18} className="text-green-500" />
      case 'failed':
        return <AlertCircle size={18} className="text-red-500" />
      case 'running':
        return <Loader2 size={18} className="text-blue-500 animate-spin" />
      default:
        return <Loader2 size={18} className="text-gray-400 animate-spin" />
    }
  }

  const getStatusText = (status?: string) => {
    switch (status) {
      case 'completed':
        return 'Success'
      case 'failed':
        return 'Failed'
      case 'running':
        return 'Running'
      default:
        return 'Initializing'
    }
  }

  const getStatusColor = (status?: string) => {
    switch (status) {
      case 'completed':
        return 'border-gray-200 bg-white hover:bg-gray-50'
      case 'failed':
        return 'border-gray-200 bg-white hover:bg-gray-50'
      case 'running':
        return 'border-gray-200 bg-white hover:bg-gray-50'
      default:
        return 'border-gray-200 bg-white hover:bg-gray-50'
    }
  }

  const toolName = latestTool.name
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (l) => l.toUpperCase())

  return (
    <div
      onClick={onClick}
      className={cn(
        'flex items-center justify-between px-4 py-3 rounded-xl border cursor-pointer transition-all duration-200 shadow-sm hover:shadow-md',
        getStatusColor(latestTool.status)
      )}
    >
      {/* Left: Icon + Tool Name */}
      <div className="flex items-center gap-3">
        <div className="flex-shrink-0">
          {getStatusIcon(latestTool.status)}
        </div>
        <span className="font-medium text-base text-gray-800">
          {toolName}
        </span>
      </div>

      {/* Right: Status Badge + Expand Icon */}
      <div className="flex items-center gap-3">
        {latestTool.status === 'completed' && (
          <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-green-100 text-green-700 border border-green-300">
            {getStatusText(latestTool.status)}
          </span>
        )}
        <Maximize2 size={16} className="text-gray-400 flex-shrink-0" />
      </div>
    </div>
  )
}

export default CompactToolStatus
