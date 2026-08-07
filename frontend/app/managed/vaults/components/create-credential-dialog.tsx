'use client'

import { useEffect, useRef, useState } from 'react'
import { useTranslation } from '@/lib/i18n'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { managedPost } from '@/lib/api-client'
import { apiResourcePath } from '@/lib/managed/api-paths'
import { toastOperationError } from '@/lib/managed/errors'
import { parseVaultCredentialResponse } from '@/lib/managed/vault-response-parsers'
import {
  managedRequestOptions,
  managedScopeKey,
  type ManagedRequestScope,
  useManagedRequestScope,
} from '@/lib/managed/request-scope'
import { validateUrlScheme } from '@/lib/utils/url-validation'
import { useProjectStore } from '@/stores/managed/project-store'
import { currentProjectAllowsWrite } from '@/hooks/managed/use-current-project-read-only'
import type { VaultId } from '@/types/entity-id'
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
  vaultId: VaultId
  queryKey: unknown[]
  canSubmit?: () => boolean
}

type CredType = 'mcp_oauth' | 'static_bearer'

interface CreateCredentialVariables {
  vaultId: VaultId
  queryKey: unknown[]
  payload: {
    name?: string
    credential_type: CredType
    mcp_server_url: string
    token_value: string
  }
  runId: number
  scope: string
  requestScope: ManagedRequestScope
}

export function CreateCredentialDialog({
  open,
  onOpenChange,
  vaultId,
  queryKey,
  canSubmit,
}: CreateCredentialDialogProps) {
  const { t } = useTranslation()
  const managedScope = useManagedRequestScope()
  const operationScope = `${managedScope.key}:${vaultId}`
  const createRunRef = useRef(0)
  const operationScopeRef = useRef(operationScope)
  const requestScopeRef = useRef<ManagedRequestScope>(managedScope)
  const [name, setName] = useState('')
  const [credentialType, setCredentialType] = useState<CredType>('mcp_oauth')
  const [mcpServerUrl, setMcpServerUrl] = useState('')
  const [tokenValue, setTokenValue] = useState('')
  const queryClient = useQueryClient()

  const getCurrentOperationScope = () => {
    const { currentOrgId: orgId, currentProjectId: projectId } = useProjectStore.getState()
    return `${managedScopeKey(orgId, projectId)}:${vaultId}`
  }

  const currentOperationScopeIsActive = (scope = operationScopeRef.current) =>
    operationScopeRef.current === scope && getCurrentOperationScope() === scope

  const mutation = useMutation({
    mutationFn: ({ vaultId, payload, scope, requestScope }: CreateCredentialVariables) => {
      if (!currentOperationScopeIsActive(scope) || !currentProjectAllowsWrite()) {
        throw new Error('Stale vault credential create ignored')
      }
      return managedPost<unknown>(
        apiResourcePath('vaults', vaultId, 'credentials'),
        payload,
        managedRequestOptions(requestScope),
      ).then(parseVaultCredentialResponse)
    },
    onSuccess: (_data, { queryKey, runId, scope }) => {
      if (
        createRunRef.current !== runId ||
        !currentOperationScopeIsActive(scope) ||
        !currentProjectAllowsWrite()
      )
        return
      queryClient.invalidateQueries({ queryKey })
      resetForm()
      onOpenChange(false)
    },
    onError: (error, { runId, scope }) => {
      if (
        createRunRef.current !== runId ||
        !currentOperationScopeIsActive(scope) ||
        !currentProjectAllowsWrite()
      )
        return
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

  useEffect(() => {
    if (operationScopeRef.current !== operationScope) {
      createRunRef.current += 1
      operationScopeRef.current = operationScope
      requestScopeRef.current = managedScope
    }
    if (open) resetForm()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [operationScope])

  useEffect(
    () => () => {
      createRunRef.current += 1
    },
    [],
  )

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!mcpServerUrl.trim()) return
    const urlError = validateUrlScheme(mcpServerUrl.trim())
    if (urlError) {
      alert(urlError)
      return
    }
    if (credentialType === 'static_bearer' && !tokenValue.trim()) return
    if (
      !currentOperationScopeIsActive() ||
      !currentProjectAllowsWrite() ||
      (canSubmit && !canSubmit())
    ) {
      resetForm()
      onOpenChange(false)
      return
    }
    const runId = createRunRef.current + 1
    createRunRef.current = runId
    mutation.mutate({
      vaultId,
      queryKey,
      payload: {
        name: name || undefined,
        credential_type: credentialType,
        mcp_server_url: mcpServerUrl,
        token_value: tokenValue,
      },
      runId,
      scope: operationScopeRef.current,
      requestScope: requestScopeRef.current,
    })
  }

  const handleOpenChange = (next: boolean) => {
    if (next && !currentProjectAllowsWrite()) return
    if (!next) {
      createRunRef.current += 1
      resetForm()
    }
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
