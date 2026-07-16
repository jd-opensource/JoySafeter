'use client'

import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'

import { CronEditor } from '@/components/managed/schedules/cron-editor'
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { managedGet } from '@/lib/api-client'
import { currentProjectAllowsWrite } from '@/hooks/managed/use-current-project-read-only'
import { useTranslation } from '@/lib/i18n'

import { detectBrowserTimezone, isValidCron } from '@/lib/managed/cron'
import { toastOperationError } from '@/lib/managed/errors'
import { stripIdPrefix } from '@/lib/managed/id'
import {
  useCreateSchedule,
  useUpdateSchedule,
  type Schedule,
  type ScheduleConcurrencyPolicy,
} from '@/lib/managed/schedules'
import { useProjectStore } from '@/stores/managed/project-store'

interface AgentOption {
  id: string
  name: string
  archived_at?: string | null
}

interface EnvironmentOption {
  id: string
  name: string
  archived_at?: string | null
}

interface CreateScheduleDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** When provided, the dialog edits an existing schedule instead of creating. */
  schedule?: Schedule | null
}

const POLICIES: ScheduleConcurrencyPolicy[] = ['allow', 'forbid', 'replace']

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
  const currentOrgId = useProjectStore((s) => s.currentOrgId)
  const currentProjectId = useProjectStore((s) => s.currentProjectId)
  const managedScope = `${currentOrgId ?? ''}:${currentProjectId ?? ''}`
  const managedScopeRef = useRef(managedScope)
  const submitRunRef = useRef(0)

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [agentId, setAgentId] = useState('')
  const [environmentRef, setEnvironmentRef] = useState('')
  const [prompt, setPrompt] = useState('')
  const [systemPrompt, setSystemPrompt] = useState('')
  const [cron, setCron] = useState('0 9 * * *')
  const [tz, setTz] = useState('UTC')
  const [policy, setPolicy] = useState<ScheduleConcurrencyPolicy>('allow')
  const [timeoutSec, setTimeoutSec] = useState(7200)
  const [maxRetries, setMaxRetries] = useState(2)
  const [enabled, setEnabled] = useState(true)

  const agentsQuery = useQuery({
    queryKey: ['agents', managedScope, 'for-schedule'],
    queryFn: () => managedGet<AgentOption[] | { data: AgentOption[] }>('/agents?limit=200'),
    enabled: open,
  })
  const agents: AgentOption[] = useMemo(() => {
    const raw = agentsQuery.data
    const list = Array.isArray(raw) ? raw : (raw?.data ?? [])
    return list.filter((a) => !a.archived_at)
  }, [agentsQuery.data])

  const environmentsQuery = useQuery({
    queryKey: ['environments', managedScope, 'for-schedule'],
    queryFn: () =>
      managedGet<EnvironmentOption[] | { data: EnvironmentOption[] }>('/environments?limit=200'),
    enabled: open,
  })
  const environments: EnvironmentOption[] = useMemo(() => {
    const raw = environmentsQuery.data
    const list = Array.isArray(raw) ? raw : (raw?.data ?? [])
    return list.filter((e) => !e.archived_at)
  }, [environmentsQuery.data])

  const getCurrentManagedScope = () => {
    const { currentOrgId: orgId, currentProjectId: projectId } = useProjectStore.getState()
    return `${orgId ?? ''}:${projectId ?? ''}`
  }

  const currentManagedScopeIsActive = (scope = managedScopeRef.current) =>
    scope === managedScopeRef.current && scope === getCurrentManagedScope()

  const isCurrentSubmitRun = (runId: number, scope: string) =>
    runId === submitRunRef.current && currentManagedScopeIsActive(scope) && currentProjectAllowsWrite()

  useEffect(() => {
    if (managedScopeRef.current === managedScope) return
    managedScopeRef.current = managedScope
    submitRunRef.current += 1
    onOpenChange(false)
  }, [managedScope, onOpenChange])

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
      setAgentId(stripIdPrefix(schedule.agent_id))
      setEnvironmentRef(schedule.environment_ref ?? '')
      setPrompt(schedule.prompt)
      setSystemPrompt(schedule.system_prompt ?? '')
      setCron(schedule.cron_expr)
      setTz(schedule.timezone)
      setPolicy(schedule.concurrency_policy)
      setTimeoutSec(schedule.timeout_sec)
      setMaxRetries(schedule.max_retries)
      setEnabled(schedule.enabled)
    } else {
      setName('')
      setDescription('')
      setAgentId('')
      setEnvironmentRef('')
      setPrompt('')
      setSystemPrompt('')
      setCron('0 9 * * *')
      setTz(detectBrowserTimezone())
      setPolicy('allow')
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
    const scopeAtStart = managedScopeRef.current
    if (!currentManagedScopeIsActive(scopeAtStart)) return
    const runId = submitRunRef.current + 1
    submitRunRef.current = runId
    try {
      if (isEdit && schedule) {
        await updateMut.mutateAsync({
          id: stripIdPrefix(schedule.id),
          body: {
            name: name.trim(),
            description: description.trim() || null,
            prompt: prompt.trim(),
            system_prompt: systemPrompt.trim() || null,
            environment_ref: environmentRef || null,
            cron_expr: cron,
            timezone: tz,
            concurrency_policy: policy,
            timeout_sec: timeoutSec,
            max_retries: maxRetries,
            enabled,
          },
        })
      } else {
        await createMut.mutateAsync({
          name: name.trim(),
          description: description.trim() || null,
          agent_id: agentId,
          environment_ref: environmentRef || null,
          prompt: prompt.trim(),
          system_prompt: systemPrompt.trim() || null,
          cron_expr: cron,
          timezone: tz,
          concurrency_policy: policy,
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
              <Select value={agentId} onValueChange={setAgentId} disabled={isEdit}>
                <SelectTrigger>
                  <SelectValue placeholder={t('managed.schedules.selectAgent')} />
                </SelectTrigger>
                <SelectContent>
                  {agents.map((a) => (
                    <SelectItem key={a.id} value={stripIdPrefix(a.id)}>
                      {a.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
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
            <Label htmlFor="sched-system-prompt">{t('managed.schedules.systemPrompt')}</Label>
            <Textarea
              id="sched-system-prompt"
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              rows={2}
            />
          </div>

          <div className="space-y-1.5">
            <Label>{t('managed.schedules.environment')}</Label>
            <Select
              value={environmentRef || FOLLOW_AGENT_ENV}
              onValueChange={(v) => setEnvironmentRef(v === FOLLOW_AGENT_ENV ? '' : v)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={FOLLOW_AGENT_ENV}>
                  {t('managed.schedules.envFollowAgent')}
                </SelectItem>
                {environments.map((env) => (
                  <SelectItem key={env.id} value={env.id}>
                    {env.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">{t('managed.schedules.environmentHint')}</p>
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
              <Select value={policy} onValueChange={(v) => setPolicy(v as ScheduleConcurrencyPolicy)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {POLICIES.map((p) => (
                    <SelectItem key={p} value={p}>
                      {t(`managed.schedules.policy.${p}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
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
