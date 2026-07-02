'use client'

import React, { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Save } from 'lucide-react'
import { useTranslation } from '@/lib/i18n'
import { managedGet, managedPost } from '@/lib/api-client'
import { shouldRetryManagedResourceError, toastOperationError } from '@/lib/managed/errors'
import { stripIdPrefix } from '@/lib/managed/id'
import type { Environment } from '@/types/managed'
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

export default function EnvironmentDetailPage({ params }: { params: Promise<{ envId: string }> }) {
  const { envId: rawId } = React.use(params)
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
  const envId = stripIdPrefix(rawId || '')

  const {
    data: env,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ['environment', rawId],
    queryFn: () => managedGet<Environment>(`/environments/${envId}`),
    enabled: !!rawId,
    retry: shouldRetryManagedResourceError,
  })

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [networkType, setNetworkType] = useState('unrestricted')
  const [allowedHosts, setAllowedHosts] = useState('')
  const [aptPackages, setAptPackages] = useState('')
  const [pipPackages, setPipPackages] = useState('')
  const [npmPackages, setNpmPackages] = useState('')
  const [envVars, setEnvVars] = useState('')
  const [secretRefs, setSecretRefs] = useState('')

  useEffect(() => {
    if (env) {
      setName(env.name)
      setDescription(env.description || '')
      setNetworkType(env.config?.networking?.type || 'unrestricted')
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
    }
  }, [env])

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

  const saveMutation = useMutation({
    mutationFn: () => {
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

      return managedPost<Environment>(`/environments/${envId}`, {
        name: name.trim(),
        description: description.trim(),
        config,
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['environment', rawId] })
      queryClient.invalidateQueries({ queryKey: ['environments'] })
      router.push('/managed/environments')
    },
    onError: (error) => {
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

      <fieldset disabled={!!env.archived_at} className="mt-6 max-w-2xl space-y-6">
        <div className="space-y-2">
          <label className="text-sm font-medium">{t('managed.environments.name')}</label>
          <Input value={name} onChange={(e) => setName(e.target.value)} />
        </div>

        <div className="space-y-2">
          <label className="text-sm font-medium">{t('managed.environments.description')}</label>
          <Input value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>

        <div className="border-t pt-4">
          <h4 className="mb-3 text-sm font-medium">{t('managed.environments.networking')}</h4>
          <div className="space-y-3">
            <Select value={networkType} onValueChange={setNetworkType}>
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
          <h4 className="mb-3 text-sm font-medium">{t('managed.environments.packages')}</h4>
          <div className="space-y-3">
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">apt</label>
              <Input
                value={aptPackages}
                onChange={(e) => setAptPackages(e.target.value)}
                placeholder="curl, git"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">pip</label>
              <Input
                value={pipPackages}
                onChange={(e) => setPipPackages(e.target.value)}
                placeholder="numpy, pandas"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">npm</label>
              <Input
                value={npmPackages}
                onChange={(e) => setNpmPackages(e.target.value)}
                placeholder="typescript, eslint"
              />
            </div>
          </div>
        </div>

        <div className="border-t pt-4">
          <h4 className="mb-3 text-sm font-medium">{t('managed.environments.envVarsLabel')}</h4>
          <Input
            value={envVars}
            onChange={(e) => setEnvVars(e.target.value)}
            placeholder="KEY=value, NODE_ENV=production"
          />
        </div>

        <div className="border-t pt-4">
          <h4 className="mb-3 text-sm font-medium">{t('managed.environments.secretRefsLabel')}</h4>
          <Input
            value={secretRefs}
            onChange={(e) => setSecretRefs(e.target.value)}
            placeholder="my-api-secret, db-credentials"
          />
        </div>

        <div className="border-t pt-4">
          {env.archived_at ? (
            <p className="text-sm text-muted-foreground">{t('managed.errors.projectArchived')}</p>
          ) : (
            <Button
              onClick={() => saveMutation.mutate()}
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
