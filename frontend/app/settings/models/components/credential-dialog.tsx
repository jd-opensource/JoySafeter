'use client'

import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useToast } from '@/hooks/use-toast'
import { useCreateCredential } from '@/hooks/queries/models'
import type { ModelCredential, ModelProvider } from '@/types/models'

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
  const { toast } = useToast()
  const [fields, setFields] = useState<Record<string, string>>({})

  const schema = provider.credential_schema ?? {}
  const schemaKeys = Object.keys(schema)

  useEffect(() => {
    if (open) {
      const initial: Record<string, string> = {}
      for (const key of schemaKeys) {
        initial[key] = existingCredential?.credentials?.[key] ?? ''
      }
      setFields(initial)
    }
  }, [open])

  const handleSave = async () => {
    const credentials: Record<string, string> = {}
    for (const key of schemaKeys) {
      if (fields[key]) credentials[key] = fields[key]
    }
    try {
      await createCredential.mutateAsync({
        provider_name: provider.provider_name,
        credentials,
        validate: true,
      })
      onOpenChange(false)
    } catch (err) {
      toast({
        variant: 'destructive',
        title: '保存凭证失败',
        description: err instanceof Error ? err.message : '请检查凭证信息后重试',
      })
    }
  }

  const isEditing = !!existingCredential

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[440px]">
        <DialogHeader>
          <DialogTitle>
            {isEditing ? '编辑凭证' : '配置凭证'} — {provider.display_name}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {schemaKeys.length === 0 ? (
            <p className="text-sm text-[var(--text-muted)]">该供应商无需配置凭证。</p>
          ) : (
            schemaKeys.map((key) => {
              const fieldDef = schema[key] ?? {}
              const label = fieldDef.title ?? key
              const placeholder = fieldDef.description ?? ''
              const isSecret =
                fieldDef.format === 'password' ||
                key.toLowerCase().includes('key') ||
                key.toLowerCase().includes('secret') ||
                key.toLowerCase().includes('token')

              return (
                <div key={key} className="space-y-1.5">
                  <Label className="text-sm font-medium">{label}</Label>
                  <Input
                    type={isSecret ? 'password' : 'text'}
                    value={fields[key] ?? ''}
                    onChange={(e) => setFields((prev) => ({ ...prev, [key]: e.target.value }))}
                    placeholder={placeholder}
                    autoComplete="off"
                  />
                </div>
              )
            })
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={handleSave} disabled={createCredential.isPending}>
            {createCredential.isPending ? '保存中...' : '保存并验证'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
