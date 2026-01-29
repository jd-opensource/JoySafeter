'use client'

import {
  Zap,
  Box,
  Terminal,
  Cpu,
  BrainCircuit,
  Wrench,
  Clock,
  CheckCircle2,
  Activity,
  Code2,
  Eye,
  CheckSquare,
  ListTodo,
  AlertTriangle,
} from 'lucide-react'
import React from 'react'

import { cn } from '@/lib/core/utils/cn'
import { useTranslation } from '@/lib/i18n'
import type { ExecutionStep } from '@/types'

import { ThoughtContent } from './ThoughtContent'
import { ToolCallCard } from './ToolCallCard'

interface ExecutionStepCardProps {
  step: ExecutionStep
  isSelected?: boolean
  onClick?: () => void
  isNodeStart?: boolean
  showDetails?: boolean
}

export const ExecutionStepCard: React.FC<ExecutionStepCardProps> = ({
  step,
  isSelected = false,
  onClick,
  isNodeStart = false,
  showDetails = false,
}) => {
  const { t } = useTranslation()

  const getIcon = () => {
    if (step.status === 'running')
      return <Zap size={14} className="text-cyan-600 fill-cyan-100 animate-pulse" />
    if (step.status === 'error') return <Activity size={14} className="text-red-500" />

    switch (step.stepType) {
      case 'node_lifecycle':
        return <Cpu size={14} className="text-blue-500" />
      case 'agent_thought':
        return <BrainCircuit size={14} className="text-purple-500" />
      case 'tool_execution':
        return <Wrench size={14} className="text-amber-500" />
      // CodeAgent step types
      case 'code_agent_thought':
        return <BrainCircuit size={14} className="text-indigo-500" />
      case 'code_agent_code':
        return <Code2 size={14} className="text-blue-600" />
      case 'code_agent_observation':
        return <Eye size={14} className="text-teal-500" />
      case 'code_agent_final_answer':
        return <CheckSquare size={14} className="text-green-600" />
      case 'code_agent_planning':
        return <ListTodo size={14} className="text-orange-500" />
      case 'code_agent_error':
        return <AlertTriangle size={14} className="text-red-500" />
      default:
        return <Terminal size={14} className="text-gray-500" />
    }
  }

  const getStatusColor = (status: string) => {
    if (status === 'running') return 'border-cyan-500 ring-2 ring-cyan-100 bg-white'
    if (status === 'success') return 'border-emerald-200 bg-emerald-50'
    if (status === 'error') return 'border-red-200 bg-red-50'
    return 'border-gray-200 bg-white'
  }

  // Node lifecycle (parent node)
  if (isNodeStart) {
    return (
      <div
        onClick={onClick}
        className={cn(
          'relative flex items-center gap-3 py-3 px-4 border-b border-gray-100 cursor-pointer transition-all duration-200 group',
          isSelected ? 'bg-blue-50/60' : 'bg-white hover:bg-gray-50'
        )}
      >
        {isSelected && <div className="absolute left-0 top-0 bottom-0 w-[3px] bg-blue-500" />}

        <div
          className={cn(
            'w-7 h-7 rounded-lg flex items-center justify-center shrink-0 border transition-all shadow-sm',
            getStatusColor(step.status)
          )}
        >
          {step.status === 'running' ? (
            <Zap size={14} className="text-cyan-600" />
          ) : (
            <Box
              size={14}
              className={step.status === 'success' ? 'text-emerald-600' : 'text-gray-400'}
            />
          )}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between">
            <span
              className={cn(
                'text-[11px] font-bold uppercase tracking-wider truncate',
                step.status === 'running' ? 'text-cyan-700' : 'text-gray-700'
              )}
            >
              {step.nodeLabel}
            </span>
            {step.duration && (
              <span className="text-[9px] text-gray-400 font-mono flex items-center gap-1">
                <Clock size={8} /> {step.duration}ms
              </span>
            )}
          </div>
          {step.status === 'running' && (
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className="w-1.5 h-1.5 rounded-full bg-cyan-500 animate-pulse" />
              <span className="text-[9px] text-cyan-600 font-medium">
                {t('workspace.processing', { defaultValue: 'Processing...' })}
              </span>
            </div>
          )}
        </div>
      </div>
    )
  }

  // Child steps (Thoughts, Tools, System logs)
  return (
    <div
      onClick={onClick}
      className={cn(
        'relative flex gap-2 py-2 px-4 pl-10 cursor-pointer transition-colors border-l-2 border-transparent group',
        isSelected ? 'bg-blue-50/40 border-l-blue-400' : 'hover:bg-gray-50 border-l-gray-100'
      )}
    >
      {/* Circuit Line Connector */}
      <div className="absolute left-[27px] top-0 bottom-0 w-[1px] bg-gray-200 group-hover:bg-gray-300 transition-colors" />
      <div className="absolute left-[27px] top-1/2 -translate-y-1/2 w-2 h-[1px] bg-gray-200 group-hover:bg-gray-300" />

      <div
        className={cn(
          'relative z-10 w-5 h-5 rounded-full flex items-center justify-center shrink-0 border bg-white transition-colors shadow-sm',
          step.status === 'running'
            ? 'border-cyan-400 ring-2 ring-cyan-100'
            : 'border-gray-200 group-hover:border-gray-300'
        )}
      >
        {getIcon()}
      </div>

      <div className="flex-1 min-w-0 flex flex-col gap-0.5">
        <div className="flex items-center justify-between">
          <span
            className={cn(
              'text-[11px] font-bold truncate',
              step.stepType === 'agent_thought'
                ? 'text-purple-600'
                : step.stepType === 'tool_execution'
                  ? 'text-amber-600'
                  : step.stepType === 'code_agent_thought'
                    ? 'text-indigo-600'
                    : step.stepType === 'code_agent_code'
                      ? 'text-blue-600'
                      : step.stepType === 'code_agent_observation'
                        ? 'text-teal-600'
                        : step.stepType === 'code_agent_final_answer'
                          ? 'text-green-600'
                          : step.stepType === 'code_agent_planning'
                            ? 'text-orange-600'
                            : step.stepType === 'code_agent_error'
                              ? 'text-red-600'
                              : 'text-gray-600'
            )}
          >
            {step.title}
          </span>
          {step.status === 'success' && <CheckCircle2 size={10} className="text-emerald-500" />}
        </div>

        {/* Content Preview / Details */}
        {showDetails ? (
          // Show full details when expanded
          <div className="mt-2 space-y-2">
            {step.stepType === 'agent_thought' && (
              <ThoughtContent step={step} showHeader={false} />
            )}
            {step.stepType === 'tool_execution' && (
              <ToolCallCard step={step} defaultCollapsed={false} showHeader={false} />
            )}
            {step.stepType === 'system_log' && step.content && (
              <div className="text-[10px] text-gray-500 font-mono leading-relaxed bg-gray-50 border border-gray-200 rounded p-2">
                {step.content}
              </div>
            )}
            {/* CodeAgent step types - full details */}
            {step.stepType === 'code_agent_thought' && step.content && (
              <div className="text-[10px] text-indigo-700 font-mono leading-relaxed bg-indigo-50 border border-indigo-200 rounded p-2 whitespace-pre-wrap">
                {step.content}
              </div>
            )}
            {step.stepType === 'code_agent_code' && step.content && (
              <div className="text-[10px] text-blue-700 font-mono leading-relaxed bg-blue-50 border border-blue-200 rounded p-2 whitespace-pre-wrap overflow-x-auto">
                <pre className="text-xs">{step.content}</pre>
              </div>
            )}
            {step.stepType === 'code_agent_observation' && step.content && (
              <div className={cn(
                "text-[10px] font-mono leading-relaxed border rounded p-2 whitespace-pre-wrap",
                step.data?.has_error 
                  ? "text-red-700 bg-red-50 border-red-200" 
                  : "text-teal-700 bg-teal-50 border-teal-200"
              )}>
                {step.content}
              </div>
            )}
            {step.stepType === 'code_agent_final_answer' && step.content && (
              <div className="text-[10px] text-green-700 font-mono leading-relaxed bg-green-50 border border-green-200 rounded p-2 whitespace-pre-wrap">
                <div className="font-bold text-[11px] mb-1 text-green-800">✓ {t('execution.finalAnswer', { defaultValue: '最终答案' })}</div>
                {step.content}
              </div>
            )}
            {step.stepType === 'code_agent_planning' && step.content && (
              <div className="text-[10px] text-orange-700 font-mono leading-relaxed bg-orange-50 border border-orange-200 rounded p-2 whitespace-pre-wrap">
                <div className="font-bold text-[11px] mb-1 text-orange-800">
                  {step.data?.is_update ? t('execution.planUpdate', { defaultValue: '📝 计划更新' }) : t('execution.executionPlan', { defaultValue: '📋 执行计划' })}
                </div>
                {step.content}
              </div>
            )}
            {step.stepType === 'code_agent_error' && step.content && (
              <div className="text-[10px] text-red-700 font-mono leading-relaxed bg-red-50 border border-red-200 rounded p-2 whitespace-pre-wrap">
                <div className="font-bold text-[11px] mb-1 text-red-800">⚠ {t('execution.error', { defaultValue: '错误' })}</div>
                {step.content}
              </div>
            )}
          </div>
        ) : (
          // Show preview when collapsed
          <>
            {step.stepType === 'agent_thought' && step.content && (
              <p className="text-[10px] text-gray-500 line-clamp-2 font-mono leading-relaxed">
                {step.content}
              </p>
            )}
            {step.stepType === 'tool_execution' && step.data && (
              <div className="flex flex-col gap-0.5">
                <p className="text-[10px] text-gray-400 font-mono truncate">
                  <span className="text-amber-600/70 font-semibold">
                    {t('workspace.in', { defaultValue: 'IN' })}:
                  </span>{' '}
                  {JSON.stringify(step.data.request || step.data).slice(0, 40)}...
                </p>
                {step.data.response && (
                  <p className="text-[10px] text-gray-400 font-mono truncate">
                    <span className="text-emerald-600/70 font-semibold">
                      {t('workspace.out', { defaultValue: 'OUT' })}:
                    </span>{' '}
                    {JSON.stringify(step.data.response).slice(0, 40)}...
                  </p>
                )}
              </div>
            )}
            {step.stepType === 'system_log' && step.content && (
              <p className="text-[10px] text-gray-500 line-clamp-1 font-mono truncate">
                {step.content}
              </p>
            )}
            {/* CodeAgent step types - preview */}
            {step.stepType === 'code_agent_thought' && step.content && (
              <p className="text-[10px] text-indigo-500 line-clamp-2 font-mono leading-relaxed">
                {step.content}
              </p>
            )}
            {step.stepType === 'code_agent_code' && step.content && (
              <p className="text-[10px] text-blue-500 line-clamp-2 font-mono leading-relaxed">
                {step.content.slice(0, 100)}...
              </p>
            )}
            {step.stepType === 'code_agent_observation' && step.content && (
              <p className={cn(
                "text-[10px] line-clamp-2 font-mono leading-relaxed",
                step.data?.has_error ? "text-red-500" : "text-teal-500"
              )}>
                {step.content}
              </p>
            )}
            {step.stepType === 'code_agent_final_answer' && step.content && (
              <p className="text-[10px] text-green-600 line-clamp-2 font-mono leading-relaxed">
                ✓ {step.content}
              </p>
            )}
            {step.stepType === 'code_agent_planning' && step.content && (
              <p className="text-[10px] text-orange-500 line-clamp-2 font-mono leading-relaxed">
                {step.content}
              </p>
            )}
            {step.stepType === 'code_agent_error' && step.content && (
              <p className="text-[10px] text-red-500 line-clamp-2 font-mono leading-relaxed">
                ⚠ {step.content}
              </p>
            )}
          </>
        )}
      </div>
    </div>
  )
}

