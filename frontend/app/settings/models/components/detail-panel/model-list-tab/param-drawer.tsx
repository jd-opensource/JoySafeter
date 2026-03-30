'use client'

import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Switch } from '@/components/ui/switch'
import { useUpdateModelInstance } from '@/hooks/queries/models'
import type { ModelInstance } from '@/types/models'

interface ParamDrawerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  instance: ModelInstance
  configSchema: Record<string, any> | null
  providerDefaults: Record<string, unknown>
}

const COMMON_PARAMS = ['temperature', 'max_tokens', 'top_p', 'frequency_penalty', 'presence_penalty', 'timeout', 'max_retries']

export function ParamDrawer({ open, onOpenChange, instance, configSchema, providerDefaults }: ParamDrawerProps) {
  const updateInstance = useUpdateModelInstance()
  const [params, setParams] = useState<Record<string, unknown>>(instance.model_parameters ?? {})
  const [useDefaults, setUseDefaults] = useState<Record<string, boolean>>({})

  const paramKeys = configSchema
    ? Object.keys(configSchema)
    : COMMON_PARAMS

  const handleSave = async () => {
    const finalParams: Record<string, unknown> = {}
    for (const key of paramKeys) {
      if (!useDefaults[key] && params[key] !== undefined && params[key] !== '') {
        finalParams[key] = params[key]
      }
    }
    await updateInstance.mutateAsync({ instanceId: instance.id, request: { model_parameters: finalParams } })
    onOpenChange(false)
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-[400px] sm:w-[480px]">
        <SheetHeader>
          <SheetTitle>编辑参数 — {instance.model_name}</SheetTitle>
        </SheetHeader>

        <div className="mt-6 space-y-4 overflow-y-auto">
          {paramKeys.map((key) => {
            const isUsingDefault = useDefaults[key] ?? false
            const defaultVal = providerDefaults[key]
            const currentVal = params[key]

            return (
              <div key={key} className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <Label className="text-sm font-medium">{key}</Label>
                  {defaultVal !== undefined && (
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs text-[var(--text-muted)]">使用 Provider 默认</span>
                      <Switch
                        checked={isUsingDefault}
                        onCheckedChange={(v) => setUseDefaults((prev) => ({ ...prev, [key]: v }))}
                      />
                    </div>
                  )}
                </div>
                {isUsingDefault ? (
                  <Input
                    value={String(defaultVal ?? '')}
                    disabled
                    className="bg-[var(--surface-3)] text-[var(--text-muted)]"
                  />
                ) : (
                  <Input
                    value={currentVal !== undefined ? String(currentVal) : ''}
                    onChange={(e) => setParams((prev) => ({ ...prev, [key]: e.target.value }))}
                    placeholder={defaultVal !== undefined ? `默认: ${defaultVal}` : ''}
                  />
                )}
              </div>
            )
          })}
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>取消</Button>
          <Button onClick={handleSave} disabled={updateInstance.isPending}>
            {updateInstance.isPending ? '保存中...' : '保存'}
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  )
}
