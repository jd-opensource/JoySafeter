'use client'

import React, { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Save } from 'lucide-react'
import { useTranslation } from '@/lib/i18n'
import { managedGet, managedPost } from '@/lib/api-client'
import { apiResourcePath } from '@/lib/managed/api-paths'
import { parseEnvironmentResponse } from '@/lib/managed/environment-response-parsers'
import { parseCredentialResponse } from '@/lib/managed/credential-response-parsers'
import { shouldRetryManagedResourceError, toastOperationError } from '@/lib/managed/errors'
import {
  hasManagedRequestScope,
  managedRequestOptions,
  managedScopeKey,
  useManagedRequestScope,
} from '@/lib/managed/request-scope'
import type { ManagedRequestScope } from '@/lib/managed/request-scope'
import type {
  Environment,
  EnvironmentMountResource,
  Credential,
  StorageVolumeCatalogItem,
} from '@/types/managed'
import { parseEnvironmentId, parseCredentialId, type EnvironmentId } from '@/types/entity-id'
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
  StatusBadge,
  MonoId,
  RelativeTime,
  ResourceErrorState,
  FieldHelp,
  AdvancedSection,
  FormActionBar,
  FormFieldLabel,
  FormSectionCard,
  withEntityRouteGuard,
} from '@/components/managed/shared'
import { useProjectStore } from '@/stores/managed/project-store'
import {
  currentProjectAllowsWrite,
  useCurrentProjectReadOnly,
} from '@/hooks/managed/use-current-project-read-only'
import {
  EgressServicesEditor,
  buildEgressServices,
  emptyEgressService,
  serviceToForm,
  type EgressServiceErrorField,
  type EgressServiceErrors,
  type EgressServiceForm,
} from '@/components/managed/environments-egress-editor'
import { usePaginatedList } from '@/hooks/managed/use-paginated-list'

interface SaveEnvironmentVariables {
  envId: EnvironmentId
  payload: {
    name: string
    description: string
    config: Record<string, unknown>
  }
  requestScope: ManagedRequestScope
  runId: number
  scope: string
}

type MountResourceForm = {
  name: string
  volumeRef: string
  subPath: string
  mountPath: string
  access: 'read_only' | 'read_write'
  required: boolean
}

const mountNameFromVolume = (volumeRef: string) =>
  volumeRef
    .replace(/^storage[-_]?/, '')
    .replace(/[^a-zA-Z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '') || 'storage-data'

const defaultMountPath = (name: string) => `/workspace/storage/${name || 'data'}`

const mountResourceToForm = (resource: EnvironmentMountResource): MountResourceForm => ({
  name: resource.name || mountNameFromVolume(resource.volume_ref || ''),
  volumeRef: resource.volume_ref || '',
  subPath: resource.sub_path || '',
  mountPath: resource.mount_path || defaultMountPath(resource.name || 'data'),
  access: resource.access === 'read_write' ? 'read_write' : 'read_only',
  required: resource.required !== false,
})

export default withEntityRouteGuard(EnvironmentDetailPageInner, {
  kind: 'environment',
  paramKey: 'envId',
  backTo: '/managed/environments',
})

function EnvironmentDetailPageInner({ params }: { params: Promise<{ envId: string }> }) {
  const { envId: rawId } = React.use(params)
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
  const projectReadOnly = useCurrentProjectReadOnly()
  const managedScope = useManagedRequestScope()
  const envId = parseEnvironmentId(rawId)
  const operationScope = `${managedScope.key}:${envId}`
  const saveRunRef = useRef(0)
  const operationScopeRef = useRef(operationScope)
  const managedRequestScopeRef = useRef<ManagedRequestScope>(managedScope)
  const hydratedEnvironmentScopeRef = useRef<string | null>(null)

  const {
    data: env,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ['environment', managedScope.key, envId],
    queryFn: () =>
      managedGet<Environment>(
        apiResourcePath('environments', envId),
        managedRequestOptions(managedScope),
      ).then(parseEnvironmentResponse),
    enabled: hasManagedRequestScope(managedScope),
    retry: shouldRetryManagedResourceError,
  })
  const { data: secrets } = usePaginatedList<Credential>({
    queryKey: 'service-credentials',
    path: '/credentials?kind=service',
    includeArchived: false,
    limit: 50,
    parseItem: parseCredentialResponse,
    parseCursor: parseCredentialId,
  })
  const { data: storageCatalog } = useQuery({
    queryKey: ['storage-mount-catalog', managedScope.key],
    queryFn: () => managedGet<{ data: StorageVolumeCatalogItem[] }>('/storage-volumes/catalog'),
    enabled: hasManagedRequestScope(managedScope),
    staleTime: 60_000,
  })
  const storageVolumes = storageCatalog?.data || []

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [networkType, setNetworkType] = useState('limited')
  const [allowedHosts, setAllowedHosts] = useState('')
  const [aptPackages, setAptPackages] = useState('')
  const [pipPackages, setPipPackages] = useState('')
  const [npmPackages, setNpmPackages] = useState('')
  const [envVars, setEnvVars] = useState('')
  const [mountResources, setMountResources] = useState<MountResourceForm[]>([])
  const [egressServices, setEgressServices] = useState<EgressServiceForm[]>([])
  const [egressErrors, setEgressErrors] = useState<EgressServiceErrors>({})
  const [dirty, setDirty] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)

  useEffect(() => {
    if (operationScopeRef.current !== operationScope) {
      operationScopeRef.current = operationScope
      managedRequestScopeRef.current = managedScope
      saveRunRef.current += 1
    }
  }, [operationScope])

  useEffect(
    () => () => {
      saveRunRef.current += 1
    },
    [],
  )

  useEffect(() => {
    if (env) {
      const shouldHydrate = !dirty || hydratedEnvironmentScopeRef.current !== operationScope
      if (!shouldHydrate) return

      setName(env.name)
      setDescription(env.description || '')
      setNetworkType('limited')
      setAllowedHosts(env.config?.networking?.allowed_hosts?.join(', ') || '')
      setAptPackages(env.config?.packages?.apt?.join(', ') || '')
      setPipPackages(env.config?.packages?.pip?.join(', ') || '')
      setNpmPackages(env.config?.packages?.npm?.join(', ') || '')
      setEnvVars(
        Object.entries(env.config?.env_vars || {})
          .map(([k, v]) => `${k}=${v}`)
          .join(', '),
      )
      setMountResources((env.config?.mount_resources || []).map(mountResourceToForm))
      setEgressServices((env.config?.egress_services || []).map(serviceToForm))
      hydratedEnvironmentScopeRef.current = operationScope
      setDirty(false)
    }
  }, [dirty, env, operationScope])

  const splitList = (s: string) =>
    s
      .split(/[\n,]/)
      .map((x) => x.trim())
      .filter(Boolean)

  const parseEnvVarsStr = (s: string): Record<string, string> => {
    const vars: Record<string, string> = {}
    for (const line of splitList(s)) {
      const eqIdx = line.indexOf('=')
      if (eqIdx > 0) {
        vars[line.slice(0, eqIdx).trim()] = line.slice(eqIdx + 1).trim()
      }
    }
    return vars
  }

  const buildSavePayload = (): SaveEnvironmentVariables['payload'] => {
    const config: Record<string, unknown> = {
      type: 'cloud',
      networking: {
        type: networkType,
        ...(networkType === 'limited' && allowedHosts.trim()
          ? { allowed_hosts: splitList(allowedHosts) }
          : {}),
      },
    }
    const packages: Record<string, string[]> = {}
    if (aptPackages.trim()) packages.apt = splitList(aptPackages)
    if (pipPackages.trim()) packages.pip = splitList(pipPackages)
    if (npmPackages.trim()) packages.npm = splitList(npmPackages)
    if (Object.keys(packages).length > 0) config.packages = packages

    const ev = parseEnvVarsStr(envVars)
    if (Object.keys(ev).length > 0) config.env_vars = ev

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

    const services = buildEgressServices(egressServices)
    if (services.length > 0) config.egress_services = services

    return {
      name: name.trim(),
      description: description.trim(),
      config,
    }
  }

  const getCurrentOperationScope = () => {
    const { currentOrgId: orgId, currentProjectId: projectId } = useProjectStore.getState()
    return `${managedScopeKey(orgId, projectId)}:${envId}`
  }

  const getCurrentManagedScope = () => {
    const { currentOrgId: orgId, currentProjectId: projectId } = useProjectStore.getState()
    return managedScopeKey(orgId, projectId)
  }

  const currentOperationScopeIsActive = (scope = operationScopeRef.current) =>
    operationScopeRef.current === scope && getCurrentOperationScope() === scope

  const currentEditableEnvironment = () => {
    if (!currentOperationScopeIsActive()) return null
    if (!currentProjectAllowsWrite()) return null
    const current = queryClient.getQueryData<Environment>([
      'environment',
      getCurrentManagedScope(),
      envId,
    ])
    return current?.id === envId && !current.archived_at ? current : null
  }

  const isCurrentSaveRun = (runId: number, scope: string) =>
    saveRunRef.current === runId &&
    operationScopeRef.current === scope &&
    getCurrentOperationScope() === scope

  const saveMutation = useMutation({
    mutationFn: async ({
      envId,
      payload,
      requestScope,
      runId,
      scope,
    }: SaveEnvironmentVariables) => {
      if (!isCurrentSaveRun(runId, scope)) {
        return undefined as unknown as Environment
      }
      if (!currentProjectAllowsWrite()) {
        return undefined as unknown as Environment
      }
      return managedPost<Environment>(
        apiResourcePath('environments', envId),
        payload,
        managedRequestOptions(requestScope),
      ).then(parseEnvironmentResponse)
    },
    onSuccess: (_data, { envId, requestScope, runId, scope }) => {
      if (!isCurrentSaveRun(runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['environment', requestScope.key, envId] })
      queryClient.invalidateQueries({ queryKey: ['environments', requestScope.key] })
      router.push('/managed/environments')
    },
    onError: (error, { runId, scope }) => {
      if (!isCurrentSaveRun(runId, scope)) return
      toastOperationError(t, error, 'common.operationFailed')
    },
  })

  if (isError) {
    return (
      <ResourceErrorState
        error={error}
        resource="environment"
        onBack={() => router.push('/managed/environments')}
      />
    )
  }

  if (isLoading || !env) {
    return <div className="text-muted-foreground">{t('common.loading')}</div>
  }

  const isReadOnly = !!env.archived_at || projectReadOnly

  return (
    <div>
      <PageHeader
        title={env.name}
        titleExtra={<StatusBadge status={env.archived_at ? 'archived' : 'active'} />}
        breadcrumb={[
          {
            label: t('managed.environments.title'),
            to: '/managed/environments',
          },
          { label: env.name },
        ]}
        action={
          <Button size="sm" onClick={() => router.push('/managed/environments')}>
            <ArrowLeft className="h-4 w-4" />
            {t('common.back')}
          </Button>
        }
      />

      <div className="mb-6 flex items-center gap-1.5 text-sm text-muted-foreground">
        <MonoId id={env.id} truncate={false} />
        <span>·</span>
        <RelativeTime date={env.created_at} />
      </div>

      <fieldset disabled={isReadOnly} className="mt-6 max-w-2xl space-y-6">
        <FormSectionCard
          title={t('managed.environments.basicSettings', '基础配置')}
          description={t(
            'managed.environments.basicSettingsDesc',
            '设置环境名称、用途和默认网络访问策略。',
          )}
        >
          <div className="space-y-2">
            <FormFieldLabel required>{t('managed.environments.name')}</FormFieldLabel>
            <Input
              value={name}
              placeholder={t('managed.environments.namePlaceholder')}
              onChange={(e) => {
                setName(e.target.value)
                setDirty(true)
              }}
            />
          </div>

          <div className="space-y-2">
            <FormFieldLabel optional={t('managed.environments.optional')}>
              {t('managed.environments.description')}
            </FormFieldLabel>
            <Input
              value={description}
              placeholder={t('managed.environments.descPlaceholder')}
              onChange={(e) => {
                setDescription(e.target.value)
                setDirty(true)
              }}
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
              <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                {t('managed.environments.netLimited')}
              </div>
              <p className="mt-2 text-xs leading-5 text-muted-foreground">
                {t(
                  'managed.environments.netLimitedDesc',
                  '默认禁止外网访问，仅允许白名单主机和已配置的第三方服务。',
                )}
              </p>
              {networkType === 'limited' && (
                <div className="border-border/70 mt-3 space-y-1.5 border-t pt-3">
                  <FormFieldLabel optional={t('managed.environments.optional')}>
                    {t('managed.environments.allowedHosts')}
                  </FormFieldLabel>
                  <textarea
                    placeholder={t(
                      'managed.environments.allowedHostsPlaceholder',
                      'api.example.com\ngithub.com\n*.internal.example.com',
                    )}
                    value={allowedHosts}
                    onChange={(e) => {
                      setAllowedHosts(e.target.value)
                      setDirty(true)
                    }}
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
            'managed.environments.advancedSummaryEdit',
            '环境变量、数据卷挂载、第三方服务',
          )}
        >
          <div>
            <FormFieldLabel
              optional={t('managed.environments.optional')}
              tooltip={t(
                'managed.environments.envVarsHint',
                '注入到沙箱的非敏感环境变量。格式：KEY=value，逗号或换行分隔。不要填写 token、cookie、API key 等敏感值；请改存到服务凭据中。',
              )}
              className="mb-3"
            >
              {t('managed.environments.envVarsLabel')}
            </FormFieldLabel>
            <Input
              value={envVars}
              onChange={(e) => {
                setEnvVars(e.target.value)
                setDirty(true)
              }}
              placeholder="KEY=value, NODE_ENV=production"
            />
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
                  const mountName = mountNameFromVolume(first.volume_ref)
                  setMountResources((items) => [
                    ...items,
                    {
                      name: mountName,
                      volumeRef: first.volume_ref,
                      subPath: first.allowed_prefixes?.[0] || '',
                      mountPath: defaultMountPath(mountName),
                      access: 'read_only',
                      required: true,
                    },
                  ])
                  setDirty(true)
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
                          onClick={() => {
                            setMountResources((items) =>
                              items.filter((_, itemIndex) => itemIndex !== index),
                            )
                            setDirty(true)
                          }}
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
                              const mountName = mountNameFromVolume(value)
                              setMountResources((items) =>
                                items.map((item, itemIndex) =>
                                  itemIndex === index
                                    ? {
                                        ...item,
                                        name: mountName,
                                        volumeRef: value,
                                        subPath: volume?.allowed_prefixes?.[0] || '',
                                        mountPath: defaultMountPath(mountName),
                                        access: 'read_only',
                                      }
                                    : item,
                                ),
                              )
                              setDirty(true)
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
                            onValueChange={(value) => {
                              setMountResources((items) =>
                                items.map((item, itemIndex) =>
                                  itemIndex === index
                                    ? { ...item, access: value as MountResourceForm['access'] }
                                    : item,
                                ),
                              )
                              setDirty(true)
                            }}
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
                            onChange={(event) => {
                              setMountResources((items) =>
                                items.map((item, itemIndex) =>
                                  itemIndex === index
                                    ? { ...item, subPath: event.target.value }
                                    : item,
                                ),
                              )
                              setDirty(true)
                            }}
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
                            onChange={(event) => {
                              setMountResources((items) =>
                                items.map((item, itemIndex) =>
                                  itemIndex === index
                                    ? { ...item, mountPath: event.target.value }
                                    : item,
                                ),
                              )
                              setDirty(true)
                            }}
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
                onClick={() => {
                  setEgressServices((items) => [...items, emptyEgressService()])
                  setDirty(true)
                }}
              >
                {t('managed.environments.addEgressService')}
              </Button>
            </div>
            <EgressServicesEditor
              services={egressServices}
              setServices={setEgressServices}
              secrets={secrets}
              errors={egressErrors}
              onClearFieldError={(index, field) => {
                setEgressErrors((prev) => {
                  const next = { ...prev }
                  if (next[index]) {
                    next[index] = { ...next[index], [field]: undefined }
                    if (Object.values(next[index]).every((v) => !v)) delete next[index]
                  }
                  return next
                })
              }}
              onDirty={() => setDirty(true)}
              onRemove={(index) => {
                setEgressServices((items) => items.filter((_, i) => i !== index))
                setEgressErrors((prev) => {
                  const next = { ...prev }
                  delete next[index]
                  return next
                })
                setDirty(true)
              }}
            />
          </div>
        </AdvancedSection>

        <FormActionBar className="mx-0">
          {isReadOnly ? (
            <p className="text-sm text-muted-foreground">{t('managed.errors.projectArchived')}</p>
          ) : (
            <Button
              onClick={() => {
                // Validate egress services before save
                const errors: EgressServiceErrors = {}
                egressServices.forEach((svc, idx) => {
                  const e: Record<string, string> = {}
                  if (!svc.name.trim()) e.name = t('managed.environments.validation.required')
                  if (!svc.baseUrl.trim()) e.baseUrl = t('managed.environments.validation.required')
                  if (!svc.credentialRef.trim())
                    e.credentialRef = t('managed.environments.validation.required')
                  if (svc.authType === 'cookie' && !svc.secretKey.trim())
                    e.secretKey = t('managed.environments.validation.cookieRequired')
                  if (Object.keys(e).length) errors[idx] = e
                })
                setEgressErrors(errors)
                if (Object.keys(errors).length > 0) return

                if (!currentEditableEnvironment()) return
                const requestScope = managedRequestScopeRef.current
                const scope = operationScopeRef.current
                if (!currentOperationScopeIsActive(scope)) return
                const runId = saveRunRef.current + 1
                saveRunRef.current = runId
                saveMutation.mutate({
                  envId,
                  payload: buildSavePayload(),
                  requestScope,
                  runId,
                  scope,
                })
              }}
              disabled={!name.trim() || saveMutation.isPending}
            >
              <Save className="h-4 w-4" />
              {saveMutation.isPending ? t('common.loading') : t('managed.environments.save')}
            </Button>
          )}
        </FormActionBar>
      </fieldset>
    </div>
  )
}
