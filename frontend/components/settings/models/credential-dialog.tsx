'use client'

import { useEffect, useMemo, useState } from 'react'

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
import { useToast } from '@/hooks/use-toast'
import { useCreateCredential, useValidateCredential, useDeleteCredential } from '@/hooks/queries/models'
import type { ModelCredential, ModelProvider } from '@/types/models'

import { parseJsonSchema } from './schema-utils'
import type { SchemaField } from './schema-utils'

interface CredentialDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  provider: ModelProvider
  existingCredential?: ModelCredential
}

export function CredentialDialog({
  open,
  onOpenChange,
  provider,
  existingCredential,
}: CredentialDialogProps) {
  const createCredential = useCreateCredential()
  const validateCredential = useValidateCredential()
  const { toast } = useToast()
  const [fields, setFields] = useState<Record<string, string>>({})
  const [validating, setValidating] = useState(false)
  const deleteCredential = useDeleteCredential()

  const formFields = useMemo(
    () => parseJsonSchema(provider.credential_schema),
    [provider.credential_schema],
  )

  useEffect(() => {
    if (open) {
      const initial: Record<string, string> = {}
      for (const field of formFields) {
        initial[field.key] = existingCredential?.credentials?.[field.key] ?? ''
      }
      setFields(initial)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, formFields])

  const isDirty = useMemo(() => {
    for (const field of formFields) {
      const initialValue = existingCredential?.credentials?.[field.key] ?? ''
      if ((fields[field.key] || '') !== initialValue) {
        return true
      }
    }
    return false
  }, [fields, formFields, existingCredential])

  const canSubmit = formFields
    .filter((f) => f.required)
    .every((f) => fields[f.key]?.trim())

  const handleSave = async () => {
    const credentials: Record<string, string> = {}
    for (const field of formFields) {
      const val = fields[field.key]?.trim()
      if (val) credentials[field.key] = val
    }
    try {
      await createCredential.mutateAsync({
        provider_name: provider.provider_name,
        credentials,
        validate: true,
      })
      toast({ title: '凭证保存成功' })
      onOpenChange(false)
    } catch (err) {
      toast({
        variant: 'destructive',
        title: '保存凭证失败',
        description: err instanceof Error ? err.message : '请检查凭证信息后重试',
      })
    }
  }

  const handleValidate = async () => {
    if (!existingCredential) return
    setValidating(true)
    try {
      const result = await validateCredential.mutateAsync(existingCredential.id)
      if (result.is_valid) {
        toast({ title: '凭证验证通过' })
      } else {
        toast({
          variant: 'destructive',
          title: '凭证验证失败',
          description: result.error || '凭证无效',
        })
      }
    } catch (err) {
      toast({
        variant: 'destructive',
        title: '验证失败',
        description: err instanceof Error ? err.message : '验证请求失败',
      })
    } finally {
      setValidating(false)
    }
  }

  const handleClearCredential = async () => {
    if (!existingCredential) return
    try {
      await deleteCredential.mutateAsync(existingCredential.id)
      toast({ title: '凭证已清除' })
      onOpenChange(false)
    } catch (err) {
      toast({
        variant: 'destructive',
        title: '清除凭证失败',
        description: err instanceof Error ? err.message : '请稍后重试',
      })
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>配置 {provider.display_name} 凭证</DialogTitle>
          {provider.description && (
            <DialogDescription>{provider.description}</DialogDescription>
          )}
        </DialogHeader>

        <div className="space-y-4 py-2">
          {formFields.map((field) => (
            <div key={field.key} className="space-y-1.5">
              <Label htmlFor={field.key}>
                {field.title}
                {field.required && <span className="text-destructive ml-1">*</span>}
              </Label>
              {field.enum ? (
                <Select
                  value={fields[field.key] || ''}
                  onValueChange={(val) =>
                    setFields((f) => ({ ...f, [field.key]: val }))
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
                  id={field.key}
                  type={
                    field.key.toLowerCase().includes('key') ||
                    field.key.toLowerCase().includes('secret')
                      ? 'password'
                      : 'text'
                  }
                  placeholder={field.description}
                  value={fields[field.key] ?? ''}
                  onChange={(e) =>
                    setFields((f) => ({ ...f, [field.key]: e.target.value }))
                  }
                />
              )}
              {field.description && !field.enum && (
                <p className="text-xs text-muted-foreground">{field.description}</p>
              )}
            </div>
          ))}
        </div>

        <DialogFooter className="gap-2">
          <div className="mr-auto flex gap-2">
            {existingCredential && (
              <Button
                variant="outline"
                onClick={handleValidate}
                disabled={validating || isDirty}
              >
                {validating ? '验证中...' : '重新验证'}
              </Button>
            )}
            {existingCredential && provider.provider_type !== 'custom' && (
              <Button
                variant="outline"
                onClick={handleClearCredential}
                disabled={deleteCredential.isPending}
                className="text-red-600 hover:text-red-700"
              >
                {deleteCredential.isPending ? '清除中...' : '清除认证'}
              </Button>
            )}
          </div>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={handleSave} disabled={createCredential.isPending || !canSubmit}>
            {createCredential.isPending ? '保存中...' : '保存'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
