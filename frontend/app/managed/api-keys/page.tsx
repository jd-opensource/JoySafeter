'use client'

import { useState } from 'react'
import { useTranslation } from '@/lib/i18n'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { managedGet, managedPost, managedDelete } from '@/lib/api-client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { Plus, Trash2, Copy, Check } from 'lucide-react'
import { DataTable, FilterBar, MonoId, RelativeTime, type Column, type FilterDef, PageHeader, ResourceErrorState } from '@/components/managed/shared'
import { toastOperationError } from '@/lib/managed/errors'
import { createCreatedTimeFilter, filterByCreatedTime, matchesSearch } from '@/lib/managed/filters'
import { roleLabel, roleOptions } from '@/lib/managed/roles'
import { useUserPermissionsContext } from '@/providers/permissions-provider'

interface ApiKey {
  id: string
  project_id: string
  name: string
  key_prefix: string
  role: string
  created_at?: string
  last_used_at?: string
}

export default function ApiKeysPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { canEdit } = useUserPermissionsContext()
  const [showCreate, setShowCreate] = useState(false)
  const [keyName, setKeyName] = useState('')
  const [keyRole, setKeyRole] = useState('developer')
  const [newRawKey, setNewRawKey] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<ApiKey | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [createdFilter, setCreatedFilter] = useState('all')

  const { data: keys = [], isLoading, isError, error } = useQuery({
    queryKey: ['api-keys'],
    queryFn: async () => managedGet<ApiKey[]>('/auth/api-keys'),
  })

  const filteredKeys = keys.filter((key) =>
    filterByCreatedTime(key.created_at || '', createdFilter) &&
    matchesSearch(searchQuery, [key.id, key.name, key.key_prefix, key.role]),
  )
  const filters: FilterDef[] = [
    {
      ...createCreatedTimeFilter(t),
      value: createdFilter,
      onChange: setCreatedFilter,
    },
  ]
  const columns: Column<ApiKey>[] = [
    {
      key: 'name',
      header: t('manage.apiKeys.keyName'),
      render: (key) => <span className="font-medium text-foreground">{key.name}</span>,
    },
    {
      key: 'prefix',
      header: t('manage.apiKeys.prefix'),
      render: (key) => <MonoId id={`${key.key_prefix}...`} truncate={false} />,
    },
    {
      key: 'role',
      header: t('manage.apiKeys.role'),
      render: (key) => <span className="text-muted-foreground">{roleLabel(t, key.role)}</span>,
    },
    {
      key: 'created',
      header: t('managed.table.created'),
      render: (key) => key.created_at ? <RelativeTime date={key.created_at} /> : <span className="text-muted-foreground">-</span>,
    },
    {
      key: 'last_used',
      header: t('manage.apiKeys.lastUsed'),
      render: (key) => key.last_used_at ? <RelativeTime date={key.last_used_at} /> : <span className="text-muted-foreground">-</span>,
    },
  ]

  const createKey = useMutation({
    mutationFn: (data: { name: string; role: string }) =>
      managedPost<{ raw_key: string }>('/auth/api-keys', data),
    onSuccess: (res) => {
      setNewRawKey(res.raw_key)
      queryClient.invalidateQueries({ queryKey: ['api-keys'] })
      setShowCreate(false)
      setKeyName('')
    },
    onError: (error) => {
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  const revokeKey = useMutation({
    mutationFn: (id: string) => managedDelete(`/auth/api-keys/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['api-keys'] })
    },
    onError: (error) => {
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  if (isError) {
    return <ResourceErrorState error={error} resource="apiKey" onRetry={() => queryClient.invalidateQueries({ queryKey: ['api-keys'] })} />
  }

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="w-full">
      <PageHeader
        title={t('manage.apiKeys.title')}
        subtitle={t('manage.apiKeys.subtitle')}
        action={canEdit ? (
          <Button size="sm" onClick={() => setShowCreate(true)}>
            <Plus className="w-4 h-4 mr-1" />
            {t('manage.apiKeys.create')}
          </Button>
        ) : null}
      />

      {newRawKey && (
        <div className="mb-4 p-4 border border-green-500/50 bg-green-50 dark:bg-green-950/20 rounded-lg">
          <p className="text-sm font-medium mb-2">{t('manage.apiKeys.newKeyWarning')}</p>
          <div className="flex items-center gap-2">
            <code className="flex-1 bg-background px-3 py-2 rounded border text-xs font-mono break-all">{newRawKey}</code>
            <Button variant="outline" size="icon" className="h-8 w-8 shrink-0" onClick={() => handleCopy(newRawKey)}>
              {copied ? <Check className="w-3.5 h-3.5 text-green-500" /> : <Copy className="w-3.5 h-3.5" />}
            </Button>
          </div>
          <Button variant="ghost" size="sm" className="mt-2 text-xs" onClick={() => setNewRawKey(null)}>
            {t('manage.apiKeys.dismiss')}
          </Button>
        </div>
      )}

      <FilterBar
        searchPlaceholder={t('managed.search.apiKeys')}
        searchValue={searchQuery}
        onSearchChange={setSearchQuery}
        filters={filters}
      />

      {showCreate && (
        <Dialog open={showCreate} onOpenChange={setShowCreate}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{t('manage.apiKeys.create')}</DialogTitle>
              <DialogDescription>{t('manage.apiKeys.subtitle')}</DialogDescription>
            </DialogHeader>
            <div className="space-y-3 py-2">
              <Input
                placeholder={t('manage.apiKeys.namePlaceholder')}
                value={keyName}
                onChange={(e) => setKeyName(e.target.value)}
              />
              <Select value={keyRole} onValueChange={setKeyRole}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {roleOptions(t).filter((option) => option.value !== 'viewer').map((option) => (
                    <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setShowCreate(false)}>
                {t('common.cancel')}
              </Button>
              <Button onClick={() => createKey.mutate({ name: keyName, role: keyRole })} disabled={!keyName.trim()}>
                {t('manage.apiKeys.create')}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}

      <DataTable
        columns={columns}
        data={filteredKeys}
        loading={isLoading}
        emptyMessage={t('manage.apiKeys.empty')}
        actionMenu={canEdit ? (key) => [
          {
            label: t('manage.apiKeys.revoke'),
            icon: <Trash2 className="w-3.5 h-3.5" />,
            destructive: true,
            onClick: () => setDeleteTarget(key),
          },
        ] : undefined}
      />

      <Dialog open={!!deleteTarget} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('manage.apiKeys.revokeTitle')}</DialogTitle>
            <DialogDescription>{t('manage.apiKeys.revokeDesc')}</DialogDescription>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            {deleteTarget?.name} ({deleteTarget?.key_prefix}...)
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>{t('common.cancel')}</Button>
            <Button variant="destructive" onClick={() => { revokeKey.mutate(deleteTarget!.id); setDeleteTarget(null) }}>
              {t('manage.apiKeys.revoke')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
