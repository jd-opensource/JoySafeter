'use client'

import { X, Plus, Trash2, Settings2, Variable, AlertCircle, CheckCircle2 } from 'lucide-react'
import { useParams } from 'next/navigation'
import React, { useState, useMemo, useCallback } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { useToast } from '@/components/ui/use-toast'
import { useUserPermissions } from '@/hooks/use-user-permissions'
import { useWorkspacePermissions } from '@/hooks/use-workspace-permissions'
import { cn } from '@/lib/core/utils/cn'
import { useTranslation } from '@/lib/i18n'



/**
 * Context variable definition
 */
export interface ContextVariable {
  key: string
  value: string | number | boolean | object
  type: 'string' | 'number' | 'boolean' | 'object'
  description?: string
}

interface GraphSettingsPanelProps {
  variables: Record<string, ContextVariable>
  onUpdateVariables: (variables: Record<string, ContextVariable>) => void
  onClose: () => void
  open?: boolean
}

/**
 * GraphSettingsPanel - Configure graph-level context variables
 * 
 * These variables are available in condition expressions and are
 * passed to GraphState.context at runtime.
 * 
 * Usage in condition expressions:
 * - context.get('retry_count', 0) < 3
 * - context.get('user_type') == 'vip'
 */
export const GraphSettingsPanel: React.FC<GraphSettingsPanelProps> = ({
  variables,
  onUpdateVariables,
  onClose,
  open = true,
}) => {
  const { t } = useTranslation()
  const params = useParams()
  const workspaceId = params.workspaceId as string
  const { toast } = useToast()
  const { permissions, loading: permissionsLoading } = useWorkspacePermissions(workspaceId)
  const userPermissions = useUserPermissions(permissions, permissionsLoading, null)

  // Local state for editing
  const [editingKey, setEditingKey] = useState<string | null>(null)
  const [newVariable, setNewVariable] = useState<ContextVariable>({
    key: '',
    value: '',
    type: 'string',
    description: '',
  })

  // Convert variables object to array for display
  const variablesList = useMemo(() => {
    return Object.entries(variables).map(([key, variable]) => ({
      ...variable,
      key,
    }))
  }, [variables])

  // Add new variable
  const handleAddVariable = useCallback(() => {
    if (!userPermissions.canEdit) {
      toast({
        title: t('workspace.noPermission'),
        description: t('workspace.cannotEditNode'),
        variant: 'destructive',
      })
      return
    }

    if (!newVariable.key.trim()) {
      toast({
        title: t('workspace.validationError'),
        description: t('workspace.variableKeyRequired'),
        variant: 'destructive',
      })
      return
    }

    // Check for duplicate keys
    if (variables[newVariable.key]) {
      toast({
        title: t('workspace.validationError'),
        description: t('workspace.variableKeyExists', { key: newVariable.key }),
        variant: 'destructive',
      })
      return
    }

    // Validate key format (alphanumeric and underscores only)
    if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(newVariable.key)) {
      toast({
        title: t('workspace.validationError'),
        description: t('workspace.variableKeyInvalid'),
        variant: 'destructive',
      })
      return
    }

    // Parse value based on type
    let parsedValue: string | number | boolean | object = newVariable.value
    try {
      if (newVariable.type === 'number') {
        parsedValue = Number(newVariable.value)
        if (isNaN(parsedValue)) {
          throw new Error('Invalid number')
        }
      } else if (newVariable.type === 'boolean') {
        parsedValue = newVariable.value === 'true' || newVariable.value === true
      } else if (newVariable.type === 'object') {
        parsedValue = typeof newVariable.value === 'string' 
          ? JSON.parse(newVariable.value || '{}')
          : newVariable.value
      }
    } catch (e) {
      toast({
        title: t('workspace.validationError'),
        description: t('workspace.invalidValue', { type: newVariable.type }),
        variant: 'destructive',
      })
      return
    }

    const updatedVariables = {
      ...variables,
      [newVariable.key]: {
        key: newVariable.key,
        value: parsedValue,
        type: newVariable.type,
        description: newVariable.description,
      },
    }

    onUpdateVariables(updatedVariables)
    setNewVariable({ key: '', value: '', type: 'string', description: '' })
  }, [newVariable, variables, userPermissions.canEdit, onUpdateVariables, toast, t])

  // Update existing variable
  const handleUpdateVariable = useCallback((key: string, updates: Partial<ContextVariable>) => {
    if (!userPermissions.canEdit) {
      toast({
        title: t('workspace.noPermission'),
        description: t('workspace.cannotEditNode'),
        variant: 'destructive',
      })
      return
    }

    const current = variables[key]
    if (!current) return

    const updatedVariables = {
      ...variables,
      [key]: {
        ...current,
        ...updates,
      },
    }

    onUpdateVariables(updatedVariables)
  }, [variables, userPermissions.canEdit, onUpdateVariables, toast, t])

  // Delete variable
  const handleDeleteVariable = useCallback((key: string) => {
    if (!userPermissions.canEdit) {
      toast({
        title: t('workspace.noPermission'),
        description: t('workspace.cannotEditNode'),
        variant: 'destructive',
      })
      return
    }

    const { [key]: _, ...rest } = variables
    onUpdateVariables(rest)
  }, [variables, userPermissions.canEdit, onUpdateVariables, toast, t])

  // Format value for display
  const formatValueForDisplay = (variable: ContextVariable): string => {
    if (variable.type === 'object') {
      return typeof variable.value === 'string' 
        ? variable.value 
        : JSON.stringify(variable.value, null, 2)
    }
    return String(variable.value)
  }

  // Get value input component based on type
  const renderValueInput = (
    value: string | number | boolean | object,
    type: ContextVariable['type'],
    onChange: (val: string | number | boolean | object) => void,
    disabled: boolean = false
  ) => {
    switch (type) {
      case 'boolean':
        return (
          <Select
            value={String(value)}
            onValueChange={(v) => onChange(v === 'true')}
            disabled={disabled}
          >
            <SelectTrigger className="h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="true">true</SelectItem>
              <SelectItem value="false">false</SelectItem>
            </SelectContent>
          </Select>
        )
      case 'number':
        return (
          <Input
            type="number"
            value={value as number}
            onChange={(e) => onChange(Number(e.target.value))}
            disabled={disabled}
            className="h-8 text-xs"
          />
        )
      case 'object':
        return (
          <Textarea
            value={typeof value === 'string' ? value : JSON.stringify(value, null, 2)}
            onChange={(e) => {
              try {
                onChange(JSON.parse(e.target.value))
              } catch {
                onChange(e.target.value)
              }
            }}
            disabled={disabled}
            className="text-xs font-mono min-h-[60px]"
            placeholder='{"key": "value"}'
          />
        )
      default:
        return (
          <Input
            value={String(value)}
            onChange={(e) => onChange(e.target.value)}
            disabled={disabled}
            className="h-8 text-xs"
          />
        )
    }
  }

  return (
    <Dialog open={open} onOpenChange={(open) => !open && onClose()}>
      <DialogContent hideCloseButton className="sm:max-w-[500px] max-h-[85vh] p-0 bg-white border border-gray-200 rounded-2xl shadow-2xl flex flex-col overflow-hidden">
        <DialogHeader className="px-4 py-3.5 border-b border-gray-100 shrink-0 flex flex-row items-center justify-between">
          <div className="flex items-center gap-3 text-gray-900 overflow-hidden">
            <div className="p-1.5 rounded-lg border border-gray-50 shadow-sm shrink-0 bg-violet-50 text-violet-600">
              <Settings2 size={14} />
            </div>
            <div className="flex flex-col min-w-0">
              <DialogTitle className="font-bold text-sm leading-tight truncate">{t('workspace.graphSettings')}</DialogTitle>
              <span className="text-[9px] text-gray-400 uppercase tracking-widest font-bold">
                {t('workspace.contextVariables')}
              </span>
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            className="h-7 w-7 text-gray-300 hover:text-gray-600 hover:bg-gray-100 shrink-0"
          >
            <X size={16} />
          </Button>
        </DialogHeader>

      {/* Body */}
      <div className="flex-1 overflow-y-auto custom-scrollbar p-4 space-y-4">
        {/* Info Banner */}
        <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg text-xs text-blue-800">
          <div className="flex items-start gap-2">
            <Variable size={14} className="mt-0.5 shrink-0" />
            <div>
              <div className="font-medium mb-1">{t('workspace.contextVariablesTitle')}</div>
              <p className="text-blue-600">
                {t('workspace.contextVariablesDescription')}{' '}
                {t('workspace.contextVariablesAccess')}{' '}
                <code className="bg-blue-100 px-1 rounded">{t('workspace.contextVariablesUsage')}</code>
              </p>
            </div>
          </div>
        </div>

        {/* Existing Variables */}
        {variablesList.length > 0 && (
          <div className="space-y-2">
            <Label className="text-[10px] font-bold text-gray-400 uppercase tracking-wider">
              {t('workspace.definedVariables')} ({variablesList.length})
            </Label>
            <div className="space-y-2">
              {variablesList.map((variable) => (
                <div
                  key={variable.key}
                  className="border border-gray-200 rounded-lg p-3 bg-gray-50/50 space-y-2"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <code className="text-xs font-mono font-medium text-violet-600 bg-violet-50 px-1.5 py-0.5 rounded">
                        {variable.key}
                      </code>
                      <span className="text-[9px] text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded uppercase">
                        {variable.type}
                      </span>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => handleDeleteVariable(variable.key)}
                      disabled={!userPermissions.canEdit}
                      className="h-6 w-6 text-gray-400 hover:text-red-500"
                    >
                      <Trash2 size={12} />
                    </Button>
                  </div>
                  
                  <div className="space-y-1.5">
                    <Label className="text-[9px] font-bold text-gray-400">{t('workspace.value')}</Label>
                    {renderValueInput(
                      variable.value,
                      variable.type,
                      (val) => handleUpdateVariable(variable.key, { value: val }),
                      !userPermissions.canEdit
                    )}
                  </div>

                  {variable.description && (
                    <p className="text-[9px] text-gray-400 italic">{variable.description}</p>
                  )}

                  {/* Usage hint */}
                  <div className="text-[9px] text-gray-400 font-mono bg-white px-2 py-1 rounded border border-gray-100">
                    context.get('{variable.key}'{variable.type === 'string' ? '' : `, ${variable.type === 'number' ? '0' : variable.type === 'boolean' ? 'False' : '{}'}`})
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Add New Variable */}
        <div className="space-y-3 border border-dashed border-gray-300 rounded-lg p-3 bg-white">
          <Label className="text-[10px] font-bold text-gray-400 uppercase tracking-wider flex items-center gap-1.5">
            <Plus size={12} />
            {t('workspace.addNewVariable')}
          </Label>

          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1">
              <Label className="text-[9px] font-bold text-gray-400">{t('workspace.variableKey')}</Label>
              <Input
                value={newVariable.key}
                onChange={(e) => setNewVariable({ ...newVariable, key: e.target.value })}
                placeholder={t('workspace.variableNamePlaceholder')}
                disabled={!userPermissions.canEdit}
                className="h-8 text-xs font-mono"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-[9px] font-bold text-gray-400">{t('workspace.variableType')}</Label>
              <Select
                value={newVariable.type}
                onValueChange={(v) => setNewVariable({ ...newVariable, type: v as ContextVariable['type'], value: '' })}
                disabled={!userPermissions.canEdit}
              >
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="string">string</SelectItem>
                  <SelectItem value="number">number</SelectItem>
                  <SelectItem value="boolean">boolean</SelectItem>
                  <SelectItem value="object">object</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-1">
            <Label className="text-[9px] font-bold text-gray-400">{t('workspace.initialValue')}</Label>
            {renderValueInput(
              newVariable.value,
              newVariable.type,
              (val) => setNewVariable({ ...newVariable, value: val }),
              !userPermissions.canEdit
            )}
          </div>

          <div className="space-y-1">
            <Label className="text-[9px] font-bold text-gray-400">{t('workspace.variableDescription')}</Label>
            <Input
              value={newVariable.description || ''}
              onChange={(e) => setNewVariable({ ...newVariable, description: e.target.value })}
              placeholder={t('workspace.variableDescriptionPlaceholder')}
              disabled={!userPermissions.canEdit}
              className="h-8 text-xs"
            />
          </div>

          <Button
            variant="outline"
            size="sm"
            onClick={handleAddVariable}
            disabled={!userPermissions.canEdit || !newVariable.key.trim()}
            className="w-full h-8 text-xs"
          >
            <Plus size={12} className="mr-1" />
            {t('workspace.addVariable')}
          </Button>
        </div>

        {/* Empty State */}
        {variablesList.length === 0 && (
          <div className="text-center py-6 text-gray-400">
            <Variable size={32} className="mx-auto mb-2 opacity-30" />
            <p className="text-xs">{t('workspace.noContextVariablesDefined')}</p>
            <p className="text-[9px] mt-1">{t('workspace.addVariablesHint')}</p>
          </div>
        )}
      </div>

      {/* Footer Info */}
      <div className="px-4 py-2 border-t border-gray-100 bg-gray-50 flex items-center justify-between text-[9px] text-gray-400 font-mono">
        <span>{variablesList.length} {t('workspace.variableCount')}</span>
        <span className="flex items-center gap-1">
          <div className="w-1.5 h-1.5 rounded-full bg-green-500" /> {t('workspace.saved')}
        </span>
      </div>
      </DialogContent>
    </Dialog>
  )
}

