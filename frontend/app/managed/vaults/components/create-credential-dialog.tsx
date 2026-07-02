'use client'

import { useState } from 'react'
import { useTranslation } from '@/lib/i18n'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { managedPost } from '@/lib/api-client'
import { toastOperationError } from '@/lib/managed/errors'
import type { VaultCredential } from '@/types/managed'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'

interface CreateCredentialDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  vaultId: string
  queryKey: unknown[]
}

type CredType = 'mcp_oauth' | 'static_bearer'

export function CreateCredentialDialog({
  open,
  onOpenChange,
  vaultId,
  queryKey,
}: CreateCredentialDialogProps) {
  const { t } = useTranslation()
  const [name, setName] = useState('')
  const [credentialType, setCredentialType] = useState<CredType>('mcp_oauth')
  const [mcpServerUrl, setMcpServerUrl] = useState('')
  const [tokenValue, setTokenValue] = useState('')
  const queryClient = useQueryClient()

  const mutation = useMutation({
    mutationFn: () =>
      managedPost<VaultCredential>(`/vaults/${vaultId}/credentials`, {
        name: name || undefined,
        credential_type: credentialType,
        mcp_server_url: mcpServerUrl,
        token_value: tokenValue,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey })
      resetForm()
      onOpenChange(false)
    },
    onError: (error) => {
      toastOperationError(t, error, 'managed.vaults.cred.createFailed')
    },
  })

  const resetForm = () => {
    setName('')
    setCredentialType('mcp_oauth')
    setMcpServerUrl('')
    setTokenValue('')
    mutation.reset()
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!mcpServerUrl.trim()) return
    // URL scheme validation
    const { validateUrlScheme } = require('@/lib/utils/url-validation')
    const urlError = validateUrlScheme(mcpServerUrl.trim())
    if (urlError) {
      alert(urlError)
      return
    }
    if (credentialType === 'static_bearer' && !tokenValue.trim()) return
    mutation.mutate()
  }

  const handleOpenChange = (next: boolean) => {
    if (!next) resetForm()
    onOpenChange(next)
  }

  const isOAuth = credentialType === 'mcp_oauth'

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('managed.vaults.cred.createTitle')}</DialogTitle>
          <DialogDescription>{t('managed.vaults.cred.createDescription')}</DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="mt-2 space-y-4">
          <div className="space-y-1.5">
            <label htmlFor="cred-name" className="text-sm font-medium">
              {t('managed.vaults.cred.name')}{' '}
              <span className="font-normal text-muted-foreground">
                {t('managed.vaults.cred.nameOptional')}
              </span>
            </label>
            <Input
              id="cred-name"
              placeholder={t('managed.vaults.cred.namePlaceholder')}
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-medium">{t('managed.vaults.cred.type')}</label>
            <div className="flex w-fit overflow-hidden rounded-md border border-border">
              <button
                type="button"
                onClick={() => setCredentialType('mcp_oauth')}
                className={`px-3 py-1.5 text-sm font-medium transition-colors ${
                  isOAuth
                    ? 'bg-foreground text-background'
                    : 'bg-background text-foreground hover:bg-accent'
                }`}
              >
                OAuth
              </button>
              <button
                type="button"
                onClick={() => setCredentialType('static_bearer')}
                className={`border-l border-border px-3 py-1.5 text-sm font-medium transition-colors ${
                  !isOAuth
                    ? 'bg-foreground text-background'
                    : 'bg-background text-foreground hover:bg-accent'
                }`}
              >
                {t('managed.vaults.cred.bearerToken')}
              </button>
            </div>
          </div>

          <div className="space-y-1.5">
            <label htmlFor="cred-url" className="text-sm font-medium">
              {t('managed.vaults.cred.mcpServer')}
            </label>
            <Input
              id="cred-url"
              placeholder="https://mcp.example.com"
              value={mcpServerUrl}
              onChange={(e) => setMcpServerUrl(e.target.value)}
            />
          </div>

          {!isOAuth && (
            <div className="space-y-1.5">
              <label htmlFor="cred-token" className="text-sm font-medium">
                {t('managed.vaults.cred.token')}
              </label>
              <Input
                id="cred-token"
                type="password"
                placeholder="sk-..."
                value={tokenValue}
                onChange={(e) => setTokenValue(e.target.value)}
              />
            </div>
          )}

          <div className="flex justify-end">
            <Button
              type="submit"
              disabled={
                !mcpServerUrl.trim() || (!isOAuth && !tokenValue.trim()) || mutation.isPending
              }
            >
              {mutation.isPending
                ? t('managed.vaults.cred.connecting')
                : t('managed.vaults.cred.connect')}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
