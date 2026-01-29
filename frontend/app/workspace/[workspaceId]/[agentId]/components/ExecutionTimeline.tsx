'use client'

import { PlayCircle } from 'lucide-react'
import React, { useEffect, useRef, useCallback, useMemo } from 'react'

import { useTranslation } from '@/lib/i18n'
import type { ExecutionStep } from '@/types'

import { ExecutionStepCard } from './ExecutionStepCard'

interface ExecutionTimelineProps {
  steps: ExecutionStep[]
  selectedStepId: string | null
  onStepSelect: (stepId: string) => void
  isExecuting: boolean
}

export const ExecutionTimeline: React.FC<ExecutionTimelineProps> = ({
  steps,
  selectedStepId,
  onStepSelect,
  isExecuting,
}) => {
  const { t } = useTranslation()
  const parentRef = useRef<HTMLDivElement>(null)
  const shouldAutoScrollRef = useRef(true)

  // Group steps by node (for visual hierarchy)
  const groupedSteps = useMemo(() => {
    const groups: Array<{ nodeId: string; nodeLabel: string; steps: ExecutionStep[] }> = []
    let currentGroup: { nodeId: string; nodeLabel: string; steps: ExecutionStep[] } | null = null

    steps.forEach((step) => {
      if (step.stepType === 'node_lifecycle') {
        // Start a new group
        if (currentGroup) {
          groups.push(currentGroup)
        }
        currentGroup = {
          nodeId: step.nodeId,
          nodeLabel: step.nodeLabel,
          steps: [step],
        }
      } else if (currentGroup) {
        // Add to current group
        currentGroup.steps.push(step)
      } else {
        // Orphan step (shouldn't happen, but handle it)
        groups.push({
          nodeId: step.nodeId,
          nodeLabel: step.nodeLabel,
          steps: [step],
        })
      }
    })

    if (currentGroup) {
      groups.push(currentGroup)
    }

    return groups
  }, [steps])

  // Auto-scroll when new steps are added during execution
  useEffect(() => {
    if (isExecuting && steps.length > 0 && shouldAutoScrollRef.current && parentRef.current) {
      parentRef.current.scrollTop = parentRef.current.scrollHeight
    }
  }, [steps.length, isExecuting])

  // Handle manual scroll - disable auto-scroll if user scrolls up
  const handleScroll = useCallback(() => {
    if (!parentRef.current) return

    const { scrollTop, scrollHeight, clientHeight } = parentRef.current
    const isNearBottom = scrollHeight - scrollTop - clientHeight < 100

    shouldAutoScrollRef.current = isNearBottom
  }, [])

  if (steps.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-gray-400 gap-3 opacity-60">
        <div className="w-12 h-12 rounded-full border border-gray-100 bg-gray-50 flex items-center justify-center">
          <PlayCircle size={20} strokeWidth={1} />
        </div>
        <span className="text-xs font-medium font-mono">
          {t('workspace.readyToExecute', { defaultValue: 'Ready to execute' })}
        </span>
      </div>
    )
  }

  return (
    <div
      ref={parentRef}
      onScroll={handleScroll}
      className="flex-1 overflow-y-auto custom-scrollbar bg-white"
    >
      <div className="pb-4">
        {groupedSteps.map((group, groupIndex) => (
          <div key={`group-${groupIndex}`}>
            {group.steps.map((step) => {
              const isNodeStart = step.stepType === 'node_lifecycle'
              const isSelected = selectedStepId === step.id

              return (
                <ExecutionStepCard
                  key={step.id}
                  step={step}
                  isSelected={isSelected}
                  onClick={() => onStepSelect(step.id)}
                  isNodeStart={isNodeStart}
                />
              )
            })}
          </div>
        ))}
        {isExecuting && (
          <div className="px-4 py-3 flex items-center gap-2">
            <div className="w-1 h-3 bg-cyan-400 animate-pulse" />
            <span className="text-[9px] text-cyan-600 font-mono animate-pulse">
              {t('workspace.waitingForNextStep', { defaultValue: 'Waiting for next step...' })}
            </span>
          </div>
        )}
      </div>
    </div>
  )
}
