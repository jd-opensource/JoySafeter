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
import type { CredentialGroupId } from '@/types/entity-id'
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
  vaultId: CredentialGroupId
  queryKey: unknown[]
  canSubmit?: () => boolean
}

interface CreateCredentialVariables {
  vaultId: CredentialGroupId
  queryKey: unknown[]
  payload: {
    name: string
    mcp_server_url: string
    data: { token_value: string }
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
        apiResourcePath('credential-groups', vaultId, 'members'),
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
    const trimmedMcpServerUrl = mcpServerUrl.trim()
    const trimmedTokenValue = tokenValue.trim()
    if (!trimmedMcpServerUrl || !trimmedTokenValue) return
    const urlError = validateUrlScheme(trimmedMcpServerUrl)
    if (urlError) {
      alert(urlError)
      return
    }
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
        name: name.trim() || trimmedMcpServerUrl,
        mcp_server_url: trimmedMcpServerUrl,
        data: { token_value: trimmedTokenValue },
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

          <div className="space-y-1.5">
            <label htmlFor="cred-token" className="text-sm font-medium">
              {t('managed.vaults.cred.token')}
            </label>
            <Input
              id="cred-token"
              type="password"
              placeholder={t('managed.vaults.cred.tokenPlaceholder')}
              value={tokenValue}
              onChange={(e) => setTokenValue(e.target.value)}
            />
          </div>

          <div className="flex justify-end">
            <Button
              type="submit"
              disabled={!mcpServerUrl.trim() || !tokenValue.trim() || mutation.isPending}
            >
              {mutation.isPending
                ? t('managed.vaults.cred.adding')
                : t('managed.vaults.cred.add')}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
