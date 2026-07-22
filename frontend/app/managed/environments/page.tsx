'use client'

import { useState, useCallback, useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { useTranslation } from '@/lib/i18n'
import { Plus } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import type { Environment, Secret } from '@/types/managed'
import { managedPost } from '@/lib/api-client'
import { apiResourcePath } from '@/lib/managed/api-paths'
import { toastOperationError } from '@/lib/managed/errors'
import {
  managedRequestOptions,
  managedScopeKey,
  useManagedRequestScope,
  type ManagedRequestScope,
} from '@/lib/managed/request-scope'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
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
import { useProjectStore } from '@/stores/managed/project-store'
import {
  currentProjectAllowsWrite,
  useCurrentProjectReadOnly,
} from '@/hooks/managed/use-current-project-read-only'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import {
  EgressServicesEditor,
  buildEgressServices,
  emptyEgressService,
  type EgressServiceErrorField,
  type EgressServiceErrors,
  type EgressServiceForm,
} from '@/components/managed/environments-egress-editor'

type CreateEnvironmentErrors = {
  name?: string
  egressServices: EgressServiceErrors
}

const emptyCreateErrors = (): CreateEnvironmentErrors => ({ egressServices: {} })

export default function EnvironmentListPage() {
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
  const managedScope = useManagedRequestScope()
  const projectReadOnly = useCurrentProjectReadOnly()

  const [showArchived, setShowArchived] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [createdFilter, setCreatedFilter] = useState('all')
  const [showCreate, setShowCreate] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const networkType = 'limited'
  const [allowedHosts, setAllowedHosts] = useState('')
  const [aptPackages, setAptPackages] = useState('')
  const [pipPackages, setPipPackages] = useState('')
  const [npmPackages, setNpmPackages] = useState('')
  const [envVars, setEnvVars] = useState('')
  const [secretRefs, setSecretRefs] = useState('')
  const [egressServices, setEgressServices] = useState<EgressServiceForm[]>([])
  const [formErrors, setFormErrors] = useState<CreateEnvironmentErrors>(emptyCreateErrors)
  const [creating, setCreating] = useState(false)
  const createRunRef = useRef(0)
  const actionRunRef = useRef(0)
  const previousScopeRef = useRef<string | null>(null)
  const managedScopeRef = useRef(managedScope.key)
  const managedRequestScopeRef = useRef<ManagedRequestScope>(managedScope)

  const {
    data,
    isLoading,
    isFetching,
    isError,
    error,
    hasNext,
    hasPrev,
    page,
    pageSize,
    pageSizeOptions,
    goNext,
    goPrev,
    goToPage,
    setPageSize,
  } = usePaginatedList<Environment>({
    queryKey: 'environments',
    path: '/environments',
    includeArchived: showArchived,
  })
  const { data: secrets } = usePaginatedList<Secret>({
    queryKey: 'secrets',
    path: '/secrets',
    limit: 50,
  })

  const environments = data.filter(
    (e) =>
      (showArchived || !e.archived_at) &&
      filterByCreatedTime(e.created_at, createdFilter) &&
      matchesSearch(searchQuery, [
        e.id,
        e.name,
        e.description,
        e.config?.type,
        e.archived_at ? 'archived' : 'active',
      ]),
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
    setAllowedHosts('')
    setAptPackages('')
    setPipPackages('')
    setNpmPackages('')
    setEnvVars('')
    setSecretRefs('')
    setEgressServices([])
    setFormErrors(emptyCreateErrors())
  }

  const clearFieldError = (field: keyof Omit<CreateEnvironmentErrors, 'egressServices'>) => {
    setFormErrors((current) => ({ ...current, [field]: undefined }))
  }

  const clearEgressFieldError = (index: number, field: EgressServiceErrorField) => {
    setFormErrors((current) => {
      const nextServices = { ...current.egressServices }
      if (nextServices[index]) {
        nextServices[index] = { ...nextServices[index], [field]: undefined }
        if (Object.values(nextServices[index]).every((value) => !value)) {
          delete nextServices[index]
        }
      }
      return { ...current, egressServices: nextServices }
    })
  }

  const validateCreateForm = (): CreateEnvironmentErrors => {
    const errors = emptyCreateErrors()
    const requiredMessage = t('managed.environments.validation.required')
    if (!name.trim()) {
      errors.name = t('managed.environments.validation.nameRequired')
    }
    egressServices.forEach((service, index) => {
      const serviceErrors: CreateEnvironmentErrors['egressServices'][number] = {}
      if (!service.name.trim()) serviceErrors.name = requiredMessage
      if (!service.baseUrl.trim()) serviceErrors.baseUrl = requiredMessage
      if (!service.credentialRef.trim()) serviceErrors.credentialRef = requiredMessage
      if (service.authType === 'cookie' && !service.secretKey.trim()) {
        serviceErrors.secretKey = t('managed.environments.validation.cookieRequired')
      }
      if (Object.keys(serviceErrors).length > 0) {
        errors.egressServices[index] = serviceErrors
      }
    })
    return errors
  }

  const hasCreateErrors = (errors: CreateEnvironmentErrors) =>
    Boolean(errors.name) || Object.keys(errors.egressServices).length > 0

  const resetDialog = (open: boolean) => {
    if (open && (!currentManagedScopeIsActive() || !currentProjectAllowsWrite())) return
    createRunRef.current += 1
    if (open) {
      resetForm()
    }
    setShowCreate(open)
    if (!open) {
      resetForm()
    }
  }

  useEffect(() => {
    if (previousScopeRef.current === null) {
      previousScopeRef.current = managedScope.key
      return
    }
    if (previousScopeRef.current === managedScope.key) return
    previousScopeRef.current = managedScope.key
    managedScopeRef.current = managedScope.key
    managedRequestScopeRef.current = managedScope
    createRunRef.current += 1
    actionRunRef.current += 1
    setCreating(false)
    setShowCreate(false)
    resetForm()
  }, [managedScope.key])

  useEffect(
    () => () => {
      createRunRef.current += 1
      actionRunRef.current += 1
    },
    [],
  )

  useEffect(() => {
    if (!projectReadOnly) return
    createRunRef.current += 1
    actionRunRef.current += 1
    setCreating(false)
    setShowCreate(false)
    resetForm()
  }, [projectReadOnly])

  const getCurrentManagedScope = () => {
    const { currentOrgId: orgId, currentProjectId: projectId } = useProjectStore.getState()
    return managedScopeKey(orgId, projectId)
  }

  const currentManagedScopeIsActive = (scope = managedScopeRef.current) =>
    getCurrentManagedScope() === scope

  const isCurrentCreateRun = (runId: number, scope: string) =>
    runId === createRunRef.current &&
    scope === managedScopeRef.current &&
    currentManagedScopeIsActive(scope) &&
    currentProjectAllowsWrite()

  const isCurrentAction = (runId: number, scope: string) =>
    actionRunRef.current === runId &&
    managedScopeRef.current === scope &&
    currentManagedScopeIsActive(scope) &&
    currentProjectAllowsWrite()

  const currentEnvironmentIsActive = (env: Environment, scope: string) =>
    currentProjectAllowsWrite() &&
    queryClient
      .getQueriesData<{ data?: Environment[] }>({
        queryKey: ['environments', scope, '/environments'],
      })
      .some(([, page]) =>
        page?.data?.some(
          (currentEnvironment) =>
            currentEnvironment.id === env.id && !currentEnvironment.archived_at,
        ),
      )

  const handleCreate = useCallback(async () => {
    if (!currentProjectAllowsWrite()) return
    if (!currentManagedScopeIsActive()) return
    const validationErrors = validateCreateForm()
    setFormErrors(validationErrors)
    if (hasCreateErrors(validationErrors)) return
    const runId = createRunRef.current + 1
    createRunRef.current = runId
    const createScope = managedScopeRef.current
    const requestScope = managedRequestScopeRef.current
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

      const services = buildEgressServices(egressServices)
      if (services.length > 0) config.egress_services = services

      await managedPost(
        '/environments',
        {
          name: name.trim(),
          description: description.trim(),
          config,
        },
        managedRequestOptions(requestScope),
      )
      if (!isCurrentCreateRun(runId, createScope)) return
      resetForm()
      setShowCreate(false)
      queryClient.invalidateQueries({ queryKey: ['environments', createScope] })
    } catch (e) {
      if (!isCurrentCreateRun(runId, createScope)) return
      toastOperationError(t, e, 'common.operationFailed')
    } finally {
      if (isCurrentCreateRun(runId, createScope)) {
        setCreating(false)
      }
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
    egressServices,
    queryClient,
  ])

  const handleArchive = async (env: Environment) => {
    if (!currentProjectAllowsWrite()) return
    const actionScope = managedScopeRef.current
    if (!currentManagedScopeIsActive(actionScope)) return
    if (!currentEnvironmentIsActive(env, actionScope)) return

    const runId = actionRunRef.current + 1
    actionRunRef.current = runId
    const requestScope = managedRequestScopeRef.current
    try {
      await managedPost(
        apiResourcePath('environments', env.id, 'archive'),
        {},
        managedRequestOptions(requestScope),
      )
      if (!isCurrentAction(runId, actionScope)) return
      queryClient.invalidateQueries({ queryKey: ['environments', actionScope] })
    } catch (e) {
      if (!isCurrentAction(runId, actionScope)) return
      toastOperationError(t, e, 'common.operationFailed')
    }
  }

  const columns: Column<Environment>[] = [
    {
      key: 'id',
      header: t('managed.environments.table.id'),
      render: (e) => <MonoId id={e.id} />,
    },
    {
      key: 'name',
      header: t('managed.environments.table.name'),
      render: (e) => <span className="font-medium text-foreground">{e.name}</span>,
    },
    {
      key: 'status',
      header: t('managed.environments.table.status'),
      render: (e) => <StatusBadge status={e.archived_at ? 'archived' : 'active'} />,
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
        <span className="text-xs text-muted-foreground">
          <RelativeTime date={e.created_at} />
        </span>
      ),
    },
  ]

  if (isError) {
    return (
      <ResourceErrorState
        error={error}
        resource="environment"
        onRetry={() =>
          queryClient.invalidateQueries({ queryKey: ['environments', managedScope.key] })
        }
      />
    )
  }

  return (
    <div>
      <PageHeader
        title={t('managed.environments.title')}
        subtitle={t('managed.environments.subtitle')}
        action={
          projectReadOnly ? null : (
            <Button size="sm" onClick={() => resetDialog(true)}>
              <Plus className="h-4 w-4" />
              {t('managed.environments.add')}
            </Button>
          )
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
        actionMenu={(env) =>
          projectReadOnly || env.archived_at
            ? []
            : [
                {
                  label: t('managed.environments.archiveEnv'),
                  onClick: () => handleArchive(env),
                },
              ]
        }
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

      <Dialog open={!projectReadOnly && showCreate} onOpenChange={resetDialog}>
        <DialogContent className="max-h-[85vh] max-w-xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t('managed.environments.addTitle')}</DialogTitle>
            <DialogDescription>{t('managed.environments.addDesc')}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="environment-name">
                {t('managed.environments.name')}
                <span className="ml-1 text-destructive">*</span>
              </label>
              <Input
                id="environment-name"
                placeholder={t('managed.environments.namePlaceholder')}
                value={name}
                aria-invalid={Boolean(formErrors.name)}
                onChange={(e) => {
                  setName(e.target.value)
                  clearFieldError('name')
                }}
                autoFocus
              />
              {formErrors.name && <p className="text-xs text-destructive">{formErrors.name}</p>}
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="environment-description">
                {t('managed.environments.description')}
                <span className="ml-1 text-xs font-normal text-muted-foreground">
                  {t('managed.environments.optional')}
                </span>
              </label>
              <Input
                id="environment-description"
                placeholder={t('managed.environments.descPlaceholder')}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>

            <div className="border-t pt-4">
              <h4 className="mb-3 text-sm font-medium">
                {t('managed.environments.networking')}
                <span className="ml-1 text-destructive">*</span>
              </h4>
              <div className="space-y-3">
                <Input value={t('managed.environments.netLimited')} readOnly />
                {networkType === 'limited' && (
                  <div className="space-y-1">
                    <label className="text-sm font-medium" htmlFor="environment-allowed-hosts">
                      {t('managed.environments.allowedHosts')}
                      <span className="ml-1 text-xs font-normal text-muted-foreground">
                        {t('managed.environments.optional')}
                      </span>
                    </label>
                    <Input
                      id="environment-allowed-hosts"
                      placeholder="api.example.com, github.com"
                      value={allowedHosts}
                      onChange={(e) => setAllowedHosts(e.target.value)}
                    />
                  </div>
                )}
              </div>
            </div>

            <div className="border-t pt-4">
              <h4 className="mb-3 text-sm font-medium">
                {t('managed.environments.envVarsLabel')}
                <span className="ml-1 text-xs font-normal text-muted-foreground">
                  {t('managed.environments.optional')}
                </span>
              </h4>
              <Input
                placeholder="KEY=value, NODE_ENV=production"
                value={envVars}
                onChange={(e) => setEnvVars(e.target.value)}
              />
            </div>

            <div className="border-t pt-4">
              <h4 className="mb-3 text-sm font-medium">
                {t('managed.environments.secretRefsLabel')}
                <span className="ml-1 text-xs font-normal text-muted-foreground">
                  {t('managed.environments.optional')}
                </span>
              </h4>
              <Input
                placeholder="my-api-secret, db-credentials"
                value={secretRefs}
                onChange={(e) => setSecretRefs(e.target.value)}
              />
            </div>

            <div className="pt-4">
              <div className="mb-3 flex items-center justify-between gap-2">
                <div>
                  <h4 className="text-sm font-medium">
                    {t('managed.environments.egressServices')}
                    <span className="ml-1 text-xs font-normal text-muted-foreground">
                      {t('managed.environments.optional')}
                    </span>
                  </h4>
                  <p className="text-xs text-muted-foreground">
                    {t('managed.environments.egressServicesHint')}
                  </p>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setEgressServices((items) => [...items, emptyEgressService()])}
                >
                  {t('managed.environments.addEgressService')}
                </Button>
              </div>
              <EgressServicesEditor
                services={egressServices}
                setServices={setEgressServices}
                secrets={secrets}
                errors={formErrors.egressServices}
                onClearFieldError={clearEgressFieldError}
                onRemove={(index) => {
                  setFormErrors((current) => ({
                    ...current,
                    egressServices: Object.fromEntries(
                      Object.entries(current.egressServices)
                        .filter(([key]) => Number(key) !== index)
                        .map(([key, value]) => [
                          Number(key) > index ? String(Number(key) - 1) : key,
                          value,
                        ]),
                    ),
                  }))
                  setEgressServices((items) => items.filter((_, i) => i !== index))
                }}
              />
            </div>
          </div>
          <DialogFooter>
            <Button onClick={handleCreate} disabled={creating}>
              {creating ? t('managed.environments.creating') : t('managed.environments.add')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
