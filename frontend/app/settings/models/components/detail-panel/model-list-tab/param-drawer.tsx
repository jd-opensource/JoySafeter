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

interface ParamField {
  key: string
  title: string
  description?: string
  type: string
  default?: number | null
  minimum?: number
  maximum?: number
}

function parseConfigSchema(schema: Record<string, any> | null): ParamField[] {
  if (!schema) return []

  // config_schemas.chat is { type: "object", properties: { ... } }
  const properties =
    schema.properties && typeof schema.properties === 'object'
      ? schema.properties
      : schema // fallback: treat schema itself as flat key-value if no properties wrapper

  if (!properties || typeof properties !== 'object') return []

  // If we accidentally got the wrapper, skip non-property keys
  if ('type' in properties && 'properties' in properties) {
    return parseConfigSchema(properties)
  }

  return Object.entries(properties).map(([key, prop]: [string, any]) => ({
    key,
    title: prop.title || key,
    description: prop.description,
    type: prop.type || 'number',
    default: prop.default,
    minimum: prop.minimum,
    maximum: prop.maximum,
  }))
}

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

  const fields = useMemo(() => parseConfigSchema(configSchema), [configSchema])

  // Reset state when drawer opens
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
      toast({ title: '参数已保存' })
      onOpenChange(false)
    } catch (err) {
      toast({
        variant: 'destructive',
        title: '保存失败',
        description: err instanceof Error ? err.message : '请重试',
      })
    }
  }

  const setParam = (key: string, value: unknown) => {
    setParams((prev) => ({ ...prev, [key]: value }))
  }

  const getEffectiveValue = (field: ParamField): number | string => {
    if (useDefaults[field.key]) {
      const dv = providerDefaults[field.key]
      return dv !== undefined ? Number(dv) : (field.default ?? '')
    }
    const v = params[field.key]
    return v !== undefined ? Number(v) : (field.default ?? '')
  }

  if (fields.length === 0) {
    return (
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent side="right" className="w-[400px] sm:w-[480px]">
          <SheetHeader>
            <SheetTitle>参数设置 — {modelName}</SheetTitle>
            <SheetDescription>调整模型运行参数</SheetDescription>
          </SheetHeader>
          <div className="flex h-40 items-center justify-center text-[var(--text-muted)]">
            <p className="text-sm">该模型暂无可配置参数</p>
          </div>
        </SheetContent>
      </Sheet>
    )
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-[400px] sm:w-[480px] flex flex-col">
        <SheetHeader>
          <SheetTitle>参数设置 — {modelName}</SheetTitle>
          <SheetDescription>调整模型运行参数，如 temperature、max_tokens 等</SheetDescription>
        </SheetHeader>

        <div className="mt-4 flex-1 space-y-5 overflow-y-auto pr-1">
          {fields.map((field) => {
            const isUsingDefault = useDefaults[field.key] ?? false
            const hasProviderDefault = providerDefaults[field.key] !== undefined
            const effectiveValue = getEffectiveValue(field)
            const isSlider =
              (field.type === 'number' || field.type === 'integer') &&
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
                      <span className="text-xs text-[var(--text-muted)]">默认</span>
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
                      value={[typeof effectiveValue === 'number' ? effectiveValue : 0]}
                      disabled={isUsingDefault}
                      onValueChange={([v]) => setParam(field.key, v)}
                      className="flex-1"
                    />
                    <span className="text-sm text-[var(--text-secondary)] w-12 text-right tabular-nums">
                      {typeof effectiveValue === 'number' ? effectiveValue.toFixed(field.type === 'integer' ? 0 : 1) : '—'}
                    </span>
                  </div>
                ) : (
                  <Input
                    type={field.type === 'integer' ? 'number' : 'text'}
                    value={effectiveValue !== undefined ? String(effectiveValue) : ''}
                    disabled={isUsingDefault}
                    placeholder={field.default !== undefined && field.default !== null ? `默认: ${field.default}` : '未设置'}
                    onChange={(e) => {
                      const raw = e.target.value
                      if (field.type === 'number' || field.type === 'integer') {
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
            取消
          </Button>
          <Button onClick={handleSave} disabled={updateInstance.isPending}>
            {updateInstance.isPending ? '保存中...' : '保存'}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}
