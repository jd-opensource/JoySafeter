'use client'

import { PauseCircle, CheckCircle, XCircle, Edit, Play, SkipForward, ArrowRight } from 'lucide-react'
import React, { useState, useMemo } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useToast } from '@/components/ui/use-toast'
import { useTranslation } from '@/lib/i18n'

import { resumeWithCommand } from '../services/commandService'
import { useBuilderStore } from '../stores/builderStore'
import { useExecutionStore, type InterruptInfo } from '../stores/executionStore'
import { getNodeNameFromFlowNode } from '../utils/nodeNameUtils'


interface InterruptPanelProps {
  interrupt: InterruptInfo
  onClose?: () => void
}

// Security: Sensitive field names to redact from state display
const SENSITIVE_FIELDS = [
  'password', 'passwd', 'pwd', 'secret', 'token', 'apikey', 'api_key',
  'api-key', 'authorization', 'auth', 'credential', 'private_key',
  'private-key', 'session', 'cookie', 'csrf', 'jwt', 'bearer',
]

/**
 * Sanitize string value by removing HTML tags and special characters
 * Used for sanitizing user-controlled data before display
 */
function sanitizeStringValue(value: string): string {
  if (typeof value !== 'string') return value
  // Remove HTML tags and special characters that could be used for XSS
  return value
    .replace(/<[^>]*>/g, '') // Remove HTML tags
    .replace(/javascript:/gi, '') // Remove javascript: protocol
    .replace(/on\w+\s*=/gi, '') // Remove event handlers
    .slice(0, 200) // Limit length
}

/**
 * Filter sensitive fields from state object
 * Returns a sanitized version with sensitive values redacted
 */
function filterSensitiveFields(state: any): any {
  if (!state || typeof state !== 'object') return state

  const sanitized = Array.isArray(state) ? [...state] : { ...state }
  const keys = Object.keys(sanitized)

  for (const key of keys) {
    const lowerKey = key.toLowerCase()
    // Check if this is a sensitive field
    const isSensitive = SENSITIVE_FIELDS.some(sensitive =>
      lowerKey.includes(sensitive)
    )

    if (isSensitive) {
      // Redact sensitive values
      sanitized[key] = '[REDACTED]'
    } else if (typeof sanitized[key] === 'object' && sanitized[key] !== null) {
      // Recursively filter nested objects
      sanitized[key] = filterSensitiveFields(sanitized[key])
    } else if (typeof sanitized[key] === 'string') {
      // Sanitize string values
      sanitized[key] = sanitizeStringValue(sanitized[key])
    }
  }

  return sanitized
}

// Extract key state fields for display
function extractKeyStateFields(state: any): { key: string; value: any }[] {
  if (!state || typeof state !== 'object') {
    return []
  }

  const keyFields: { key: string; value: any }[] = []

  // Priority display of common fields
  const priorityFields = ['messages', 'context', 'input', 'output', 'result', 'data']

  for (const key of priorityFields) {
    if (key in state) {
      const value = state[key]
      // If array, show length; if object, show number of keys; otherwise show value
      if (Array.isArray(value)) {
        keyFields.push({ key, value: `Array(${value.length})` })
      } else if (value && typeof value === 'object') {
        keyFields.push({ key, value: `Object(${Object.keys(value).length} keys)` })
      } else {
        keyFields.push({ key, value: String(value).slice(0, 50) })
      }
    }
  }

  // Add other fields (display up to 10)
  const otherKeys = Object.keys(state).filter(k => !priorityFields.includes(k)).slice(0, 10)
  for (const key of otherKeys) {
    const value = state[key]
    if (Array.isArray(value)) {
      keyFields.push({ key, value: `Array(${value.length})` })
    } else if (value && typeof value === 'object') {
      keyFields.push({ key, value: `Object(${Object.keys(value).length} keys)` })
    } else {
      keyFields.push({ key, value: String(value).slice(0, 50) })
    }
  }

  return keyFields
}

export const InterruptPanel: React.FC<InterruptPanelProps> = ({ interrupt, onClose }) => {
  const { t } = useTranslation()
  const { removeInterrupt } = useExecutionStore()
  const { nodes } = useBuilderStore()
  const { toast } = useToast()
  const [isResuming, setIsResuming] = useState(false)
  const [editedState, setEditedState] = useState(interrupt.state)
  const [isEditing, setIsEditing] = useState(false)
  const [showGotoSelector, setShowGotoSelector] = useState(false)
  const [selectedNodeId, setSelectedNodeId] = useState<string>('')

  const { setExecuting } = useExecutionStore()

  // Get list of jumpable nodes (exclude current interrupt node)
  const availableNodes = useMemo(() => {
    return nodes
      .filter(node => node.id !== interrupt.nodeId)
      .map(node => ({
        id: node.id,
        label: (node.data as { label?: string })?.label || node.id,
        type: (node.data as { type?: string })?.type || 'unknown',
      }))
      .sort((a, b) => a.label.localeCompare(b.label))
  }, [nodes, interrupt.nodeId])

  // Extract key state fields (with sensitive fields filtered)
  const keyStateFields = useMemo(() => extractKeyStateFields(filterSensitiveFields(interrupt.state)), [interrupt.state])

  const handleContinue = async () => {
    setIsResuming(true)
    setExecuting(true)
    try {
      await resumeWithCommand(
        interrupt.threadId,
        {
          update: {}, // Empty update, continue execution
        },
        undefined
      )
      removeInterrupt(interrupt.nodeId)
      toast({
        title: 'Execution Resumed',
        description: `Continued execution from node "${interrupt.nodeLabel}"`,
      })
      onClose?.()
    } catch (error: unknown) {
      setExecuting(false)
      const err = error as { message?: string }
      toast({
        title: t('workspace.continueExecutionFailed'),
        description: err?.message || t('workspace.cannotContinueExecution'),
        variant: 'destructive',
      })
    } finally {
      setIsResuming(false)
    }
  }

  const handleStop = async () => {
    removeInterrupt(interrupt.nodeId)
    toast({
      title: t('workspace.executionStopped'),
      description: t('workspace.executionStoppedDescription'),
    })
    onClose?.()
  }

  const handleUpdateState = async () => {
    setIsResuming(true)
    setExecuting(true)
    try {
      await resumeWithCommand(
        interrupt.threadId,
        {
          update: editedState,
        },
        undefined
      )
      removeInterrupt(interrupt.nodeId)
      toast({
        title: 'Execution Resumed',
        description: `Continued execution from node "${interrupt.nodeLabel}" with updated state`,
      })
      setIsEditing(false)
      onClose?.()
    } catch (error: unknown) {
      setExecuting(false)
      const err = error as { message?: string }
      toast({
        title: t('workspace.continueExecutionFailed'),
        description: err?.message || t('workspace.cannotContinueExecution'),
        variant: 'destructive',
      })
    } finally {
      setIsResuming(false)
    }
  }

  const handleGoto = async (targetNodeId?: string) => {
    const nodeId = targetNodeId || selectedNodeId
    if (!nodeId) {
      toast({
        title: 'Please Select a Node',
        description: 'Please select a node to jump to first',
        variant: 'destructive',
      })
      return
    }

    setIsResuming(true)
    setExecuting(true)
    try {
      // Find target node
      const targetNode = nodes.find(n => n.id === nodeId)

      // Use unified node name conversion tool (ensure consistency with backend LangGraph format)
      const nodeName = targetNode
        ? getNodeNameFromFlowNode({
            id: targetNode.id,
            data: targetNode.data as { label?: string; type?: string },
          })
        : `unknown_${nodeId.slice(0, 8)}`

      await resumeWithCommand(
        interrupt.threadId,
        {
          goto: nodeName,
        },
        undefined
      )
      removeInterrupt(interrupt.nodeId)
      toast({
        title: 'Execution Jumped',
        description: `Jumped to node: ${(targetNode?.data as { label?: string })?.label || nodeName}`,
      })
      setShowGotoSelector(false)
      onClose?.()
    } catch (error: unknown) {
      setExecuting(false)
      const err = error as { message?: string }
      toast({
        title: 'Jump Failed',
        description: err?.message || 'Unable to jump to specified node',
        variant: 'destructive',
      })
    } finally {
      setIsResuming(false)
    }
  }

  return (
    <Card className="w-full border-amber-200 bg-amber-50/50">
      <CardHeader>
        <div className="flex items-center gap-2">
          <PauseCircle className="h-5 w-5 text-amber-600" />
          <CardTitle className="text-lg">{t('workspace.executionPaused')}</CardTitle>
        </div>
        <CardDescription>
          {t('workspace.nodeWaitingForAction', { nodeLabel: sanitizeStringValue(interrupt.nodeLabel || interrupt.nodeId) })}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* State Summary */}
        {!isEditing && keyStateFields.length > 0 && (
          <div className="space-y-2">
            <label className="text-sm font-medium text-gray-700">State Summary</label>
            <div className="p-3 bg-white border border-gray-200 rounded-md space-y-1">
              {keyStateFields.slice(0, 5).map((field, idx) => (
                <div key={idx} className="text-xs">
                  <span className="font-mono font-semibold text-gray-700">{field.key}:</span>{' '}
                  <span className="text-gray-600">{String(field.value)}</span>
                </div>
              ))}
              {keyStateFields.length > 5 && (
                <div className="text-xs text-gray-500 pt-1">
                  and {keyStateFields.length - 5} more fields...
                </div>
              )}
            </div>
          </div>
        )}

        {/* Full State Edit */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label className="text-sm font-medium text-gray-700">
              {isEditing ? 'Edit State (JSON)' : 'Full State'}
            </label>
            {!isEditing && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setIsEditing(true)}
                className="h-7 text-xs"
              >
                <Edit className="h-3 w-3 mr-1" />
                Edit
              </Button>
            )}
          </div>
          {isEditing ? (
            <div className="space-y-2">
              <textarea
                value={JSON.stringify(editedState, null, 2)}
                onChange={(e) => {
                  try {
                    setEditedState(JSON.parse(e.target.value))
                  } catch {
                    // Invalid JSON, keep as is
                  }
                }}
                className="w-full h-32 p-2 text-xs font-mono border border-gray-300 rounded-md bg-white"
                placeholder="Edit state JSON..."
              />
              <div className="flex gap-2">
                <Button
                  size="sm"
                  onClick={handleUpdateState}
                  disabled={isResuming}
                  className="h-7 text-xs"
                >
                  <Play className="h-3 w-3 mr-1" />
                  Apply and Continue
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    setIsEditing(false)
                    setEditedState(interrupt.state)
                  }}
                  disabled={isResuming}
                  className="h-7 text-xs"
                >
                  Cancel
                </Button>
              </div>
            </div>
          ) : (
            <div className="p-3 bg-white border border-gray-200 rounded-md max-h-32 overflow-auto">
              <pre className="text-xs font-mono text-gray-600">
                {JSON.stringify(filterSensitiveFields(interrupt.state), null, 2)}
              </pre>
            </div>
          )}
        </div>

        {/* Jump to Node */}
        {!isEditing && !showGotoSelector && availableNodes.length > 0 && (
          <div className="space-y-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowGotoSelector(true)}
              className="w-full"
              disabled={isResuming}
            >
              <SkipForward className="h-4 w-4 mr-2" />
              Jump to Other Node
            </Button>
          </div>
        )}

        {showGotoSelector && (
          <div className="space-y-2 p-3 bg-white border border-gray-200 rounded-md">
            <label className="text-sm font-medium text-gray-700">Select Node to Jump To</label>
            <Select value={selectedNodeId} onValueChange={setSelectedNodeId}>
              <SelectTrigger>
                <SelectValue placeholder="Select node..." />
              </SelectTrigger>
              <SelectContent>
                {availableNodes.map((node) => (
                  <SelectItem key={node.id} value={node.id}>
                    {node.label} ({node.type})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <div className="flex gap-2">
              <Button
                size="sm"
                onClick={() => handleGoto()}
                disabled={isResuming || !selectedNodeId}
                className="flex-1"
              >
                <ArrowRight className="h-3 w-3 mr-1" />
                Jump
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setShowGotoSelector(false)
                  setSelectedNodeId('')
                }}
                disabled={isResuming}
              >
                Cancel
              </Button>
            </div>
          </div>
        )}

        {/* Main Action Buttons */}
        {!isEditing && !showGotoSelector && (
          <div className="flex gap-2 pt-2 border-t border-amber-200">
            <Button
              onClick={handleContinue}
              disabled={isResuming}
              className="flex-1 bg-green-600 hover:bg-green-700"
            >
              <CheckCircle className="h-4 w-4 mr-2" />
              Continue Execution
            </Button>
            <Button
              onClick={handleStop}
              disabled={isResuming}
              variant="destructive"
              className="flex-1"
            >
              <XCircle className="h-4 w-4 mr-2" />
              Stop Execution
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
