'use client'

import { KeyRound, Loader2 } from 'lucide-react'
import React, { useState, useMemo } from 'react'

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
import type { ModelProvider, ModelCredential } from '@/hooks/queries/models'
import { useCreateCredential, useValidateCredential } from '@/hooks/queries/models'
import { useToast } from '@/hooks/use-toast'
import { useTranslation } from '@/lib/i18n'

interface ModelCredentialDialogProps {
  provider: ModelProvider
  credential?: ModelCredential
  workspaceId?: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function ModelCredentialDialog({
  provider,
  credential,
  workspaceId,
  open,
  onOpenChange,
}: ModelCredentialDialogProps) {
  const { t } = useTranslation()
  const { toast } = useToast()
  const createCredential = useCreateCredential()
  const validateCredential = useValidateCredential()
  const [validating, setValidating] = useState(false)

  // Parse form fields from credential_schema
  const formFields = useMemo(() => {
    if (!provider.credential_schema) return []

    // credential_schema may be a JSON Schema object
    // Simplified here, assuming it's an object with properties
    const schema = provider.credential_schema
    if (schema && typeof schema === 'object' && 'properties' in schema) {
      return Object.entries((schema as any).properties || {}).map(([key, value]: [string, any]) => ({
        key,
        label: value.title || value.label || key,
        type: value.type || 'string',
        required: (schema as any).required?.includes(key) || false,
        description: value.description,
        default: value.default,
      }))
    }

    // If no properties, return empty array
    return []
  }, [provider.credential_schema])

  const [formData, setFormData] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {}
    formFields.forEach(field => {
      if (field.default !== undefined) {
        initial[field.key] = String(field.default)
      } else {
        // Don't display existing sensitive information in edit mode
        initial[field.key] = ''
      }
    })
    // If no form fields, at least provide an api_key field
    if (formFields.length === 0) {
      initial['api_key'] = ''
    }
    return initial
  })

  // Update form data when formFields changes
  React.useEffect(() => {
    const initial: Record<string, string> = {}
    formFields.forEach(field => {
      if (field.default !== undefined) {
        initial[field.key] = String(field.default)
      } else {
        initial[field.key] = formData[field.key] || ''
      }
    })
    if (formFields.length === 0) {
      initial['api_key'] = formData['api_key'] || ''
    }
    setFormData(initial)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [formFields.length])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    // Filter out empty values
    const filteredData: Record<string, string> = {}
    Object.entries(formData).forEach(([key, value]) => {
      if (value && value.trim()) {
        filteredData[key] = value.trim()
      }
    })

    try {
      await createCredential.mutateAsync({
        provider_name: provider.provider_name,
        credentials: filteredData,
        workspaceId,
        validate: true,
      })

      // Use concise message on success
      toast({
        variant: 'success',
        description: credential
          ? t('settings.credentialUpdated')
          : t('settings.credentialCreated'),
      })

      onOpenChange(false)
      // Reset form
      const initial: Record<string, string> = {}
      formFields.forEach(field => {
        if (field.default !== undefined) {
          initial[field.key] = String(field.default)
        } else {
          initial[field.key] = ''
        }
      })
      setFormData(initial)
    } catch (error) {
      toast({
        title: t('settings.error'),
        description: error instanceof Error
          ? error.message
          : (credential ? t('settings.failedToUpdateCredential') : t('settings.failedToCreateCredential')),
        variant: 'destructive',
      })
    }
  }

  const handleValidate = async () => {
    setValidating(true)
    try {
      if (credential?.id) {
        await validateCredential.mutateAsync(credential.id)
        // Use concise message on success
        toast({
          variant: 'success',
          description: t('settings.credentialValidated'),
        })
      }
    } catch (error) {
      toast({
        title: t('settings.error'),
        description: t('settings.failedToValidateCredential'),
        variant: 'destructive',
      })
    } finally {
      setValidating(false)
    }
  }

  const dialogContentClassName =
    'sm:max-w-lg p-0 gap-0 overflow-hidden bg-white border border-gray-200 rounded-2xl shadow-2xl flex flex-col max-h-[85vh]'
  const headerClassName = 'px-6 py-4 border-b border-gray-100 shrink-0 flex flex-row items-center gap-3'
  const bodyClassName = 'p-6 space-y-4 max-h-[60vh] overflow-y-auto'
  const footerClassName = 'border-t border-gray-100 px-6 py-4 flex flex-col-reverse sm:flex-row sm:justify-end gap-2'

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={dialogContentClassName}>
        <DialogHeader className={headerClassName}>
          <div className="p-1.5 rounded-lg border border-gray-50 shadow-sm shrink-0 bg-violet-50 text-violet-600">
            <KeyRound size={14} />
          </div>
          <div className="flex flex-col min-w-0">
            <DialogTitle className="font-bold text-sm leading-tight">
              {provider.display_name} {t('settings.configureCredential')}
            </DialogTitle>
            <DialogDescription className="text-muted-foreground text-xs mt-0.5">
              {t('settings.modelProviderDescription')}
            </DialogDescription>
          </div>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="flex flex-col flex-1 min-h-0">
          <div className={bodyClassName}>
            {formFields.length === 0 ? (
              <div>
                <Label htmlFor="api_key">{t('settings.apiKeyLabel', { defaultValue: 'API Key' })}</Label>
                <Input
                  id="api_key"
                  type="password"
                  value={formData.api_key || ''}
                  onChange={(e) => setFormData({ ...formData, api_key: e.target.value })}
                  placeholder={t('settings.enterApiKey', { defaultValue: 'Enter API key' })}
                  required
                  className="mt-1"
                />
              </div>
            ) : (
              formFields.map(field => (
                <div key={field.key}>
                  <Label htmlFor={field.key}>
                    {field.label}
                    {field.required && <span className="text-destructive ml-1">*</span>}
                  </Label>
                  <Input
                    id={field.key}
                    type={field.type === 'string' ? (field.key.toLowerCase().includes('key') || field.key.toLowerCase().includes('secret') ? 'password' : 'text') : field.type}
                    value={formData[field.key] || ''}
                    onChange={(e) => setFormData({ ...formData, [field.key]: e.target.value })}
                    placeholder={field.description || t('settings.enterField', { field: field.label, defaultValue: `Enter ${field.label.toLowerCase()}` })}
                    required={field.required}
                    className="mt-1"
                  />
                  {field.description && (
                    <p className="text-xs text-muted-foreground mt-1">{field.description}</p>
                  )}
                </div>
              ))
            )}
          </div>
          <DialogFooter className={footerClassName}>
            {credential?.id && (
              <Button
                type="button"
                variant="outline"
                onClick={handleValidate}
                disabled={validating}
              >
                {validating && <Loader2 className="mr-2 w-4 h-4 animate-spin" />}
                {t('settings.validateCredential')}
              </Button>
            )}
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t('settings.cancel')}
            </Button>
            <Button type="submit" disabled={createCredential.isPending}>
              {createCredential.isPending && <Loader2 className="mr-2 w-4 h-4 animate-spin" />}
              {t('settings.save')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
