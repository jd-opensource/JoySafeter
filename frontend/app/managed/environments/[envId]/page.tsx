'use client'

import React, { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Save } from 'lucide-react'
import { useTranslation } from '@/lib/i18n'
import { managedGet, managedPost } from '@/lib/api-client'
import { apiResourceId, apiResourcePath } from '@/lib/managed/api-paths'
import { shouldRetryManagedResourceError, toastOperationError } from '@/lib/managed/errors'
import {
  hasManagedRequestScope,
  managedRequestOptions,
  managedScopeKey,
  useManagedRequestScope,
} from '@/lib/managed/request-scope'
import type { ManagedRequestScope } from '@/lib/managed/request-scope'
import type { Environment, Secret } from '@/types/managed'
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
  envId: string
  rawId: string
  payload: {
    name: string
    description: string
    config: Record<string, unknown>
  }
  requestScope: ManagedRequestScope
  runId: number
  scope: string
}

export default function EnvironmentDetailPage({ params }: { params: Promise<{ envId: string }> }) {
  const { envId: rawId } = React.use(params)
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
  const projectReadOnly = useCurrentProjectReadOnly()
  const managedScope = useManagedRequestScope()
  const envId = apiResourceId(rawId || '')
  const operationScope = `${managedScope.key}:${rawId ?? ''}`
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
    queryKey: ['environment', managedScope.key, rawId],
    queryFn: () =>
      managedGet<Environment>(
        apiResourcePath('environments', envId),
        managedRequestOptions(managedScope),
      ),
    enabled: !!rawId && hasManagedRequestScope(managedScope),
    retry: shouldRetryManagedResourceError,
  })
  const { data: secrets } = usePaginatedList<Secret>({
    queryKey: 'secrets',
    path: '/secrets',
    limit: 50,
  })

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [networkType, setNetworkType] = useState('limited')
  const [allowedHosts, setAllowedHosts] = useState('')
  const [aptPackages, setAptPackages] = useState('')
  const [pipPackages, setPipPackages] = useState('')
  const [npmPackages, setNpmPackages] = useState('')
  const [envVars, setEnvVars] = useState('')
  const [secretRefs, setSecretRefs] = useState('')
  const [egressServices, setEgressServices] = useState<EgressServiceForm[]>([])
  const [egressErrors, setEgressErrors] = useState<EgressServiceErrors>({})
  const [dirty, setDirty] = useState(false)

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
      setNetworkType(env.config?.networking?.type || 'limited')
      setAllowedHosts(env.config?.networking?.allowed_hosts?.join(', ') || '')
      setAptPackages(env.config?.packages?.apt?.join(', ') || '')
      setPipPackages(env.config?.packages?.pip?.join(', ') || '')
      setNpmPackages(env.config?.packages?.npm?.join(', ') || '')
      setEnvVars(
        Object.entries(env.config?.env_vars || {})
          .map(([k, v]) => `${k}=${v}`)
          .join(', '),
      )
      setSecretRefs(env.config?.secret_refs?.join(', ') || '')
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

    const refs = splitList(secretRefs)
    if (refs.length > 0) config.secret_refs = refs

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
    return `${managedScopeKey(orgId, projectId)}:${rawId ?? ''}`
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
      rawId,
    ])
    return current?.id === rawId && !current.archived_at ? current : null
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
      )
    },
    onSuccess: (_data, { rawId, requestScope, runId, scope }) => {
      if (!isCurrentSaveRun(runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['environment', requestScope.key, rawId] })
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
        <div className="space-y-2">
          <label className="text-sm font-medium">{t('managed.environments.name')}</label>
          <Input
            value={name}
            onChange={(e) => {
              setName(e.target.value)
              setDirty(true)
            }}
          />
        </div>

        <div className="space-y-2">
          <label className="text-sm font-medium">{t('managed.environments.description')}</label>
          <Input
            value={description}
            onChange={(e) => {
              setDescription(e.target.value)
              setDirty(true)
            }}
          />
        </div>

        <div className="border-t pt-4">
          <h4 className="mb-3 text-sm font-medium">{t('managed.environments.networking')}</h4>
          <div className="space-y-3">
            <Select
              value={networkType}
              onValueChange={(value) => {
                setNetworkType(value)
                setDirty(true)
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="unrestricted">
                  {t('managed.environments.netUnrestricted')}
                </SelectItem>
                <SelectItem value="limited">{t('managed.environments.netLimited')}</SelectItem>
              </SelectContent>
            </Select>
            {networkType === 'limited' && (
              <div className="space-y-1">
                <label className="text-sm font-medium">
                  {t('managed.environments.allowedHosts')}
                </label>
                <Input
                  placeholder="api.example.com, github.com"
                  value={allowedHosts}
                  onChange={(e) => {
                    setAllowedHosts(e.target.value)
                    setDirty(true)
                  }}
                />
              </div>
            )}
          </div>
        </div>

        <div className="border-t pt-4">
          <h4 className="mb-3 text-sm font-medium">{t('managed.environments.envVarsLabel')}</h4>
          <Input
            value={envVars}
            onChange={(e) => {
              setEnvVars(e.target.value)
              setDirty(true)
            }}
            placeholder="KEY=value, NODE_ENV=production"
          />
        </div>

        <div className="border-t pt-4">
          <h4 className="mb-3 text-sm font-medium">{t('managed.environments.secretRefsLabel')}</h4>
          <Input
            value={secretRefs}
            onChange={(e) => {
              setSecretRefs(e.target.value)
              setDirty(true)
            }}
            placeholder="my-api-secret, db-credentials"
          />
        </div>

        <div className="pt-4">
          <div className="mb-3 flex items-center justify-between gap-2">
            <div>
              <h4 className="text-sm font-medium">{t('managed.environments.egressServices')}</h4>
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

        <div className="border-t pt-4">
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
                  if (!svc.credentialRef.trim()) e.credentialRef = t('managed.environments.validation.required')
                  if (svc.authType === 'cookie' && !svc.secretKey.trim()) e.secretKey = t('managed.environments.validation.cookieRequired')
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
                  rawId,
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
        </div>
      </fieldset>
    </div>
  )
}
