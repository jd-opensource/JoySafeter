'use client'

import { CheckCircle2, XCircle, Clock, Loader2 } from 'lucide-react'
import React from 'react'

import { useTranslation } from '@/lib/i18n'

import type { TaskState } from './StateViewer'

interface ParallelExecutionViewProps {
  taskStates: Record<string, TaskState>
  showResults?: boolean
}

/**
 * 并行任务执行可视化组件
 * 显示并行任务列表、执行状态和结果
 */
export const ParallelExecutionView: React.FC<ParallelExecutionViewProps> = ({
  taskStates,
  showResults = true
}) => {
  const { t } = useTranslation()
  const tasks = Object.entries(taskStates)
  const statusCounts = tasks.reduce((acc, [, task]) => {
    acc[task.status] = (acc[task.status] || 0) + 1
    return acc
  }, {} as Record<string, number>)

  const getStatusIcon = (status: TaskState['status']) => {
    switch (status) {
      case 'completed':
        return <CheckCircle2 size={14} className="text-green-600" />
      case 'error':
        return <XCircle size={14} className="text-red-600" />
      case 'running':
        return <Loader2 size={14} className="text-blue-600 animate-spin" />
      case 'pending':
        return <Clock size={14} className="text-gray-400" />
      default:
        return null
    }
  }

  const getStatusColor = (status: TaskState['status']) => {
    switch (status) {
      case 'completed':
        return 'bg-green-50 border-green-200'
      case 'error':
        return 'bg-red-50 border-red-200'
      case 'running':
        return 'bg-blue-50 border-blue-200'
      case 'pending':
        return 'bg-gray-50 border-gray-200'
      default:
        return 'bg-white border-gray-200'
    }
  }

  const completedCount = statusCounts.completed || 0
  const totalCount = tasks.length
  const progress = totalCount > 0 ? (completedCount / totalCount) * 100 : 0

  return (
    <div className="parallel-execution border border-purple-200 rounded-lg bg-purple-50/50">
      {/* Header */}
      <div className="px-3 py-2 bg-purple-100 border-b border-purple-200">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-semibold text-purple-900">{t('workspace.parallelExecution')}</h3>
          <div className="text-xs text-purple-700">
            {completedCount} / {totalCount} {t('workspace.completed')}
          </div>
        </div>
        {/* 进度条 */}
        <div className="w-full bg-gray-200 rounded-full h-1.5 overflow-hidden">
          <div
            className="h-full bg-purple-500 transition-all duration-300"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      {/* 任务列表 */}
      <div className="p-3">
        <div className="grid grid-cols-1 gap-2">
          {tasks.map(([taskId, taskState]) => (
            <div
              key={taskId}
              className={`task-card p-2 rounded border text-xs ${getStatusColor(taskState.status)}`}
            >
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-2">
                  {getStatusIcon(taskState.status)}
                  <span className="font-mono font-medium text-gray-700">{taskId}</span>
                </div>
                <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${
                  taskState.status === 'completed'
                    ? 'bg-green-100 text-green-700'
                    : taskState.status === 'error'
                    ? 'bg-red-100 text-red-700'
                    : taskState.status === 'running'
                    ? 'bg-blue-100 text-blue-700'
                    : 'bg-gray-100 text-gray-600'
                }`}>
                  {taskState.status === 'completed' ? t('workspace.taskCompleted') :
                   taskState.status === 'error' ? t('workspace.taskError') :
                   taskState.status === 'running' ? t('workspace.taskRunning') : t('workspace.taskPending')}
                </span>
              </div>

              {taskState.error_msg && (
                <div className="mt-1 text-xs text-red-600">
                  {t('workspace.errorLabel')}: {taskState.error_msg}
                </div>
              )}

              {showResults && taskState.result !== undefined && taskState.status === 'completed' && (
                <details className="mt-1">
                  <summary className="text-xs text-gray-600 cursor-pointer hover:text-gray-800">
                    {t('workspace.viewResults')}
                  </summary>
                  <pre className="mt-1 text-xs bg-white p-2 rounded border border-gray-200 overflow-x-auto">
                    {typeof taskState.result === 'object'
                      ? JSON.stringify(taskState.result, null, 2)
                      : String(taskState.result)}
                  </pre>
                </details>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
