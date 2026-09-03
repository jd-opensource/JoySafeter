'use client'

import { AlertCircle, CheckCircle2, KeyRound, RefreshCw } from 'lucide-react'
import { useState } from 'react'

import { ModelConnectionSelectionFlow } from '@/components/managed/llm/model-connection-selection-flow'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useTranslation } from '@/lib/i18n'
import type { CredentialId } from '@/types/entity-id'
import type { Credential, CredentialDetail } from '@/types/managed'

interface RequiredModelConnectionControlProps {
  engineId?: string
  modelConsumerId?: string
  value: CredentialId | ''
  credentials: Credential[]
  loading: boolean
  loadError: boolean
  disabled?: boolean
  onChange: (value: CredentialId | '') => void
  onCreated: (credential: CredentialDetail) => void
  onRetry: () => void
}

export function RequiredModelConnectionControl({
  engineId,
  modelConsumerId,
  value,
  credentials,
  loading,
  loadError,
  disabled = false,
  onChange,
  onCreated,
  onRetry,
}: RequiredModelConnectionControlProps) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const selected = credentials.find((credential) => credential.id === value) ?? null
  const metadata = selected
    ? [selected.provider, selected.protocol, selected.model].filter(Boolean).join(' · ')
    : ''

  return (
    <>
      <div className="mx-5 mt-4 rounded-xl border border-border bg-card p-3 shadow-sm">
        {loading ? (
          <div className="flex items-center gap-3 text-sm text-muted-foreground">
            <RefreshCw className="h-4 w-4 animate-spin" />
            {t('managed.llm.loadingConfigurations')}
          </div>
        ) : loadError ? (
          <div className="flex items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-3 text-sm text-destructive">
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{t('managed.llm.configurationLoadFailed')}</span>
            </div>
            <Button type="button" variant="outline" size="sm" onClick={onRetry}>
              <RefreshCw className="mr-1 h-3.5 w-3.5" />
              {t('common.retry')}
            </Button>
          </div>
        ) : selected ? (
          <div className="flex items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-3">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-600">
                <CheckCircle2 className="h-4 w-4" />
              </span>
              <div className="min-w-0">
                <p className="text-xs text-muted-foreground">
                  {t('managed.skills.aiAuthor.modelConnection.selected')}
                </p>
                <p className="truncate text-sm font-medium text-foreground">{selected.name}</p>
                {metadata ? (
                  <p className="truncate text-xs text-muted-foreground">{metadata}</p>
                ) : null}
              </div>
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={disabled}
              onClick={() => setOpen(true)}
            >
              {t('managed.skills.aiAuthor.modelConnection.change')}
            </Button>
          </div>
        ) : (
          <div className="flex items-start justify-between gap-4">
            <div className="flex min-w-0 gap-3">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-amber-500/10 text-amber-600">
                <KeyRound className="h-4 w-4" />
              </span>
              <div>
                <p className="text-sm font-medium text-foreground">
                  {t('managed.skills.aiAuthor.modelConnection.required')}
                </p>
                <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                  {t('managed.skills.aiAuthor.modelConnection.requiredHint')}
                </p>
              </div>
            </div>
            <Button type="button" size="sm" disabled={disabled} onClick={() => setOpen(true)}>
              {credentials.length > 0
                ? t('managed.skills.aiAuthor.modelConnection.select')
                : t('managed.llm.createConfiguration')}
            </Button>
          </div>
        )}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t('managed.skills.aiAuthor.modelConnection.dialogTitle')}</DialogTitle>
            <DialogDescription>
              {t('managed.skills.aiAuthor.modelConnection.dialogDescription')}
            </DialogDescription>
          </DialogHeader>
          <ModelConnectionSelectionFlow
            engineId={engineId}
            modelConsumerId={modelConsumerId}
            value={value}
            disabled={disabled}
            onSelect={(credentialId) => {
              onChange(credentialId)
              if (credentialId) setOpen(false)
            }}
            onCreated={(credential) => {
              onCreated(credential)
              setOpen(false)
            }}
          />
        </DialogContent>
      </Dialog>
    </>
  )
}
