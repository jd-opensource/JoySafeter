'use client'

import { ChevronLeft, ChevronRight, List } from 'lucide-react'
import React from 'react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/core/utils/cn'

interface ToolNavigationProps {
  currentIndex: number
  totalTools: number
  onPrev: () => void
  onNext: () => void
  onSelect: (index: number) => void
  toolNames: string[]
}

const ToolNavigation: React.FC<ToolNavigationProps> = ({
  currentIndex,
  totalTools,
  onPrev,
  onNext,
  onSelect,
  toolNames,
}) => {
  if (totalTools === 0) return null

  const currentToolName = toolNames[currentIndex] || 'Tool'

  return (
    <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-200 bg-gray-50">
      {/* Navigation Buttons */}
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="sm"
          onClick={onPrev}
          disabled={totalTools <= 1}
          className="h-8 w-8 p-0"
          title="Previous tool (Cmd+[)"
        >
          <ChevronLeft size={16} />
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={onNext}
          disabled={totalTools <= 1}
          className="h-8 w-8 p-0"
          title="Next tool (Cmd+])"
        >
          <ChevronRight size={16} />
        </Button>
      </div>

      {/* Tool Indicator */}
      <div className="flex-1 flex items-center justify-center">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              className={cn(
                'h-8 px-3 gap-2 font-mono text-sm',
                'hover:bg-gray-200 transition-colors'
              )}
            >
              <List size={14} className="text-gray-500" />
              <span className="text-gray-700">
                Tool <span className="font-semibold">{currentIndex + 1}</span> of {totalTools}
              </span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="center" className="w-48 max-h-64 overflow-y-auto">
            {toolNames.map((name, index) => (
              <DropdownMenuItem
                key={index}
                onClick={() => onSelect(index)}
                className={cn(
                  'font-mono text-sm cursor-pointer',
                  index === currentIndex && 'bg-gray-100'
                )}
              >
                <span className="flex-1 truncate">
                  {index + 1}. {name}
                </span>
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {/* Current Tool Name */}
      <div className="w-24 text-right">
        <span className="text-xs text-gray-500 truncate block" title={currentToolName}>
          {currentToolName}
        </span>
      </div>
    </div>
  )
}

export default ToolNavigation
