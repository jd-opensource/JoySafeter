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
import { useCreateCustomProvider } from '@/hooks/queries/models'
import { useToast } from '@/hooks/use-toast'

import { parseJsonSchema } from './schema-utils'

interface AddCustomModelDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  credentialSchema?: Record<string, any>
  onCreated?: (providerName: string) => void
}

export function AddCustomModelDialog({ open, onOpenChange, credentialSchema, onCreated }: AddCustomModelDialogProps) {
  const createCustomProvider = useCreateCustomProvider()
  const { toast } = useToast()
  const [modelName, setModelName] = useState('')
  const [credFields, setCredFields] = useState<Record<string, string>>({})

  const formFields = useMemo(
    () => parseJsonSchema(credentialSchema),
    [credentialSchema],
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
      const result = await createCustomProvider.mutateAsync({
        model_name: modelName.trim(),
        credentials,
        validate: true,
      })
      toast({ title: '模型添加成功' })
      setModelName('')
      setCredFields({})
      onOpenChange(false)
      onCreated?.(result.provider_name)
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
            添加一个新的自定义模型实例
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
          <Button onClick={handleAdd} disabled={createCustomProvider.isPending || !canSubmit}>
            {createCustomProvider.isPending ? '添加中...' : '添加'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
