'use client'

import { useEffect, useMemo, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Slider } from '@/components/ui/slider'
import { Switch } from '@/components/ui/switch'
import { useToast } from '@/hooks/use-toast'
import { useUpdateModelInstance } from '@/hooks/queries/models'

import { parseJsonSchema } from '../../schema-utils'
import type { SchemaField } from '../../schema-utils'

interface ParamDrawerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  instanceId: string
  modelName: string
  modelParameters: Record<string, unknown>
  configSchema: Record<string, any> | null
  providerDefaults: Record<string, unknown>
}

export function ParamDrawer({
  open,
  onOpenChange,
  instanceId,
  modelName,
  modelParameters,
  configSchema,
  providerDefaults,
}: ParamDrawerProps) {
  const updateInstance = useUpdateModelInstance()
  const { toast } = useToast()
  const [params, setParams] = useState<Record<string, unknown>>({})
  const [useDefaults, setUseDefaults] = useState<Record<string, boolean>>({})

  const fields = useMemo(() => parseJsonSchema(configSchema), [configSchema])

  useEffect(() => {
    if (open) {
      setParams(modelParameters)
      const defaults: Record<string, boolean> = {}
      for (const field of fields) {
        const hasInstanceValue = modelParameters[field.key] !== undefined
        const hasProviderDefault = providerDefaults[field.key] !== undefined
        defaults[field.key] = !hasInstanceValue && hasProviderDefault
      }
      setUseDefaults(defaults)
    }
  }, [open, modelParameters, fields, providerDefaults])

  const handleSave = async () => {
    const finalParams: Record<string, unknown> = {}
    for (const field of fields) {
      if (!useDefaults[field.key] && params[field.key] !== undefined && params[field.key] !== '') {
        finalParams[field.key] = params[field.key]
      }
    }
    try {
      await updateInstance.mutateAsync({
        instanceId,
        request: { model_parameters: finalParams },
      })
      toast({ title: 'Parameters saved' })
      onOpenChange(false)
    } catch (err) {
      toast({
        variant: 'destructive',
        title: 'Save failed',
        description: err instanceof Error ? err.message : 'Please try again',
      })
    }
  }

  const setParam = (key: string, value: unknown) => {
    setParams((prev) => ({ ...prev, [key]: value }))
  }

  const isNumericField = (field: SchemaField) =>
    field.type === 'number' || field.type === 'integer'

  const getEffectiveValue = (field: SchemaField): unknown => {
    if (useDefaults[field.key]) {
      const dv = providerDefaults[field.key]
      return dv !== undefined ? dv : field.default
    }
    const v = params[field.key]
    return v !== undefined ? v : field.default
  }

  const getNumericValue = (field: SchemaField): number => {
    const v = getEffectiveValue(field)
    return typeof v === 'number' ? v : 0
  }

  if (fields.length === 0) {
    return (
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent side="right" className="w-[400px] sm:w-[480px]">
          <SheetHeader>
            <SheetTitle>Parameters — {modelName}</SheetTitle>
            <SheetDescription>Adjust model runtime parameters</SheetDescription>
          </SheetHeader>
          <div className="flex h-40 items-center justify-center text-[var(--text-muted)]">
            <p className="text-sm">No configurable parameters for this model</p>
          </div>
        </SheetContent>
      </Sheet>
    )
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-[400px] sm:w-[480px] flex flex-col">
        <SheetHeader>
          <SheetTitle>Parameters — {modelName}</SheetTitle>
          <SheetDescription>Adjust model runtime parameters such as temperature, max_tokens, etc.</SheetDescription>
        </SheetHeader>

        <div className="mt-4 flex-1 space-y-5 overflow-y-auto pr-1">
          {fields.map((field) => {
            const isUsingDefault = useDefaults[field.key] ?? false
            const hasProviderDefault = providerDefaults[field.key] !== undefined
            const effectiveValue = getEffectiveValue(field)
            const isSlider =
              isNumericField(field) &&
              field.minimum !== undefined &&
              field.maximum !== undefined

            return (
              <div key={field.key} className="space-y-2">
                <div className="flex items-center justify-between">
                  <div>
                    <Label className="text-sm font-medium">{field.title}</Label>
                    {field.description && (
                      <p className="text-xs text-[var(--text-muted)] mt-0.5">{field.description}</p>
                    )}
                  </div>
                  {hasProviderDefault && (
                    <div className="flex items-center gap-1.5 shrink-0">
                      <span className="text-xs text-[var(--text-muted)]">Default</span>
                      <Switch
                        checked={isUsingDefault}
                        onCheckedChange={(v) =>
                          setUseDefaults((prev) => ({ ...prev, [field.key]: v }))
                        }
                      />
                    </div>
                  )}
                </div>

                {isSlider ? (
                  <div className="flex items-center gap-3">
                    <Slider
                      min={field.minimum!}
                      max={field.maximum!}
                      step={field.type === 'integer' ? 1 : 0.1}
                      value={[getNumericValue(field)]}
                      disabled={isUsingDefault}
                      onValueChange={([v]) => setParam(field.key, v)}
                      className="flex-1"
                    />
                    <span className="text-sm text-[var(--text-secondary)] w-12 text-right tabular-nums">
                      {getNumericValue(field).toFixed(field.type === 'integer' ? 0 : 1)}
                    </span>
                  </div>
                ) : (
                  <Input
                    type={isNumericField(field) ? 'number' : 'text'}
                    value={effectiveValue !== undefined && effectiveValue !== null ? String(effectiveValue) : ''}
                    disabled={isUsingDefault}
                    placeholder={
                      field.default !== undefined && field.default !== null
                        ? `Default: ${field.default}`
                        : 'Not set'
                    }
                    onChange={(e) => {
                      const raw = e.target.value
                      if (isNumericField(field)) {
                        setParam(field.key, raw === '' ? undefined : Number(raw))
                      } else {
                        setParam(field.key, raw)
                      }
                    }}
                    className={isUsingDefault ? 'bg-[var(--surface-3)] text-[var(--text-muted)]' : ''}
                  />
                )}
              </div>
            )
          })}
        </div>

        <SheetFooter className="mt-4 pt-4 border-t border-[var(--border-muted)]">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={updateInstance.isPending}>
            {updateInstance.isPending ? 'Saving...' : 'Save'}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}
