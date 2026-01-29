'use client'

import { CheckCircle2, XCircle, ArrowRight, GitBranch, Repeat } from 'lucide-react'
import React from 'react'

export interface RouteDecision {
  result: boolean | string | number
  reason: string
  goto: string
  evaluated_rules?: Array<{
    rule: string
    condition: string
    matched: boolean
  }>
}

interface RouteDecisionDisplayProps {
  nodeId: string
  nodeType: 'condition' | 'router' | 'loop'
  decision: RouteDecision
  expression?: string // Expression for Condition node
}

/**
 * Route decision display component
 * Displays the routing decision process and results for Condition/Router/Loop nodes
 */
export const RouteDecisionDisplay: React.FC<RouteDecisionDisplayProps> = ({
  nodeId,
  nodeType,
  decision,
  expression
}) => {
  const getNodeTypeIcon = () => {
    switch (nodeType) {
      case 'condition':
        return <GitBranch size={16} className="text-blue-500" />
      case 'router':
        return <GitBranch size={16} className="text-purple-500" />
      case 'loop':
        return <Repeat size={16} className="text-orange-500" />
      default:
        return null
    }
  }

  const getNodeTypeLabel = () => {
    switch (nodeType) {
      case 'condition':
        return 'Condition'
      case 'router':
        return 'Router'
      case 'loop':
        return 'Loop'
      default:
        return 'Unknown'
    }
  }

  return (
    <div className="route-decision border border-gray-200 rounded-lg bg-white overflow-hidden">
      {/* Header */}
      <div className="px-3 py-2 bg-gray-50 border-b border-gray-200 flex items-center gap-2">
        {getNodeTypeIcon()}
        <span className="text-xs font-semibold text-gray-700">{getNodeTypeLabel()}</span>
        <span className="text-xs text-gray-500 font-mono">({nodeId})</span>
      </div>

      {/* Condition Node */}
      {nodeType === 'condition' && (
        <div className="p-3 space-y-2">
          {expression && (
            <div className="text-xs">
              <span className="text-gray-500">Expression:</span>{' '}
              <code className="bg-gray-100 px-1.5 py-0.5 rounded text-gray-800">
                {expression}
              </code>
            </div>
          )}
          <div className="flex items-center gap-2">
            {typeof decision.result === 'boolean' && (
              <>
                {decision.result ? (
                  <CheckCircle2 size={16} className="text-green-600" />
                ) : (
                  <XCircle size={16} className="text-red-600" />
                )}
                <span className={`text-sm font-medium ${
                  decision.result ? 'text-green-600' : 'text-red-600'
                }`}>
                  {decision.result ? '✓ True' : '✗ False'}
                </span>
              </>
            )}
          </div>
          {decision.reason && (
            <p className="text-xs text-gray-600">{decision.reason}</p>
          )}
          <div className="flex items-center gap-2 pt-2 border-t border-gray-200">
            <ArrowRight size={14} className="text-blue-500" />
            <span className="text-xs text-gray-500">Go to:</span>
            <span className="text-xs font-mono font-semibold text-blue-600">
              {decision.goto}
            </span>
          </div>
        </div>
      )}

      {/* Router Node */}
      {nodeType === 'router' && (
        <div className="p-3 space-y-3">
          {decision.evaluated_rules && decision.evaluated_rules.length > 0 && (
            <div className="space-y-1">
              <div className="text-xs font-medium text-gray-700 mb-2">Rule Evaluation:</div>
              {decision.evaluated_rules.map((rule, index) => (
                <div
                  key={index}
                  className={`text-xs p-2 rounded border ${
                    rule.matched
                      ? 'bg-green-50 border-green-200'
                      : 'bg-gray-50 border-gray-200 opacity-60'
                  }`}
                >
                  <div className="flex items-center gap-2 mb-1">
                    {rule.matched ? (
                      <CheckCircle2 size={12} className="text-green-600" />
                    ) : (
                      <XCircle size={12} className="text-gray-400" />
                    )}
                    <span className={`font-medium ${
                      rule.matched ? 'text-green-700' : 'text-gray-500'
                    }`}>
                      {rule.matched ? 'Matched' : 'Not Matched'}
                    </span>
                  </div>
                  <code className="text-xs text-gray-700">{rule.condition}</code>
                </div>
              ))}
            </div>
          )}
          <div>
            <div className="text-xs font-medium text-gray-700 mb-1">Match Result:</div>
            <div className="text-sm font-semibold text-purple-600">
              {typeof decision.result === 'string' ? decision.result : 'Default Route'}
            </div>
          </div>
          {decision.reason && (
            <p className="text-xs text-gray-600">{decision.reason}</p>
          )}
          <div className="flex items-center gap-2 pt-2 border-t border-gray-200">
            <ArrowRight size={14} className="text-purple-500" />
            <span className="text-xs text-gray-500">Go to:</span>
            <span className="text-xs font-mono font-semibold text-purple-600">
              {decision.goto}
            </span>
          </div>
        </div>
      )}

      {/* Loop Node */}
      {nodeType === 'loop' && (
        <div className="p-3 space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-500">Loop Count:</span>
            <span className="text-sm font-mono font-semibold text-orange-600">
              {typeof decision.result === 'number' ? decision.result : 0}
            </span>
          </div>
          {decision.reason && (
            <p className="text-xs text-gray-600">{decision.reason}</p>
          )}
          <div className="flex items-center gap-2 pt-2 border-t border-gray-200">
            <ArrowRight size={14} className="text-orange-500" />
            <span className="text-xs text-gray-500">
              {typeof decision.result === 'number' && decision.result > 0
                ? 'Continue Loop'
                : 'Exit Loop'}
              :
            </span>
            <span className="text-xs font-mono font-semibold text-orange-600">
              {decision.goto}
            </span>
          </div>
        </div>
      )}
    </div>
  )
}

