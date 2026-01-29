'use client'

import { Repeat, CheckCircle2, XCircle } from 'lucide-react'
import React from 'react'

import { useTranslation } from '@/lib/i18n'

interface LoopExecutionViewProps {
  loopCount: number
  maxIterations: number
  conditionMet: boolean
  loopBody?: string[]
  conditionType?: 'while' | 'forEach' | 'doWhile'
  condition?: string
}

/**
 * 循环执行可视化组件
 * 显示循环计数、条件评估结果和循环体执行路径
 */
export const LoopExecutionView: React.FC<LoopExecutionViewProps> = ({
  loopCount,
  maxIterations,
  conditionMet,
  loopBody = [],
  conditionType = 'while',
  condition
}) => {
  const { t } = useTranslation()
  const progress = maxIterations > 0
    ? Math.min((loopCount / maxIterations) * 100, 100)
    : 0

  return (
    <div className="loop-execution border border-orange-200 rounded-lg bg-orange-50/50">
      {/* Header */}
      <div className="px-3 py-2 bg-orange-100 border-b border-orange-200 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Repeat size={16} className="text-orange-600" />
          <h3 className="text-sm font-semibold text-orange-900">{t('loop.title', { defaultValue: '循环执行' })}</h3>
        </div>
        <div className="text-xs font-mono font-semibold text-orange-700">
          {t('loop.iterationCount', {
            defaultValue: '第 {{loopCount}} / {{maxIterations}} 次迭代',
            loopCount,
            maxIterations: maxIterations > 0 ? maxIterations : '∞'
          }).replace('{{loopCount}}', loopCount.toString()).replace('{{maxIterations}}', maxIterations > 0 ? maxIterations.toString() : '∞')}
        </div>
      </div>

      <div className="p-3 space-y-3">
        {/* 进度条 */}
        {maxIterations > 0 && (
          <div>
            <div className="flex items-center justify-between text-xs text-gray-600 mb-1">
              <span>{t('loop.iterationProgress', { defaultValue: '迭代进度' })}</span>
              <span>{Math.round(progress)}%</span>
            </div>
            <div className="w-full bg-gray-200 rounded-full h-2 overflow-hidden">
              <div
                className="h-full bg-orange-500 transition-all duration-300"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        )}

        {/* 循环条件 */}
        <div className="flex items-center gap-2">
          {conditionMet ? (
            <CheckCircle2 size={16} className="text-green-600" />
          ) : (
            <XCircle size={16} className="text-red-600" />
          )}
          <div className="flex-1">
            <div className="text-xs text-gray-600">
              {t('loop.condition', { defaultValue: '条件:' })} <span className={conditionMet ? 'text-green-600 font-medium' : 'text-red-600 font-medium'}>
                {conditionMet ? t('loop.conditionMet', { defaultValue: '✓ 满足' }) : t('loop.conditionNotMet', { defaultValue: '✗ 不满足' })}
              </span>
            </div>
            {condition && (
              <code className="text-xs text-gray-500 mt-1 block bg-white px-2 py-1 rounded border border-gray-200">
                {condition}
              </code>
            )}
            {conditionType && (
              <span className="text-xs text-gray-400 mt-1 block">
                {t('loop.type', {
                  defaultValue: '类型: {{type}}',
                  type: conditionType === 'while' ? 'While 循环' : conditionType === 'forEach' ? 'ForEach 循环' : 'DoWhile 循环'
                }).replace('{{type}}', conditionType === 'while' ? 'While 循环' : conditionType === 'forEach' ? 'ForEach 循环' : 'DoWhile 循环')}
              </span>
            )}
          </div>
        </div>

        {/* 循环体执行路径 */}
        {loopBody && loopBody.length > 0 && (
          <div className="border-t border-orange-200 pt-3">
            <h4 className="text-xs font-semibold text-gray-700 mb-2">{t('loop.executionPath', { defaultValue: '循环体执行路径' })}</h4>
            <ol className="space-y-1">
              {loopBody.map((nodeId, index) => (
                <li key={index} className="text-xs flex items-center gap-2">
                  <span className="text-gray-400 w-4 text-right">{index + 1}.</span>
                  <code className="text-gray-700 bg-white px-2 py-0.5 rounded border border-gray-200">
                    {nodeId}
                  </code>
                </li>
              ))}
            </ol>
          </div>
        )}
      </div>
    </div>
  )
}
