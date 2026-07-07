'use client'

import { useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { useTranslation } from '@/lib/i18n'
import { Plus } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import type { Environment } from '@/types/managed'
import { managedPost } from '@/lib/api-client'
import { stripIdPrefix } from '@/lib/managed/id'
import { toastOperationError } from '@/lib/managed/errors'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  PageHeader,
  FilterBar,
  type FilterDef,
  DataTable,
  type Column,
  StatusBadge,
  MonoId,
  RelativeTime,
  ResourceErrorState,
} from '@/components/managed/shared'
import { createCreatedTimeFilter, filterByCreatedTime, matchesSearch } from '@/lib/managed/filters'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'

export default function EnvironmentListPage() {
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()

  const [showArchived, setShowArchived] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [createdFilter, setCreatedFilter] = useState('all')
  const [showCreate, setShowCreate] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [networkType, setNetworkType] = useState('limited')
  const [allowedHosts, setAllowedHosts] = useState('')
  const [aptPackages, setAptPackages] = useState('')
  const [pipPackages, setPipPackages] = useState('')
  const [npmPackages, setNpmPackages] = useState('')
  const [envVars, setEnvVars] = useState('')
  const [secretRefs, setSecretRefs] = useState('')
  const [creating, setCreating] = useState(false)

  const { data, isLoading, isFetching, isError, error, hasNext, hasPrev, page, pageSize, pageSizeOptions, goNext, goPrev, goToPage, setPageSize } =
    usePaginatedList<Environment>({
      queryKey: 'environments',
      path: '/environments',
      includeArchived: showArchived,
    })

  const environments = data.filter(
    (e) =>
      (showArchived || !e.archived_at) &&
      filterByCreatedTime(e.created_at, createdFilter) &&
      matchesSearch(searchQuery, [e.id, e.name, e.description, e.config?.type, e.archived_at ? 'archived' : 'active']),
  )

  const filters: FilterDef[] = [
    {
      ...createCreatedTimeFilter(t),
      value: createdFilter,
      onChange: setCreatedFilter,
    },
  ]

  const splitLines = (s: string) =>
    s
      .split(/[\n,]/)
      .map((x) => x.trim())
      .filter(Boolean)

  const parseEnvVars = (s: string): Record<string, string> => {
    const vars: Record<string, string> = {}
    for (const line of splitLines(s)) {
      const eqIdx = line.indexOf('=')
      if (eqIdx > 0) {
        vars[line.slice(0, eqIdx).trim()] = line.slice(eqIdx + 1).trim()
      }
    }
    return vars
  }

  const resetForm = () => {
    setName('')
    setDescription('')
    setNetworkType('limited')
    setAllowedHosts('')
    setAptPackages('')
    setPipPackages('')
    setNpmPackages('')
    setEnvVars('')
    setSecretRefs('')
  }

  const resetDialog = (open: boolean) => {
    if (open) {
      resetForm()
    }
    setShowCreate(open)
    if (!open) {
      resetForm()
    }
  }

  const handleCreate = useCallback(async () => {
    if (!name.trim()) return
    setCreating(true)
    try {
      const config: Record<string, unknown> = {
        type: 'cloud',
        networking: {
          type: networkType,
          ...(networkType === 'limited' && allowedHosts.trim()
            ? { allowed_hosts: splitLines(allowedHosts) }
            : {}),
        },
      }

      const packages: Record<string, string[]> = {}
      if (aptPackages.trim()) packages.apt = splitLines(aptPackages)
      if (pipPackages.trim()) packages.pip = splitLines(pipPackages)
      if (npmPackages.trim()) packages.npm = splitLines(npmPackages)
      if (Object.keys(packages).length > 0) config.packages = packages

      const ev = parseEnvVars(envVars)
      if (Object.keys(ev).length > 0) config.env_vars = ev

      const refs = splitLines(secretRefs)
      if (refs.length > 0) config.secret_refs = refs

      await managedPost('/environments', {
        name: name.trim(),
        description: description.trim(),
        config,
      })
      resetForm()
      setShowCreate(false)
      queryClient.invalidateQueries({ queryKey: ['environments'] })
    } catch (e) {
      toastOperationError(t, e, 'common.operationFailed')
    } finally {
      setCreating(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    name,
    description,
    networkType,
    allowedHosts,
    aptPackages,
    pipPackages,
    npmPackages,
    envVars,
    secretRefs,
    queryClient,
  ])

  const columns: Column<Environment>[] = [
    {
      key: 'id',
      header: t('managed.environments.table.id'),
      render: (e) => <MonoId id={e.id} />,
    },
    {
      key: 'name',
      header: t('managed.environments.table.name'),
      render: (e) => (
        <span className="font-medium text-foreground">{e.name}</span>
      ),
    },
    {
      key: 'status',
      header: t('managed.environments.table.status'),
      render: (e) => (
        <StatusBadge status={e.archived_at ? 'archived' : 'active'} />
      ),
    },
    {
      key: 'type',
      header: t('managed.environments.table.type'),
      render: () => (
        <span className="text-muted-foreground">{t('managed.environments.cloud')}</span>
      ),
    },
    {
      key: 'created_at',
      header: t('managed.table.created'),
      render: (e) => (
        <span className="text-muted-foreground text-xs">
          <RelativeTime date={e.created_at} />
        </span>
      ),
    },
  ]

  if (isError) {
    return <ResourceErrorState error={error} resource="environment" onRetry={() => queryClient.invalidateQueries({ queryKey: ['environments'] })} />
  }

  return (
    <div>
      <PageHeader
        title={t('managed.environments.title')}
        subtitle={t('managed.environments.subtitle')}
        action={
          <Button size="sm" onClick={() => resetDialog(true)}>
            <Plus className="w-4 h-4" />
            {t('managed.environments.add')}
          </Button>
        }
      />

      <FilterBar
        searchPlaceholder={t('managed.search.environments')}
        searchValue={searchQuery}
        onSearchChange={setSearchQuery}
        filters={filters}
        showArchived={showArchived}
        onArchivedChange={setShowArchived}
      />

      <DataTable
        columns={columns}
        data={environments}
        loading={isLoading}
        fetching={isFetching}
        onRowClick={(e) => router.push(`/managed/environments/${e.id}`)}
        actionMenu={(env) => env.archived_at ? [] : [
          {
            label: t('managed.environments.archiveEnv'),
            onClick: () => {
              managedPost(`/environments/${stripIdPrefix(env.id)}/archive`, {}).then(() => {
                queryClient.invalidateQueries({ queryKey: ['environments'] })
              })
            },
          },
        ]}
        pagination={{
          hasNext,
          hasPrev,
          page,
          pageSize,
          pageSizeOptions,
          onNext: goNext,
          onPrev: goPrev,
          onPageChange: goToPage,
          onPageSizeChange: setPageSize,
        }}
        emptyMessage={t('managed.environments.empty')}
      />

      <Dialog open={showCreate} onOpenChange={resetDialog}>
        <DialogContent className="max-w-xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t('managed.environments.addTitle')}</DialogTitle>
            <DialogDescription>
              {t('managed.environments.addDesc')}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">
                {t('managed.environments.name')}
              </label>
              <Input
                placeholder={t('managed.environments.namePlaceholder')}
                value={name}
                onChange={(e) => setName(e.target.value)}
                autoFocus
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">
                {t('managed.environments.description')}
              </label>
              <Input
                placeholder={t('managed.environments.descPlaceholder')}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>

            <div className="border-t pt-4">
              <h4 className="text-sm font-medium mb-3">
                {t('managed.environments.networking')}
              </h4>
              <div className="space-y-3">
                <Select value={networkType} onValueChange={setNetworkType}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="limited">
                      {t('managed.environments.netLimited')}
                    </SelectItem>
                    <SelectItem value="unrestricted">
                      {t('managed.environments.netUnrestricted')}
                    </SelectItem>
                  </SelectContent>
                </Select>
                {networkType === 'limited' && (
                  <div className="space-y-1">
                    <label className="text-xs text-muted-foreground">
                      {t('managed.environments.allowedHosts')}
                    </label>
                    <Input
                      placeholder="api.example.com, github.com"
                      value={allowedHosts}
                      onChange={(e) => setAllowedHosts(e.target.value)}
                    />
                  </div>
                )}
              </div>
            </div>

            <div className="border-t pt-4">
              <h4 className="text-sm font-medium mb-3">
                {t('managed.environments.packages')}
              </h4>
              <div className="space-y-3">
                <div className="space-y-1">
                  <label className="text-xs text-muted-foreground">apt</label>
                  <Input
                    placeholder="curl, git, build-essential"
                    value={aptPackages}
                    onChange={(e) => setAptPackages(e.target.value)}
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs text-muted-foreground">pip</label>
                  <Input
                    placeholder="numpy, pandas, requests"
                    value={pipPackages}
                    onChange={(e) => setPipPackages(e.target.value)}
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs text-muted-foreground">npm</label>
                  <Input
                    placeholder="typescript, eslint"
                    value={npmPackages}
                    onChange={(e) => setNpmPackages(e.target.value)}
                  />
                </div>
              </div>
            </div>

            <div className="border-t pt-4">
              <h4 className="text-sm font-medium mb-3">
                {t('managed.environments.envVarsLabel')}
              </h4>
              <Input
                placeholder="KEY=value, NODE_ENV=production"
                value={envVars}
                onChange={(e) => setEnvVars(e.target.value)}
              />
            </div>

            <div className="border-t pt-4">
              <h4 className="text-sm font-medium mb-3">
                {t('managed.environments.secretRefsLabel')}
              </h4>
              <Input
                placeholder="my-api-secret, db-credentials"
                value={secretRefs}
                onChange={(e) => setSecretRefs(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              onClick={handleCreate}
              disabled={!name.trim() || creating}
            >
              {creating
                ? t('managed.environments.creating')
                : t('managed.environments.add')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
