'use client'

import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'

import { CronEditor } from '@/components/managed/schedules/cron-editor'
import { SearchableSelect } from '@/components/managed/schedules/searchable-select'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { managedGet } from '@/lib/api-client'
import { currentProjectAllowsWrite } from '@/hooks/managed/use-current-project-read-only'
import { useTranslation } from '@/lib/i18n'

import { detectBrowserTimezone, isValidCron } from '@/lib/managed/cron'
import { toastOperationError } from '@/lib/managed/errors'
import { apiResourceId } from '@/lib/managed/api-paths'
import {
  hasManagedRequestScope,
  managedRequestOptions,
  managedScopeKey,
  type ManagedRequestScope,
  useManagedRequestScope,
} from '@/lib/managed/request-scope'
import {
  useCreateSchedule,
  useUpdateSchedule,
  type Schedule,
  type ScheduleConcurrencyPolicy,
  type ScheduleSessionMode,
} from '@/lib/managed/schedules'
import { useProjectStore } from '@/stores/managed/project-store'

interface AgentOption {
  id: string
  name: string
  engine_kind?: string | null
  model?: { id?: string } | null
  archived_at?: string | null
}

interface EnvironmentOption {
  id: string
  name: string
  config?: { type?: string; networking?: { type?: string } } | null
  archived_at?: string | null
}

interface SessionOption {
  id: string
  title?: string | null
  status?: string | null
  archived_at?: string | null
}

interface CreateScheduleDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** When provided, the dialog edits an existing schedule instead of creating. */
  schedule?: Schedule | null
}

const POLICIES: ScheduleConcurrencyPolicy[] = ['allow', 'forbid', 'replace']
const SESSION_MODES: ScheduleSessionMode[] = ['fresh', 'reuse', 'pinned']

// Sentinel Select value for "no explicit environment" — radix Select cannot use
// an empty-string item value, so we map this to `environment_ref = null`, which
// makes the backend fall back to the agent's default environment at fire time.
const FOLLOW_AGENT_ENV = '__agent_default__'

export function CreateScheduleDialog({ open, onOpenChange, schedule }: CreateScheduleDialogProps) {
  const { t } = useTranslation()
  const isEdit = !!schedule
  const createMut = useCreateSchedule()
  const updateMut = useUpdateSchedule()
  const locale = (t('_locale') === 'zh' ? 'zh' : 'en') as 'en' | 'zh'
  const managedScope = useManagedRequestScope()
  const managedScopeRef = useRef(managedScope.key)
  const managedRequestScopeRef = useRef<ManagedRequestScope>(managedScope)
  const submitRunRef = useRef(0)

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [agentId, setAgentId] = useState('')
  const [environmentRef, setEnvironmentRef] = useState('')
  const [prompt, setPrompt] = useState('')
  const [cron, setCron] = useState('0 9 * * *')
  const [tz, setTz] = useState('UTC')
  const [policy, setPolicy] = useState<ScheduleConcurrencyPolicy>('allow')
  const [sessionMode, setSessionMode] = useState<ScheduleSessionMode>('fresh')
  const [pinnedSessionId, setPinnedSessionId] = useState('')
  const [timeoutSec, setTimeoutSec] = useState(7200)
  const [maxRetries, setMaxRetries] = useState(2)
  const [enabled, setEnabled] = useState(true)

  const agentsQuery = useQuery({
    queryKey: ['agents', managedScope.key, 'for-schedule'],
    queryFn: () =>
      managedGet<AgentOption[] | { data: AgentOption[] }>(
        '/agents?limit=100',
        managedRequestOptions(managedScope),
      ),
    enabled: open && hasManagedRequestScope(managedScope),
  })
  const agents: AgentOption[] = useMemo(() => {
    const raw = agentsQuery.data
    const list = Array.isArray(raw) ? raw : (raw?.data ?? [])
    return list.filter((a) => !a.archived_at)
  }, [agentsQuery.data])
  const agentOptions = useMemo(
    () =>
      agents.map((agent) => ({
        value: apiResourceId(agent.id),
        searchText: `${agent.name} ${agent.engine_kind || ''} ${agent.model?.id || ''}`,
        label: (
          <div className="flex items-center gap-2">
            <span className="truncate">{agent.name}</span>
            {agent.engine_kind && (
              <span className="shrink-0 rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                {agent.engine_kind}
              </span>
            )}
            {agent.model?.id && (
              <span className="shrink-0 truncate text-[10px] text-muted-foreground">
                {agent.model.id}
              </span>
            )}
          </div>
        ),
      })),
    [agents],
  )

  const environmentsQuery = useQuery({
    queryKey: ['environments', managedScope.key, 'for-schedule'],
    queryFn: () =>
      managedGet<EnvironmentOption[] | { data: EnvironmentOption[] }>(
        '/environments?limit=100',
        managedRequestOptions(managedScope),
      ),
    enabled: open && hasManagedRequestScope(managedScope),
  })
  const environments: EnvironmentOption[] = useMemo(() => {
    const raw = environmentsQuery.data
    const list = Array.isArray(raw) ? raw : (raw?.data ?? [])
    return list.filter((e) => !e.archived_at)
  }, [environmentsQuery.data])
  const environmentOptions = useMemo(
    () => [
      {
        value: FOLLOW_AGENT_ENV,
        label: t('managed.schedules.envFollowAgent'),
        searchText: t('managed.schedules.envFollowAgent'),
      },
      ...environments.map((env) => {
        const netType = env.config?.networking?.type || env.config?.type || ''
        return {
          value: env.id,
          searchText: `${env.name} ${env.id} ${netType}`,
          label: (
            <div className="flex items-center gap-2">
              <span className="truncate">{env.name}</span>
              {netType && (
                <span className="shrink-0 rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                  {netType}
                </span>
              )}
            </div>
          ),
        }
      }),
    ],
    [environments, t],
  )

  const policyOptions = useMemo(
    () =>
      POLICIES.map((policyValue) => ({
        value: policyValue,
        label: t(`managed.schedules.policy.${policyValue}`),
        searchText: t(`managed.schedules.policy.${policyValue}`),
      })),
    [t],
  )

  const sessionModeOptions = useMemo(
    () =>
      SESSION_MODES.map((mode) => ({
        value: mode,
        label: t(`managed.schedules.sessionModeOption.${mode}`),
        searchText: `${t(`managed.schedules.sessionModeOption.${mode}`)} ${t(`managed.schedules.sessionModeHint.${mode}`)}`,
      })),
    [t],
  )

  const sessionsQuery = useQuery({
    queryKey: ['agent-sessions', managedScope.key, agentId, 'for-schedule'],
    queryFn: () =>
      managedGet<{ data: SessionOption[] } | SessionOption[]>(
        `/agents/${agentId}/sessions?limit=100`,
        managedRequestOptions(managedScope),
      ),
    enabled: open && !!agentId && hasManagedRequestScope(managedScope),
  })
  const sessions: SessionOption[] = useMemo(() => {
    const raw = sessionsQuery.data
    const list = Array.isArray(raw) ? raw : (raw?.data ?? [])
    return list.filter((s) => !s.archived_at)
  }, [sessionsQuery.data])
  const sessionOptions = useMemo(
    () =>
      sessions.map((session) => ({
        value: apiResourceId(session.id),
        label: session.title?.trim() || session.id,
        searchText: `${session.title || ''} ${session.id} ${session.status || ''}`,
      })),
    [sessions],
  )

  const getCurrentManagedScope = () => {
    const { currentOrgId: orgId, currentProjectId: projectId } = useProjectStore.getState()
    return managedScopeKey(orgId, projectId)
  }

  const currentManagedScopeIsActive = (scope = managedScopeRef.current) =>
    scope === managedScopeRef.current && scope === getCurrentManagedScope()

  const isCurrentSubmitRun = (runId: number, scope: string) =>
    runId === submitRunRef.current &&
    currentManagedScopeIsActive(scope) &&
    currentProjectAllowsWrite()

  useEffect(() => {
    if (managedScopeRef.current === managedScope.key) return
    managedScopeRef.current = managedScope.key
    managedRequestScopeRef.current = managedScope
    submitRunRef.current += 1
    onOpenChange(false)
  }, [managedScope.key, onOpenChange])

  useEffect(
    () => () => {
      submitRunRef.current += 1
    },
    [],
  )

  // Seed form when opening (create defaults or edit values).
  useEffect(() => {
    if (!open) return
    if (schedule) {
      setName(schedule.name)
      setDescription(schedule.description ?? '')
      setAgentId(apiResourceId(schedule.agent_id))
      setEnvironmentRef(schedule.environment_ref ?? '')
      setPrompt(schedule.prompt)
      setCron(schedule.cron_expr)
      setTz(schedule.timezone)
      setPolicy(schedule.concurrency_policy)
      setSessionMode(schedule.session_mode || 'fresh')
      setPinnedSessionId(schedule.pinned_session_id ? apiResourceId(schedule.pinned_session_id) : '')
      setTimeoutSec(schedule.timeout_sec)
      setMaxRetries(schedule.max_retries)
      setEnabled(schedule.enabled)
    } else {
      setName('')
      setDescription('')
      setAgentId('')
      setEnvironmentRef('')
      setPrompt('')
      setCron('0 9 * * *')
      setTz(detectBrowserTimezone())
      setPolicy('allow')
      setSessionMode('fresh')
      setPinnedSessionId('')
      setTimeoutSec(7200)
      setMaxRetries(2)
      setEnabled(true)
    }
  }, [open, schedule])

  const canSubmit =
    name.trim().length > 0 &&
    !!agentId &&
    prompt.trim().length > 0 &&
    isValidCron(cron) &&
    (sessionMode !== 'pinned' || !!pinnedSessionId) &&
    Number.isFinite(timeoutSec) &&
    timeoutSec >= 1 &&
    Number.isFinite(maxRetries) &&
    maxRetries >= 0

  const pending = createMut.isPending || updateMut.isPending

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit || pending) return
    if (!currentProjectAllowsWrite()) {
      onOpenChange(false)
      return
    }
    const requestScope = managedRequestScopeRef.current
    const scopeAtStart = requestScope.key
    if (!currentManagedScopeIsActive(scopeAtStart)) return
    const runId = submitRunRef.current + 1
    submitRunRef.current = runId
    try {
      if (isEdit && schedule) {
        await updateMut.mutateAsync({
          id: schedule.id,
          requestScope,
          body: {
            name: name.trim(),
            description: description.trim() || null,
            prompt: prompt.trim(),
            environment_ref: environmentRef || null,
            cron_expr: cron,
            timezone: tz,
            concurrency_policy: policy,
            session_mode: sessionMode,
            pinned_session_id: sessionMode === 'pinned' ? pinnedSessionId : null,
            timeout_sec: timeoutSec,
            max_retries: maxRetries,
            enabled,
          },
        })
      } else {
        await createMut.mutateAsync({
          requestScope,
          name: name.trim(),
          description: description.trim() || null,
          agent_id: agentId,
          environment_ref: environmentRef || null,
          prompt: prompt.trim(),
          cron_expr: cron,
          timezone: tz,
          concurrency_policy: policy,
          session_mode: sessionMode,
          pinned_session_id: sessionMode === 'pinned' ? pinnedSessionId : null,
          timeout_sec: timeoutSec,
          max_retries: maxRetries,
          enabled,
        })
      }
      if (!isCurrentSubmitRun(runId, scopeAtStart)) return
      onOpenChange(false)
    } catch (err) {
      if (!isCurrentSubmitRun(runId, scopeAtStart)) return
      toastOperationError(t, err, 'managed.schedules.saveFailed')
    }
  }

  const handleOpenChange = (nextOpen: boolean) => {
    if (nextOpen && !currentProjectAllowsWrite()) return
    if (nextOpen && !currentManagedScopeIsActive()) return
    if (!nextOpen) {
      submitRunRef.current += 1
    }
    onOpenChange(nextOpen)
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {isEdit ? t('managed.schedules.editTitle') : t('managed.schedules.createTitle')}
          </DialogTitle>
          <DialogDescription>{t('managed.schedules.createDescription')}</DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="sched-name">{t('managed.table.name')}</Label>
              <Input
                id="sched-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={t('managed.schedules.namePlaceholder')}
              />
            </div>
            <div className="space-y-1.5">
              <Label>{t('managed.schedules.agent')}</Label>
              <SearchableSelect
                value={agentId}
                onChange={(value) => {
                  setAgentId(value)
                  setPinnedSessionId('')
                }}
                disabled={isEdit}
                options={agentOptions}
                placeholder={t('managed.schedules.selectAgent')}
                searchPlaceholder={t('managed.schedules.searchAgent')}
                emptyText={agentsQuery.isLoading ? `${t('common.loading')}…` : t('managed.schedules.noAgentMatch')}
                clearSearchLabel={t('managed.schedules.clearSearch')}
                contentClassName="max-h-[280px]"
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="sched-description">{t('managed.schedules.description')}</Label>
            <Textarea
              id="sched-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              placeholder={t('managed.schedules.descriptionPlaceholder')}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="sched-prompt">{t('managed.schedules.prompt')}</Label>
            <Textarea
              id="sched-prompt"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={3}
              placeholder={t('managed.schedules.promptPlaceholder')}
            />
          </div>

          <div className="space-y-1.5">
            <Label>{t('managed.schedules.runtimeEnvironment')}</Label>
            <SearchableSelect
              value={environmentRef || FOLLOW_AGENT_ENV}
              onChange={(value) => setEnvironmentRef(value === FOLLOW_AGENT_ENV ? '' : value)}
              options={environmentOptions}
              searchPlaceholder={t('managed.schedules.searchEnvironment')}
              emptyText={environmentsQuery.isLoading ? `${t('common.loading')}…` : t('managed.schedules.noEnvironmentMatch')}
              clearSearchLabel={t('managed.schedules.clearSearch')}
              contentClassName="max-h-[280px]"
            />
            <p className="text-xs text-muted-foreground">
              {t('managed.schedules.environmentHint')}
            </p>
          </div>

          <div className="space-y-1.5">
            <Label>{t('managed.schedules.schedule')}</Label>
            <CronEditor
              value={cron}
              timezone={tz}
              onChange={setCron}
              onTimezoneChange={setTz}
              locale={locale}
            />
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1.5">
              <Label>{t('managed.schedules.concurrency')}</Label>
              <SearchableSelect
                value={policy}
                onChange={(value) => setPolicy(value as ScheduleConcurrencyPolicy)}
                options={policyOptions}
                searchPlaceholder={t('managed.schedules.searchPolicy')}
                emptyText={t('managed.schedules.noPolicyMatch')}
                clearSearchLabel={t('managed.schedules.clearSearch')}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="sched-timeout">{t('managed.schedules.timeoutSec')}</Label>
              <Input
                id="sched-timeout"
                type="number"
                min={1}
                value={timeoutSec}
                onChange={(e) => setTimeoutSec(Number(e.target.value) || 0)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="sched-retries">{t('managed.schedules.maxRetries')}</Label>
              <Input
                id="sched-retries"
                type="number"
                min={0}
                value={maxRetries}
                onChange={(e) => setMaxRetries(Number(e.target.value) || 0)}
              />
            </div>
          </div>

          <p className="text-xs text-muted-foreground">{t('managed.schedules.concurrencyHint')}</p>

          <div className="space-y-3 rounded-md border p-3">
            <div className="space-y-1.5">
              <Label>{t('managed.schedules.sessionMode')}</Label>
              <SearchableSelect
                value={sessionMode}
                onChange={(value) => {
                  const mode = value as ScheduleSessionMode
                  setSessionMode(mode)
                  if (mode !== 'pinned') setPinnedSessionId('')
                }}
                options={sessionModeOptions}
                searchPlaceholder={t('managed.schedules.searchSessionMode')}
                emptyText={t('managed.schedules.noSessionModeMatch')}
                clearSearchLabel={t('managed.schedules.clearSearch')}
              />
              <p className="text-xs text-muted-foreground">
                {t(`managed.schedules.sessionModeHint.${sessionMode}`)}
              </p>
            </div>

            {sessionMode === 'pinned' && (
              <div className="space-y-1.5">
                <Label>{t('managed.schedules.pinnedSessionId')}</Label>
                <SearchableSelect
                  value={pinnedSessionId}
                  onChange={setPinnedSessionId}
                  disabled={!agentId || sessionsQuery.isLoading}
                  options={sessionOptions}
                  placeholder={t('managed.schedules.selectPinnedSession')}
                  searchPlaceholder={t('managed.schedules.searchPinnedSession')}
                  emptyText={sessionsQuery.isLoading ? `${t('common.loading')}…` : t('managed.schedules.noPinnedSessionMatch')}
                  clearSearchLabel={t('managed.schedules.clearSearch')}
                />
                <p className="text-xs text-muted-foreground">
                  {agentId
                    ? t('managed.schedules.pinnedSessionHint')
                    : t('managed.schedules.selectAgentFirst')}
                </p>
              </div>
            )}
          </div>

          <div className="flex items-center justify-between rounded-md border p-3">
            <div>
              <Label htmlFor="sched-enabled">{t('managed.schedules.enabled')}</Label>
              <p className="text-xs text-muted-foreground">{t('managed.schedules.enabledHint')}</p>
            </div>
            <Switch id="sched-enabled" checked={enabled} onCheckedChange={setEnabled} />
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" disabled={!canSubmit || pending}>
              {pending ? t('common.saving') : isEdit ? t('common.save') : t('common.create')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
