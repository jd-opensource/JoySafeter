'use client'

import { useMemo, useState } from 'react'

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
import { useCreateCredential } from '@/hooks/queries/models'
import { useToast } from '@/hooks/use-toast'
import type { ModelProvider } from '@/types/models'

interface SchemaField {
  key: string
  title: string
  description?: string
  type: string
  required: boolean
  enum?: string[]
  enumNames?: string[]
}

function parseCredentialSchema(schema: Record<string, any> | undefined): SchemaField[] {
  if (!schema || typeof schema !== 'object' || !('properties' in schema)) return []

  const properties = schema.properties as Record<string, any> | undefined
  if (!properties) return []

  const requiredFields: string[] = Array.isArray(schema.required) ? schema.required : []

  return Object.entries(properties).map(([key, prop]) => ({
    key,
    title: prop.title || key,
    description: prop.description,
    type: prop.type || 'string',
    required: requiredFields.includes(key) || prop.required === true,
    enum: prop.enum,
    enumNames: prop.enumNames,
  }))
}

interface AddCustomModelDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  provider: ModelProvider
}

export function AddCustomModelDialog({ open, onOpenChange, provider }: AddCustomModelDialogProps) {
  const createCredential = useCreateCredential()
  const { toast } = useToast()
  const [modelName, setModelName] = useState('')
  const [credFields, setCredFields] = useState<Record<string, string>>({})

  const formFields = useMemo(
    () => parseCredentialSchema(provider.credential_schema),
    [provider.credential_schema],
  )

  const canSubmit =
    modelName.trim() !== '' &&
    formFields
      .filter((f) => f.required)
      .every((f) => credFields[f.key]?.trim())

  const handleAdd = async () => {
    if (!canSubmit) return
    const credentials: Record<string, string> = {}
    for (const field of formFields) {
      const val = credFields[field.key]?.trim()
      if (val) credentials[field.key] = val
    }
    try {
      await createCredential.mutateAsync({
        provider_name: provider.provider_name,
        credentials,
        model_name: modelName.trim(),
        validate: true,
      })
      toast({ title: '模型添加成功' })
      setModelName('')
      setCredFields({})
      onOpenChange(false)
    } catch (err) {
      toast({
        variant: 'destructive',
        title: '添加模型失败',
        description: err instanceof Error ? err.message : '请检查模型信息后重试',
      })
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>添加自定义模型</DialogTitle>
          <DialogDescription>
            通过 {provider.display_name} 添加一个新的模型实例
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <Label htmlFor="model-name">
              模型名称
              <span className="text-destructive ml-1">*</span>
            </Label>
            <Input
              id="model-name"
              placeholder="如 gpt-4o, claude-3-5-sonnet"
              value={modelName}
              onChange={(e) => setModelName(e.target.value)}
            />
          </div>

          {formFields.map((field) => (
            <div key={field.key} className="space-y-1.5">
              <Label htmlFor={`custom-${field.key}`}>
                {field.title}
                {field.required && <span className="text-destructive ml-1">*</span>}
              </Label>
              {field.enum ? (
                <Select
                  value={credFields[field.key] || ''}
                  onValueChange={(val) =>
                    setCredFields((f) => ({ ...f, [field.key]: val }))
                  }
                >
                  <SelectTrigger>
                    <SelectValue placeholder={`选择${field.title}`} />
                  </SelectTrigger>
                  <SelectContent>
                    {field.enum.map((val, i) => (
                      <SelectItem key={val} value={val}>
                        {field.enumNames?.[i] || val}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <Input
                  id={`custom-${field.key}`}
                  type={
                    field.key.toLowerCase().includes('key') ||
                    field.key.toLowerCase().includes('secret')
                      ? 'password'
                      : 'text'
                  }
                  placeholder={field.description}
                  value={credFields[field.key] ?? ''}
                  onChange={(e) =>
                    setCredFields((f) => ({ ...f, [field.key]: e.target.value }))
                  }
                />
              )}
              {field.description && !field.enum && (
                <p className="text-xs text-muted-foreground">{field.description}</p>
              )}
            </div>
          ))}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={handleAdd} disabled={createCredential.isPending || !canSubmit}>
            {createCredential.isPending ? '添加中...' : '添加'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
