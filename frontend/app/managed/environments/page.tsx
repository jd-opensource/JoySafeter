'use client'

import { useEffect, useState, useCallback, useRef } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useTranslation } from '@/lib/i18n'
import { Plus } from 'lucide-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { usePaginatedList } from '@/hooks/managed/use-paginated-list'
import type {
  StorageVolumeCatalogItem,
  Environment,
  EnvironmentMountResource,
  Secret,
} from '@/types/managed'
import { managedGet, managedPost } from '@/lib/api-client'
import { apiResourcePath } from '@/lib/managed/api-paths'
import { toastOperationError } from '@/lib/managed/errors'
import { managedRequestOptions } from '@/lib/managed/request-scope'
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
  FieldHelp,
  AdvancedSection,
  FormActionBar,
  FormFieldError,
  FormFieldLabel,
  FormSectionCard,
} from '@/components/managed/shared'
import { createCreatedTimeFilter, filterByCreatedTime, matchesSearch } from '@/lib/managed/filters'
import { currentProjectAllowsWrite } from '@/hooks/managed/use-current-project-read-only'
import { useScopedActions } from '@/hooks/managed/use-scoped-actions'
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

type MountResourceForm = {
  name: string
  volumeRef: string
  subPath: string
  mountPath: string
  access: 'read_only' | 'read_write'
  required: boolean
}

const emptyCreateErrors = (): CreateEnvironmentErrors => ({ egressServices: {} })

const mountNameFromVolume = (volumeRef: string) =>
  volumeRef
    .replace(/^storage[-_]?/, '')
    .replace(/[^a-zA-Z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '') || 'storage-data'

const defaultMountPath = (name: string) => `/workspace/storage/${name || 'data'}`

export default function EnvironmentListPage() {
  const { t } = useTranslation()
  const router = useRouter()
  const searchParams = useSearchParams()
  const queryClient = useQueryClient()
  const {
    scopeRef: managedScopeRef,
    requestScopeRef: managedRequestScopeRef,
    scope: managedScope,
    readOnly,
    beginAction,
    isCurrentAction,
    scopeIsActive,
    bumpRun,
  } = useScopedActions({
    onReset: () => {
      createRunRef.current += 1
      setCreating(false)
      setShowCreate(false)
      resetForm()
    },
  })

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
  const [egressServices, setEgressServices] = useState<EgressServiceForm[]>([])
  const [mountResources, setMountResources] = useState<MountResourceForm[]>([])
  const [formErrors, setFormErrors] = useState<CreateEnvironmentErrors>(emptyCreateErrors)
  const [creating, setCreating] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const createRunRef = useRef(0)

  useEffect(
    () => () => {
      createRunRef.current += 1
    },
    [],
  )

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
  const { data: storageCatalog } = useQuery({
    queryKey: ['storage-mount-catalog', managedScope],
    queryFn: () => managedGet<{ data: StorageVolumeCatalogItem[] }>('/storage-volumes/catalog'),
    enabled: scopeIsActive(),
    staleTime: 60_000,
  })
  const storageVolumes = storageCatalog?.data || []

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
    setEgressServices([])
    setMountResources([])
    setFormErrors(emptyCreateErrors())
    setShowAdvanced(false)
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
    if (open && (!scopeIsActive() || !currentProjectAllowsWrite())) return
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
    if (searchParams.get('create') === '1') {
      resetDialog(true)
      router.replace('/managed/environments')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams])

  const isCurrentCreateRun = (runId: number, scope: string) =>
    runId === createRunRef.current &&
    scope === managedScopeRef.current &&
    scopeIsActive(scope) &&
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
    if (!scopeIsActive()) return
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

      const services = buildEgressServices(egressServices)
      if (services.length > 0) config.egress_services = services

      const mounts: EnvironmentMountResource[] = mountResources
        .map((resource) => ({
          type: 'storage',
          name: resource.name.trim(),
          volume_ref: resource.volumeRef.trim(),
          sub_path: resource.subPath.trim(),
          mount_path: resource.mountPath.trim(),
          access: resource.access,
          required: resource.required,
        }))
        .filter((resource) => resource.name && resource.volume_ref && resource.mount_path)
      if (mounts.length > 0) config.mount_resources = mounts

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
    egressServices,
    mountResources,
    queryClient,
  ])

  const handleArchive = async (env: Environment) => {
    if (!currentProjectAllowsWrite()) return
    if (!scopeIsActive()) return
    if (!currentEnvironmentIsActive(env, managedScopeRef.current)) return

    const action = beginAction()
    if (!action) return
    const { runId, scope, requestScope } = action
    try {
      await managedPost(
        apiResourcePath('environments', env.id, 'archive'),
        {},
        managedRequestOptions(requestScope),
      )
      if (!isCurrentAction(runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['environments', scope] })
    } catch (e) {
      if (!isCurrentAction(runId, scope)) return
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
          readOnly ? null : (
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
          readOnly || env.archived_at
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

      <Dialog open={!readOnly && showCreate} onOpenChange={resetDialog}>
        <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t('managed.environments.addTitle')}</DialogTitle>
            <DialogDescription>{t('managed.environments.addDesc')}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <FormSectionCard
              title={t('managed.environments.basicSettings', '基础配置')}
              description={t(
                'managed.environments.basicSettingsDesc',
                '设置环境名称、用途和默认网络访问策略。',
              )}
            >
              <div className="space-y-2">
                <FormFieldLabel htmlFor="environment-name" required>
                  {t('managed.environments.name')}
                </FormFieldLabel>
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
                <FormFieldError message={formErrors.name} />
              </div>
              <div className="space-y-2">
                <FormFieldLabel
                  htmlFor="environment-description"
                  optional={t('managed.environments.optional')}
                >
                  {t('managed.environments.description')}
                </FormFieldLabel>
                <Input
                  id="environment-description"
                  placeholder={t('managed.environments.descPlaceholder')}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </div>

              <div className="space-y-2">
                <FormFieldLabel
                  required
                  tooltip={t(
                    'managed.environments.networkingHint',
                    '受限网络模式下，沙箱默认无法访问外网。只有白名单中的主机和第三方服务配置的地址可以访问。',
                  )}
                >
                  {t('managed.environments.networking')}
                </FormFieldLabel>
                <div className="rounded-xl border border-border bg-muted/25 p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="inline-flex h-2 w-2 rounded-full bg-emerald-500" />
                        <span className="text-sm font-medium text-foreground">
                          {t('managed.environments.netLimited')}
                        </span>
                      </div>
                      <p className="text-xs leading-5 text-muted-foreground">
                        {t(
                          'managed.environments.netLimitedDesc',
                          '默认禁止外网访问，仅允许白名单主机和已配置的第三方服务。',
                        )}
                      </p>
                    </div>
                    <span className="shrink-0 rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-700 dark:text-emerald-300">
                      {t('managed.environments.recommended', '推荐')}
                    </span>
                  </div>
                  {networkType === 'limited' && (
                    <div className="border-border/70 mt-3 space-y-1.5 border-t pt-3">
                      <FormFieldLabel
                        htmlFor="environment-allowed-hosts"
                        optional={t('managed.environments.optional')}
                        tooltip={t(
                          'managed.environments.allowedHostsHint',
                          '沙箱可直接访问的外网主机白名单（逗号分隔）。第三方服务配置的地址会自动放行，无需重复填写。',
                        )}
                      >
                        {t('managed.environments.allowedHosts')}
                      </FormFieldLabel>
                      <textarea
                        id="environment-allowed-hosts"
                        placeholder={t(
                          'managed.environments.allowedHostsPlaceholder',
                          'api.example.com\ngithub.com\n*.internal.example.com',
                        )}
                        value={allowedHosts}
                        onChange={(e) => setAllowedHosts(e.target.value)}
                        rows={4}
                        className="flex min-h-[96px] w-full resize-y rounded-md border border-border bg-background px-3 py-2 font-mono text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                      />
                      <p className="text-xs leading-5 text-muted-foreground">
                        {t(
                          'managed.environments.allowedHostsDesc',
                          '第三方服务地址会自动放行；这里仅填写额外需要直连访问的主机。',
                        )}
                      </p>
                    </div>
                  )}
                </div>
              </div>
            </FormSectionCard>

            <AdvancedSection
              open={showAdvanced}
              onOpenChange={setShowAdvanced}
              title={t('managed.environments.advancedOptions', '高级选项')}
              summary={t(
                'managed.environments.advancedSummary',
                '环境变量、数据卷挂载、第三方服务',
              )}
            >
              <div>
                <FormFieldLabel
                  optional={t('managed.environments.optional')}
                  tooltip={t(
                    'managed.environments.envVarsHint',
                    '注入到沙箱的非敏感环境变量。格式：KEY=value，逗号或换行分隔。不要填写 token、cookie、API key 等敏感凭证。',
                  )}
                  className="mb-3"
                >
                  {t('managed.environments.envVarsLabel')}
                </FormFieldLabel>
                <Input
                  placeholder="KEY=value, NODE_ENV=production"
                  value={envVars}
                  onChange={(e) => setEnvVars(e.target.value)}
                />
              </div>

              <div className="pt-4">
                <FormFieldLabel optional={t('managed.environments.optional')} className="mb-3">
                  {t('managed.environments.packages')}
                </FormFieldLabel>
                <div className="grid gap-3 md:grid-cols-3">
                  <label className="space-y-1.5 text-sm">
                    <span className="font-medium">APT</span>
                    <Input
                      placeholder="curl, git, build-essential"
                      value={aptPackages}
                      onChange={(e) => setAptPackages(e.target.value)}
                    />
                  </label>
                  <label className="space-y-1.5 text-sm">
                    <span className="font-medium">PyPI</span>
                    <Input
                      placeholder="numpy, pandas, requests"
                      value={pipPackages}
                      onChange={(e) => setPipPackages(e.target.value)}
                    />
                  </label>
                  <label className="space-y-1.5 text-sm">
                    <span className="font-medium">npm</span>
                    <Input
                      placeholder="typescript, eslint, prettier"
                      value={npmPackages}
                      onChange={(e) => setNpmPackages(e.target.value)}
                    />
                  </label>
                </div>
              </div>

              <div className="pt-4">
                <div className="mb-3 flex items-center justify-between gap-2">
                  <div>
                    <FormFieldLabel optional={t('managed.environments.optional')}>
                      {t('managed.environments.storageMounts', '数据卷挂载')}
                    </FormFieldLabel>
                    <p className="text-xs text-muted-foreground">
                      将平台管理的共享存储目录挂载到沙箱的 /workspace 下，供 Agent 读写文件。
                    </p>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={storageVolumes.length === 0}
                    onClick={() => {
                      const first = storageVolumes[0]
                      if (!first) return
                      const name = mountNameFromVolume(first.volume_ref)
                      setMountResources((items) => [
                        ...items,
                        {
                          name,
                          volumeRef: first.volume_ref,
                          subPath: first.allowed_prefixes?.[0] || '',
                          mountPath: defaultMountPath(name),
                          access: 'read_only',
                          required: true,
                        },
                      ])
                    }}
                  >
                    添加挂载
                  </Button>
                </div>
                {storageVolumes.length === 0 && (
                  <div className="rounded-lg border border-dashed bg-muted/30 p-3 text-xs text-muted-foreground">
                    当前部署未配置 Storage volume catalog。
                  </div>
                )}
                {mountResources.length > 0 && (
                  <div className="space-y-3">
                    {mountResources.map((resource, index) => {
                      const selected = storageVolumes.find(
                        (item) => item.volume_ref === resource.volumeRef,
                      )
                      const canWrite = selected?.max_access === 'read_write'
                      return (
                        <div
                          key={`${resource.volumeRef}-${index}`}
                          className="rounded-xl border bg-card p-3"
                        >
                          <div className="mb-3 flex items-center justify-between gap-2">
                            <div>
                              <p className="text-sm font-medium">{resource.name || '数据卷'}</p>
                              <p className="text-xs text-muted-foreground">
                                挂载到 {resource.mountPath || '/workspace/storage/data'}
                              </p>
                            </div>
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              onClick={() =>
                                setMountResources((items) => items.filter((_, i) => i !== index))
                              }
                            >
                              移除
                            </Button>
                          </div>
                          <div className="grid gap-3 sm:grid-cols-2">
                            <label className="space-y-1 text-sm">
                              <span className="font-medium">数据卷</span>
                              <Select
                                value={resource.volumeRef}
                                onValueChange={(value) => {
                                  const volume = storageVolumes.find(
                                    (item) => item.volume_ref === value,
                                  )
                                  const name = mountNameFromVolume(value)
                                  setMountResources((items) =>
                                    items.map((item, i) =>
                                      i === index
                                        ? {
                                            ...item,
                                            name,
                                            volumeRef: value,
                                            subPath: volume?.allowed_prefixes?.[0] || '',
                                            mountPath: defaultMountPath(name),
                                            access: 'read_only',
                                          }
                                        : item,
                                    ),
                                  )
                                }}
                              >
                                <SelectTrigger>
                                  <SelectValue placeholder="选择数据卷" />
                                </SelectTrigger>
                                <SelectContent>
                                  {storageVolumes.map((volume) => (
                                    <SelectItem key={volume.volume_ref} value={volume.volume_ref}>
                                      {volume.display_name || volume.volume_ref}
                                    </SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                            </label>
                            <label className="space-y-1 text-sm">
                              <span className="font-medium">
                                访问权限{' '}
                                <FieldHelp text="只读模式下 Agent 只能读取文件，无法修改；读写模式允许 Agent 创建和修改文件。不能超过平台管理员授予的最大权限。" />
                              </span>
                              <Select
                                value={resource.access}
                                onValueChange={(value) =>
                                  setMountResources((items) =>
                                    items.map((item, i) =>
                                      i === index
                                        ? { ...item, access: value as MountResourceForm['access'] }
                                        : item,
                                    ),
                                  )
                                }
                              >
                                <SelectTrigger>
                                  <SelectValue placeholder="选择访问权限" />
                                </SelectTrigger>
                                <SelectContent>
                                  <SelectItem value="read_only">只读</SelectItem>
                                  {canWrite && <SelectItem value="read_write">读写</SelectItem>}
                                </SelectContent>
                              </Select>
                            </label>
                            <label className="space-y-1 text-sm">
                              <span className="font-medium">
                                子目录{' '}
                                <FieldHelp text="存储卷内的子目录路径（相对路径）。留空则挂载整个存储卷根目录。必须在管理员配置的允许前缀范围内。" />
                              </span>
                              <Input
                                value={resource.subPath}
                                placeholder="tenant-a/project-x"
                                onChange={(event) =>
                                  setMountResources((items) =>
                                    items.map((item, i) =>
                                      i === index ? { ...item, subPath: event.target.value } : item,
                                    ),
                                  )
                                }
                              />
                            </label>
                            <label className="space-y-1 text-sm">
                              <span className="font-medium">
                                沙箱路径{' '}
                                <FieldHelp text="数据卷在沙箱容器内的挂载位置。必须是 /workspace/ 下的绝对路径，Agent 通过这个路径读写文件。" />
                              </span>
                              <Input
                                value={resource.mountPath}
                                placeholder="/workspace/storage/data"
                                onChange={(event) =>
                                  setMountResources((items) =>
                                    items.map((item, i) =>
                                      i === index
                                        ? { ...item, mountPath: event.target.value }
                                        : item,
                                    ),
                                  )
                                }
                              />
                            </label>
                          </div>
                          {selected?.allowed_prefixes && selected.allowed_prefixes.length > 0 && (
                            <p className="mt-2 text-xs text-muted-foreground">
                              允许前缀：{selected.allowed_prefixes.join(', ')}
                            </p>
                          )}
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>

              <div className="pt-4">
                <div className="mb-3 flex items-center justify-between gap-2">
                  <div>
                    <FormFieldLabel optional={t('managed.environments.optional')}>
                      {t('managed.environments.egressServices')}
                    </FormFieldLabel>
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
            </AdvancedSection>
          </div>
          <FormActionBar>
            <Button variant="outline" onClick={() => resetDialog(false)}>
              {t('common.cancel')}
            </Button>
            <Button onClick={handleCreate} disabled={creating}>
              {creating ? t('managed.environments.creating') : t('managed.environments.add')}
            </Button>
          </FormActionBar>
        </DialogContent>
      </Dialog>
    </div>
  )
}
