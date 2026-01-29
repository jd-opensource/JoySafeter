'use client'

import React from 'react'

import { useExecutionStore } from '../../stores/executionStore'

import { ExecutionTrace } from './ExecutionTrace'
import { LoopExecutionView } from './LoopExecutionView'
import { ParallelExecutionView } from './ParallelExecutionView'
import { RouteDecisionDisplay } from './RouteDecisionDisplay'
import { StateViewer } from './StateViewer'

/**
 * Execution Control Panel
 * Integrates all visualization components, displaying execution status, routing decisions, loops, and parallel tasks
 */
export const ExecutionControlPanel: React.FC = () => {
  const { 
    currentState, 
    executionTrace, 
    routeDecisions,
    isExecuting 
  } = useExecutionStore()

  // Get current node type (inferred from node data or routing decisions)
  const getNodeType = (nodeId: string | undefined): 'condition' | 'router' | 'loop' | null => {
    if (!nodeId) return null
    const latestDecision = routeDecisions
      .filter(d => d.nodeId === nodeId)
      .sort((a, b) => b.timestamp - a.timestamp)[0]
    return latestDecision?.nodeType || null
  }

  // Get the latest routing decision
  const latestRouteDecision = routeDecisions.length > 0
    ? routeDecisions[routeDecisions.length - 1]
    : null

  // Get the next node (from latest routing decision or state)
  const getNextNode = (): string | undefined => {
    if (latestRouteDecision) {
      return latestRouteDecision.decision.goto
    }
    // Can get last command.goto from trace
    if (executionTrace.length > 0) {
      const lastTrace = executionTrace[executionTrace.length - 1]
      return lastTrace.command.goto
    }
    return undefined
  }

  if (!currentState) {
    return (
      <div className="execution-control-panel p-4 text-center text-gray-500">
        <p className="text-sm">No execution status data</p>
      </div>
    )
  }

  return (
    <div className="execution-control-panel space-y-4 p-4 bg-gray-50">
      {/* Current State */}
      <div>
        <StateViewer 
          state={currentState} 
          nodeId={currentState.current_node}
          compact={false}
        />
      </div>

      {/* Routing Decision */}
      {latestRouteDecision && (
        <div>
          <RouteDecisionDisplay 
            nodeId={latestRouteDecision.nodeId}
            nodeType={latestRouteDecision.nodeType}
            decision={latestRouteDecision.decision}
          />
        </div>
      )}

      {/* Loop Information */}
      {currentState.loop_count !== undefined && currentState.loop_count > 0 && (
        <div>
          <LoopExecutionView 
            loopCount={currentState.loop_count}
            maxIterations={currentState.max_loop_iterations || 0}
            conditionMet={currentState.loop_condition_met ?? false}
            loopBody={currentState.loop_body_trace}
          />
        </div>
      )}

      {/* Parallel Tasks */}
      {currentState.parallel_mode && currentState.task_states && 
       Object.keys(currentState.task_states).length > 0 && (
        <div>
          <ParallelExecutionView 
            taskStates={currentState.task_states}
            showResults={true}
          />
        </div>
      )}

      {/* Execution Trace */}
      {executionTrace.length > 0 && (
        <div>
          <ExecutionTrace trace={executionTrace} maxSteps={20} />
        </div>
      )}

      {/* Execution Status Indicator */}
      {isExecuting && (
        <div className="flex items-center gap-2 p-2 bg-blue-50 border border-blue-200 rounded text-sm text-blue-700">
          <div className="w-2 h-2 bg-blue-500 rounded-full animate-pulse" />
          <span>Executing...</span>
        </div>
      )}
    </div>
  )
}

