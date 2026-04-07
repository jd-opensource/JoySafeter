'use client'

import { useEffect, useMemo, useState } from 'react'

import { Button } from '@/components/ui/button'
import { UnifiedDialog } from '@/components/ui/unified-dialog'
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
import { useCreateCredential } from '@/hooks/queries/models'
import type { ModelCredential, ModelProvider } from '@/types/models'

import { parseJsonSchema } from './schema-utils'

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

  const canSubmit = isDirty && formFields
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
      toast({ title: 'Credential saved successfully' })
      onOpenChange(false)
    } catch (err) {
      toast({
        variant: 'destructive',
        title: 'Failed to save credential',
        description: err instanceof Error ? err.message : 'Please check credential info and try again',
      })
    }
  }

  return (
    <UnifiedDialog
      open={open}
      onOpenChange={onOpenChange}
      maxWidth="md"
      title={`Configure ${provider.display_name} Credential`}
      description={provider.description}
      showContentBg={false}
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={createCredential.isPending || !canSubmit}>
            {createCredential.isPending ? 'Saving...' : 'Save'}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
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
                  <SelectValue placeholder={`Select ${field.title}`} />
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
    </UnifiedDialog>
  )
}
