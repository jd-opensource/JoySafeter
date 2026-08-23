'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useCallback, useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { useScopedActions } from '@/hooks/managed/use-scoped-actions'
import { managedPost } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { apiResourcePath } from '@/lib/managed/api-paths'
import { parseCredentialGroupCredentialResponse } from '@/lib/managed/credential-group-response-parsers'
import { toastOperationError } from '@/lib/managed/errors'
import { managedRequestOptions } from '@/lib/managed/request-scope'
import type { ManagedRequestScope } from '@/lib/managed/request-scope'
import { validateUrlScheme } from '@/lib/utils/url-validation'
import type { CredentialGroupId } from '@/types/entity-id'

interface CreateMcpMemberDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  credentialGroupId: CredentialGroupId
  queryKey: unknown[]
  canSubmit?: () => boolean
}

interface CreateCredentialVariables {
  credentialGroupId: CredentialGroupId
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

export function CreateMcpMemberDialog({
  open,
  onOpenChange,
  credentialGroupId,
  queryKey,
  canSubmit,
}: CreateMcpMemberDialogProps) {
  const { t } = useTranslation()
  const [name, setName] = useState('')
  const [mcpServerUrl, setMcpServerUrl] = useState('')
  const [tokenValue, setTokenValue] = useState('')
  const queryClient = useQueryClient()
  const resetFields = useCallback(() => {
    setName('')
    setMcpServerUrl('')
    setTokenValue('')
  }, [])
  const { readOnly, beginAction, isCurrentAction, scopeIsActive, bumpRun } = useScopedActions({
    onReset: () => {
      resetFields()
      onOpenChange(false)
    },
  })

  const mutation = useMutation({
    mutationFn: ({
      credentialGroupId: actionCredentialGroupId,
      payload,
      runId,
      scope,
      requestScope,
    }: CreateCredentialVariables) => {
      if (!isCurrentAction(runId, scope)) {
        throw new Error('Stale vault credential create ignored')
      }
      return managedPost<unknown>(
        apiResourcePath('credential-groups', actionCredentialGroupId, 'members'),
        payload,
        managedRequestOptions(requestScope),
      ).then(parseCredentialGroupCredentialResponse)
    },
    onSuccess: (_data, { queryKey, runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      if (canSubmit && !canSubmit()) return
      queryClient.invalidateQueries({ queryKey })
      resetFields()
      onOpenChange(false)
    },
    onError: (error, { runId, scope }) => {
      if (!isCurrentAction(runId, scope)) return
      if (canSubmit && !canSubmit()) return
      toastOperationError(t, error, 'managed.credentials.groups.members.createFailed')
    },
  })

  const resetForm = useCallback(() => {
    resetFields()
    mutation.reset()
  }, [mutation, resetFields])

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
    const action = beginAction()
    if (!action || (canSubmit && !canSubmit())) {
      resetForm()
      onOpenChange(false)
      return
    }
    mutation.mutate({
      credentialGroupId,
      queryKey,
      payload: {
        name: name.trim() || trimmedMcpServerUrl,
        mcp_server_url: trimmedMcpServerUrl,
        data: { token_value: trimmedTokenValue },
      },
      ...action,
    })
  }

  const handleOpenChange = (next: boolean) => {
    if (next && (readOnly || !scopeIsActive())) return
    if (!next) {
      bumpRun()
      resetForm()
    }
    onOpenChange(next)
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('managed.credentials.groups.members.createTitle')}</DialogTitle>
          <DialogDescription>
            {t('managed.credentials.groups.members.createDescription')}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="mt-2 space-y-4">
          <div className="space-y-1.5">
            <label htmlFor="cred-name" className="text-sm font-medium">
              {t('managed.credentials.groups.members.name')}{' '}
              <span className="font-normal text-muted-foreground">
                {t('managed.credentials.groups.members.nameOptional')}
              </span>
            </label>
            <Input
              id="cred-name"
              placeholder={t('managed.credentials.groups.members.namePlaceholder')}
              value={name}
              disabled={readOnly}
              onChange={(e) => setName(e.target.value)}
              autoFocus
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="cred-url" className="text-sm font-medium">
              {t('managed.credentials.groups.members.mcpServer')}
            </label>
            <Input
              id="cred-url"
              placeholder="https://mcp.example.com"
              value={mcpServerUrl}
              disabled={readOnly}
              onChange={(e) => setMcpServerUrl(e.target.value)}
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="cred-token" className="text-sm font-medium">
              {t('managed.credentials.groups.members.token')}
            </label>
            <Input
              id="cred-token"
              type="password"
              placeholder={t('managed.credentials.groups.members.tokenPlaceholder')}
              value={tokenValue}
              disabled={readOnly}
              onChange={(e) => setTokenValue(e.target.value)}
            />
          </div>

          <div className="flex justify-end">
            <Button
              type="submit"
              disabled={
                !mcpServerUrl.trim() || !tokenValue.trim() || mutation.isPending || readOnly
              }
            >
              {mutation.isPending
                ? t('managed.credentials.groups.members.adding')
                : t('managed.credentials.groups.members.add')}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
