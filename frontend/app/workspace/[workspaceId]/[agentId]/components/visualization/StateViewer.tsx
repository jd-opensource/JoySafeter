'use client'

import { ChevronDown, ChevronRight } from 'lucide-react'
import React from 'react'

import { useTranslation } from '@/lib/i18n'

/**
 * GraphState 类型定义（与后端 GraphState 对应）
 */
export interface GraphState {
  // Business State
  context?: Record<string, any>
  messages?: any[]
  
  // Execution State
  current_node?: string
  route_decision?: string
  route_reason?: string
  route_history?: string[]
  loop_count?: number
  loop_condition_met?: boolean
  max_loop_iterations?: number
  parallel_mode?: boolean
  task_states?: Record<string, TaskState>
  loop_states?: Record<string, any>
  task_results?: Array<{
    status: 'success' | 'error'
    error_msg?: string
    result?: any
    task_id: string
  }>
  parallel_results?: any[]
  loop_body_trace?: string[]
}

export interface TaskState {
  status: 'pending' | 'running' | 'completed' | 'error'
  result?: any
  error_msg?: string
}

interface StateViewerProps {
  state: GraphState
  nodeId?: string
  compact?: boolean
}

/**
 * 状态查看器组件
 * 显示当前节点的状态快照，包括业务数据和执行元数据
 */
export const StateViewer: React.FC<StateViewerProps> = ({
  state,
  nodeId,
  compact = false
}) => {
  const { t } = useTranslation()
  const [expandedSections, setExpandedSections] = React.useState<Set<string>>(
    new Set(['business', 'execution'])
  )

  const toggleSection = (section: string) => {
    setExpandedSections((prev) => {
      const next = new Set(prev)
      if (next.has(section)) {
        next.delete(section)
      } else {
        next.add(section)
      }
      return next
    })
  }

  const formatValue = (value: any): string => {
    if (value === null || value === undefined) return 'null'
    if (typeof value === 'object') {
      try {
        return JSON.stringify(value, null, 2)
      } catch {
        return String(value)
      }
    }
    return String(value)
  }

  if (compact) {
    return (
      <div className="state-viewer-compact text-xs">
        <div className="flex items-center gap-2 mb-2">
          <span className="font-semibold text-gray-700">{t('state.snapshot', { defaultValue: '状态快照' })}</span>
          {nodeId && (
            <span className="text-gray-500">{t('state.node', { defaultValue: '节点:' })} {nodeId}</span>
          )}
        </div>
        <div className="grid grid-cols-2 gap-2">
          {state.current_node && (
            <div>
              <span className="text-gray-500">{t('state.currentNode', { defaultValue: '当前节点:' })}</span>{' '}
              <span className="font-mono">{state.current_node}</span>
            </div>
          )}
          {state.loop_count !== undefined && (
            <div>
              <span className="text-gray-500">{t('state.loopCount', { defaultValue: '循环计数:' })}</span>{' '}
              <span className="font-mono">{state.loop_count}</span>
            </div>
          )}
          {state.route_decision && (
            <div>
              <span className="text-gray-500">{t('state.routeDecision', { defaultValue: '路由决策:' })}</span>{' '}
              <span className="font-mono">{state.route_decision}</span>
            </div>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="state-viewer border border-gray-200 rounded-lg bg-white">
      <div className="p-3 border-b border-gray-200 bg-gray-50">
        <h3 className="text-sm font-semibold text-gray-800">{t('state.currentState', { defaultValue: '当前状态' })}</h3>
        {nodeId && (
          <p className="text-xs text-gray-500 mt-1">{t('state.node', { defaultValue: '节点:' })} {nodeId}</p>
        )}
      </div>

      {/* 业务状态 */}
      <div className="border-b border-gray-200">
        <button
          onClick={() => toggleSection('business')}
          className="w-full px-3 py-2 flex items-center justify-between hover:bg-gray-50 transition-colors"
        >
          <span className="text-sm font-medium text-gray-700">{t('state.businessData', { defaultValue: '业务数据' })}</span>
          {expandedSections.has('business') ? (
            <ChevronDown size={16} className="text-gray-500" />
          ) : (
            <ChevronRight size={16} className="text-gray-500" />
          )}
        </button>
        {expandedSections.has('business') && (
          <div className="px-3 pb-3">
            {state.context && Object.keys(state.context).length > 0 ? (
              <pre className="text-xs bg-gray-50 p-2 rounded border border-gray-200 overflow-x-auto">
                {formatValue(state.context)}
              </pre>
            ) : (
              <p className="text-xs text-gray-400 italic">{t('state.noBusinessData', { defaultValue: '无业务数据' })}</p>
            )}
          </div>
        )}
      </div>

      {/* 执行状态 */}
      <div>
        <button
          onClick={() => toggleSection('execution')}
          className="w-full px-3 py-2 flex items-center justify-between hover:bg-gray-50 transition-colors"
        >
          <span className="text-sm font-medium text-gray-700">{t('state.executionMetadata', { defaultValue: '执行元数据' })}</span>
          {expandedSections.has('execution') ? (
            <ChevronDown size={16} className="text-gray-500" />
          ) : (
            <ChevronRight size={16} className="text-gray-500" />
          )}
        </button>
        {expandedSections.has('execution') && (
          <div className="px-3 pb-3 space-y-2">
            {state.current_node && (
              <div className="text-xs">
                <span className="text-gray-500">{t('state.currentNode', { defaultValue: '当前节点:' })}</span>{' '}
                <span className="font-mono font-medium">{state.current_node}</span>
              </div>
            )}
            {state.route_decision && (
              <div className="text-xs">
                <span className="text-gray-500">{t('state.routeDecision', { defaultValue: '路由决策:' })}</span>{' '}
                <span className="font-mono font-medium text-blue-600">{state.route_decision}</span>
              </div>
            )}
            {state.route_reason && (
              <div className="text-xs">
                <span className="text-gray-500">{t('state.routeReason', { defaultValue: '路由原因:' })}</span>{' '}
                <span className="text-gray-700">{state.route_reason}</span>
              </div>
            )}
            {state.route_history && state.route_history.length > 0 && (
              <div className="text-xs">
                <span className="text-gray-500">{t('state.routeHistory', { defaultValue: '路由历史:' })}</span>{' '}
                <span className="font-mono text-gray-600">
                  {state.route_history.join(' → ')}
                </span>
              </div>
            )}
            {state.loop_count !== undefined && (
              <div className="text-xs">
                <span className="text-gray-500">{t('state.loopCount', { defaultValue: '循环计数:' })}</span>{' '}
                <span className="font-mono font-medium">
                  {state.loop_count} / {state.max_loop_iterations || '∞'}
                </span>
              </div>
            )}
            {state.loop_condition_met !== undefined && (
              <div className="text-xs">
                <span className="text-gray-500">{t('state.loopCondition', { defaultValue: '循环条件:' })}</span>{' '}
                <span className={state.loop_condition_met ? 'text-green-600' : 'text-red-600'}>
                  {state.loop_condition_met ? t('state.conditionMet', { defaultValue: '✓ 满足' }) : t('state.conditionNotMet', { defaultValue: '✗ 不满足' })}
                </span>
              </div>
            )}
            {state.parallel_mode && (
              <div className="text-xs">
                <span className="text-gray-500">{t('state.parallelMode', { defaultValue: '并行模式:' })}</span>{' '}
                <span className="font-medium text-purple-600">启用</span>
              </div>
            )}
            {state.task_states && Object.keys(state.task_states).length > 0 && (
              <div className="text-xs">
                <span className="text-gray-500">{t('state.taskCount', { defaultValue: '任务数量:' })}</span>{' '}
                <span className="font-mono">
                  {Object.keys(state.task_states).length}
                </span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

