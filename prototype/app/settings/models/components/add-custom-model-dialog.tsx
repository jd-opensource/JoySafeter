'use client'

import { Loader2 } from 'lucide-react'
import React, { useMemo, useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
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
import type { ModelProvider } from '@/hooks/queries/models'
import { useCreateCredential } from '@/hooks/queries/models'
import { useToast } from '@/hooks/use-toast'
import { useTranslation } from '@/lib/i18n'

const CUSTOM_CREDENTIAL_FIELDS = [
  { key: 'protocol_type', label: '协议类型', type: 'string' as const, required: true, enum: ['openai', 'anthropic', 'gemini'], enumNames: ['OpenAI', 'Anthropic (Claude)', 'Google Gemini'] },
  { key: 'api_key', label: 'API Key', type: 'string' as const, required: true },
  { key: 'base_url', label: 'Base URL', type: 'string' as const, required: false },
]

interface AddCustomModelDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** 自定义模板供应商，用于展示；不传则用内置字段 */
  provider?: ModelProvider | null
}

export function AddCustomModelDialog({
  open,
  onOpenChange,
  provider,
}: AddCustomModelDialogProps) {
  const { t } = useTranslation()
  const { toast } = useToast()
  const createCredential = useCreateCredential()

  const formFields = useMemo(() => {
    if (provider?.credential_schema && typeof provider.credential_schema === 'object' && 'properties' in provider.credential_schema) {
      const schema = provider.credential_schema as { properties?: Record<string, { title?: string; type?: string; enum?: string[]; enumNames?: string[] }>; required?: string[] }
      return Object.entries(schema.properties || {}).map(([key, value]) => ({
        key,
        label: value.title || key,
        type: (value.type || 'string') as 'string' | 'number',
        required: (schema.required || []).includes(key),
        enum: value.enum,
        enumNames: value.enumNames,
      }))
    }
    return CUSTOM_CREDENTIAL_FIELDS
  }, [provider?.credential_schema])

  const [formData, setFormData] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {}
    formFields.forEach((f: { key: string; enum?: string[] }) => {
      if (f.enum?.length) initial[f.key] = f.enum[0]
      else initial[f.key] = ''
    })
    if (!('api_key' in initial)) initial['api_key'] = ''
    return initial
  })
  const [modelName, setModelName] = useState('')
  const [displayName, setDisplayName] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!modelName?.trim()) {
      toast({
        variant: 'destructive',
        description: t('settings.customModelNameRequired', { defaultValue: '请输入模型名称' }),
      })
      return
    }
    const credentials: Record<string, string> = {}
    formFields.forEach((f: { key: string; required?: boolean }) => {
      const v = formData[f.key]?.trim()
      if (f.required && !v) return
      if (v) credentials[f.key] = v
    })
    if (!credentials.api_key) {
      toast({
        variant: 'destructive',
        description: t('settings.apiKeyRequired', { defaultValue: '请输入 API Key' }),
      })
      return
    }
    try {
      await createCredential.mutateAsync({
        provider_name: 'custom',
        credentials,
        validate: true,
        model_name: modelName.trim(),
        providerDisplayName: displayName.trim() || undefined,
      })
      toast({
        variant: 'success',
        description: t('settings.customModelAdded', { defaultValue: '已添加自定义模型' }),
      })
      setModelName('')
      setDisplayName('')
      setFormData(() => {
        const initial: Record<string, string> = {}
        formFields.forEach((f: { key: string; enum?: string[] }) => {
          if (f.enum?.length) initial[f.key] = f.enum[0]
          else initial[f.key] = ''
        })
        return initial
      })
      onOpenChange(false)
    } catch (error) {
      toast({
        variant: 'destructive',
        title: t('settings.error'),
        description: error instanceof Error ? error.message : t('settings.failedToAddCustomModel', { defaultValue: '添加失败' }),
      })
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md p-0 gap-0 overflow-hidden bg-white border border-gray-200 rounded-2xl shadow-2xl">
        <DialogHeader className="px-6 py-4 border-b border-gray-100">
          <DialogTitle className="font-bold text-sm">
            {t('settings.addCustomModel', { defaultValue: '添加自定义模型' })}
          </DialogTitle>
          <DialogDescription className="text-xs text-muted-foreground mt-0.5">
            {t('settings.addCustomModelDescriptionFull', {
              defaultValue: '填写凭据与模型名称，一步添加一个自定义模型',
            })}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="flex-col flex">
          <div className="px-6 py-4 space-y-4 max-h-[60vh] overflow-y-auto">
            {formFields.map((field: { key: string; label: string; type: string; required?: boolean; enum?: string[]; enumNames?: string[] }) => (
              <div key={field.key}>
                <Label htmlFor={`custom-${field.key}`}>
                  {field.label}
                  {field.required ? <span className="text-destructive ml-1">*</span> : null}
                </Label>
                {field.enum?.length ? (
                  <Select
                    value={formData[field.key] || field.enum[0]}
                    onValueChange={(v) => setFormData((prev) => ({ ...prev, [field.key]: v }))}
                  >
                    <SelectTrigger id={`custom-${field.key}`} className="mt-1">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent position="popper" className="z-[10000001]">
                      {field.enum.map((opt, i) => (
                        <SelectItem key={opt} value={opt}>
                          {(field.enumNames && field.enumNames[i]) || opt}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <Input
                    id={`custom-${field.key}`}
                    type={field.key === 'api_key' ? 'password' : 'text'}
                    value={formData[field.key] ?? ''}
                    onChange={(e) => setFormData((prev) => ({ ...prev, [field.key]: e.target.value }))}
                    placeholder={field.key === 'base_url' ? 'https://api.openai.com/v1（可选）' : ''}
                    className="mt-1"
                  />
                )}
              </div>
            ))}
            <div>
              <Label htmlFor="custom-model-name">
                {t('settings.modelName', { defaultValue: '模型名称' })}
                <span className="text-destructive ml-1">*</span>
              </Label>
              <Input
                id="custom-model-name"
                type="text"
                value={modelName}
                onChange={(e) => setModelName(e.target.value)}
                placeholder="gpt-4o-mini"
                required
                className="mt-1"
              />
              <p className="text-xs text-muted-foreground mt-1">
                {t('settings.modelNameRequiredHint', {
                  defaultValue: '如 gpt-4o-mini、claude-3-5-sonnet、gemini-1.5-flash',
                })}
              </p>
            </div>
            <div>
              <Label htmlFor="custom-display-name">{t('settings.providerDisplayName', { defaultValue: '显示名称' })}（可选）</Label>
              <Input
                id="custom-display-name"
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder={t('settings.providerDisplayNamePlaceholder', { defaultValue: '留空则使用模型名' })}
                className="mt-1"
              />
            </div>
          </div>
          <DialogFooter className="border-t border-gray-100 px-6 py-4 flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t('settings.cancel')}
            </Button>
            <Button
              type="submit"
              disabled={createCredential.isPending || !modelName.trim() || !formData.api_key?.trim()}
            >
              {createCredential.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {t('settings.add', { defaultValue: '添加' })}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
