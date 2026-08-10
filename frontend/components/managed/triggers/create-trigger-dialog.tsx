'use client'

import { useQuery } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'

import { ServiceCredentialSelect } from '@/components/managed/shared'
import { CronEditor } from '@/components/managed/triggers/cron-editor'
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
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { currentProjectAllowsWrite } from '@/hooks/managed/use-current-project-read-only'
import { useScopedActions } from '@/hooks/managed/use-scoped-actions'
import { useServiceCredentials } from '@/hooks/managed/use-service-credentials'
import { managedGet } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { apiResourceId } from '@/lib/managed/api-paths'
import { detectBrowserTimezone, isValidCron } from '@/lib/managed/cron'
import { toastOperationError } from '@/lib/managed/errors'
import { hasManagedRequestScope, managedRequestOptions } from '@/lib/managed/request-scope'
import {
  useCreateAgentTrigger,
  useUpdateAgentTrigger,
  type AgentTrigger,
  type TriggerConcurrencyPolicy,
  type TriggerSessionMode,
  type TriggerType,
  type WebhookAuthMethod,
} from '@/lib/managed/triggers'
import {
  parseAgentId,
  parseEnvironmentId,
  parseSessionId,
  type AgentId,
  type EnvironmentId,
  type SessionId,
} from '@/types/entity-id'

interface AgentOption {
  id: AgentId
  name: string
  engine_kind?: string | null
  model?: { id?: string } | null
  archived_at?: string | null
}

function parseAgentOption(value: unknown): AgentOption {
  const raw = value as Omit<AgentOption, 'id'> & { id: string }
  return { ...raw, id: parseAgentId(raw.id) }
}

interface EnvironmentOption {
  id: EnvironmentId
  name: string
  config?: { type?: string; networking?: { type?: string } } | null
  archived_at?: string | null
}

function parseEnvironmentOption(value: unknown): EnvironmentOption {
  const raw = value as Omit<EnvironmentOption, 'id'> & { id: string }
  return { ...raw, id: parseEnvironmentId(raw.id) }
}

interface SessionOption {
  id: SessionId
  title?: string | null
  status?: string | null
  archived_at?: string | null
}

function parseSessionOption(value: unknown): SessionOption {
  const raw = value as Omit<SessionOption, 'id'> & { id: string }
  return { ...raw, id: parseSessionId(raw.id) }
}

type TriggerKind = TriggerType

interface CreateTriggerDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** When provided, the dialog edits an existing trigger instead of creating. */
  trigger?: AgentTrigger | null
}

const POLICIES: TriggerConcurrencyPolicy[] = ['allow', 'forbid', 'replace']
const SESSION_MODES: TriggerSessionMode[] = ['fresh', 'reuse', 'pinned', 'keyed']
const AUTH_METHODS: WebhookAuthMethod[] = ['hmac', 'bearer', 'token']
const DEFAULT_DEDUPE_HEADER = 'x-joysafeter-delivery'
const DEFAULT_SECRET_KEY = 'WEBHOOK_SECRET'
const NOW_REFRESH_MS = 1000
const PROMPT_VARIABLE_EXAMPLES: Record<TriggerKind, string[]> = {
  cron: ['{{ cron.fired_at }}', '{{ cron.cron_expr }}', '{{ trigger.name }}'],
  webhook: [
    '{{ body }}',
    '{{ body.alert.name }}',
    '{{ headers.user_agent }}',
    '{{ trigger.name }}',
  ],
  manual: ['{{ trigger.fired_at }}', '{{ trigger.source_type }}', '{{ trigger.name }}'],
}
let nowSnapshot = Math.floor(Date.now() / NOW_REFRESH_MS) * NOW_REFRESH_MS

function currentNowSnapshot(): number {
  const next = Math.floor(Date.now() / NOW_REFRESH_MS) * NOW_REFRESH_MS
  if (next > nowSnapshot) nowSnapshot = next
  return nowSnapshot
}

function subscribeNowSnapshot(onStoreChange: () => void): () => void {
  const interval = window.setInterval(() => {
    currentNowSnapshot()
    onStoreChange()
  }, NOW_REFRESH_MS)
  return () => window.clearInterval(interval)
}

function subscribeNoop(): () => void {
  return () => undefined
}

function inactiveNowSnapshot(): number {
  return nowSnapshot
}

function isWebhookAuthMethod(value: unknown): value is WebhookAuthMethod {
  return typeof value === 'string' && AUTH_METHODS.includes(value as WebhookAuthMethod)
}

function usableCredentialFields(fields: readonly string[] | undefined): string[] {
  return (fields ?? []).filter((field) => field.trim().length > 0)
}

// Sentinel Select value for "no explicit environment" — radix Select cannot use
// an empty-string item value, so we map this to `environment_ref = null`.
const FOLLOW_AGENT_ENV = '__agent_default__'

interface FilterRow {
  path: string
  value: string
}

interface TriggerFormState {
  type: TriggerKind
  name: string
  description: string
  agentId: AgentId | ''
  environmentRef: string
  prompt: string
  agentSearch: string
  envSearch: string
  timeoutSec: number
  maxRetries: number
  enabled: boolean
  sessionMode: TriggerSessionMode
  pinnedSessionId: SessionId | ''
  sessionKey: string
  scheduleMode: 'repeats' | 'once'
  cron: string
  tz: string
  runAt: string
  policy: TriggerConcurrencyPolicy
  secretRef: string
  secretKey: string
  authMethods: WebhookAuthMethod[]
  dedupeHeader: string
  filterRows: FilterRow[]
}

function filterToRows(filter: Record<string, unknown> | null | undefined): FilterRow[] {
  return Object.entries(filter ?? {}).map(([path, value]) => ({ path, value: String(value) }))
}

/** Drop blank paths and collapse to the wire shape. */
function rowsToFilter(rows: FilterRow[]): Record<string, string> {
  const out: Record<string, string> = {}
  for (const { path, value } of rows) {
    if (path.trim()) out[path.trim()] = value
  }
  return out
}

/** Convert a wire ISO timestamp to a `datetime-local` input value (local tz). */
function isoToLocalInput(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function useNowMs(active: boolean): number {
  return useSyncExternalStore(
    active ? subscribeNowSnapshot : subscribeNoop,
    active ? currentNowSnapshot : inactiveNowSnapshot,
    inactiveNowSnapshot,
  )
}

function triggerToFormState(trigger?: AgentTrigger | null): TriggerFormState {
  if (!trigger) {
    return {
      type: 'cron',
      name: '',
      description: '',
      agentId: '',
      environmentRef: '',
      prompt: '',
      agentSearch: '',
      envSearch: '',
      timeoutSec: 7200,
      maxRetries: 2,
      enabled: true,
      sessionMode: 'fresh',
      pinnedSessionId: '',
      sessionKey: '',
      scheduleMode: 'repeats',
      cron: '0 9 * * *',
      tz: detectBrowserTimezone(),
      runAt: '',
      policy: 'allow',
      secretRef: '',
      secretKey: DEFAULT_SECRET_KEY,
      authMethods: [...AUTH_METHODS],
      dedupeHeader: DEFAULT_DEDUPE_HEADER,
      filterRows: [],
    }
  }

  const cfgAuth = trigger.config?.auth_methods
  return {
    type: trigger.type,
    name: trigger.name,
    description: trigger.description ?? '',
    agentId: trigger.agent_id,
    environmentRef: trigger.environment_ref ?? '',
    prompt: trigger.prompt_template,
    agentSearch: '',
    envSearch: '',
    timeoutSec: trigger.timeout_sec,
    maxRetries: trigger.max_retries,
    enabled: trigger.enabled,
    sessionMode: trigger.session_mode || 'fresh',
    pinnedSessionId: trigger.pinned_session_id ?? '',
    sessionKey: trigger.session_key ?? '',
    scheduleMode: trigger.run_at ? 'once' : 'repeats',
    cron: trigger.cron_expr || '0 9 * * *',
    tz: trigger.timezone || 'UTC',
    runAt: isoToLocalInput(trigger.run_at),
    policy: (trigger.concurrency_policy ?? 'allow') as TriggerConcurrencyPolicy,
    secretRef: trigger.secret_ref ?? '',
    secretKey: trigger.secret_key ?? DEFAULT_SECRET_KEY,
    authMethods: Array.isArray(cfgAuth) ? cfgAuth.filter(isWebhookAuthMethod) : [...AUTH_METHODS],
    dedupeHeader: (trigger.config?.dedupe_header as string) ?? DEFAULT_DEDUPE_HEADER,
    filterRows: filterToRows(trigger.filter),
  }
}

function formInstanceKey(open: boolean, trigger?: AgentTrigger | null): string {
  if (!open) return 'closed'
  return trigger?.id ?? 'create'
}

export function CreateTriggerDialog(props: CreateTriggerDialogProps) {
  return <CreateTriggerDialogForm key={formInstanceKey(props.open, props.trigger)} {...props} />
}

function CreateTriggerDialogForm({ open, onOpenChange, trigger }: CreateTriggerDialogProps) {
  const { t } = useTranslation()
  const isEdit = !!trigger
  const createMut = useCreateAgentTrigger()
  const updateMut = useUpdateAgentTrigger()
  const locale = (t('_locale') === 'zh' ? 'zh' : 'en') as 'en' | 'zh'
  const { scope, beginAction, isCurrentAction, scopeIsActive, bumpRun } = useScopedActions({
    onReset: () => onOpenChange(false),
  })
  const submitRunRef = useRef(0)
  const [initialForm] = useState(() => triggerToFormState(trigger))

  const [type, setType] = useState<TriggerKind>(initialForm.type)
  const [name, setName] = useState(initialForm.name)
  const [description, setDescription] = useState(initialForm.description)
  const [agentId, setAgentId] = useState(initialForm.agentId)
  const [environmentRef, setEnvironmentRef] = useState(initialForm.environmentRef)
  const [prompt, setPrompt] = useState(initialForm.prompt)
  const [agentSearch, setAgentSearch] = useState(initialForm.agentSearch)
  const [envSearch, setEnvSearch] = useState(initialForm.envSearch)
  const [timeoutSec, setTimeoutSec] = useState(initialForm.timeoutSec)
  const [maxRetries, setMaxRetries] = useState(initialForm.maxRetries)
  const [enabled, setEnabled] = useState(initialForm.enabled)

  const [sessionMode, setSessionMode] = useState<TriggerSessionMode>(initialForm.sessionMode)
  const [pinnedSessionId, setPinnedSessionId] = useState(initialForm.pinnedSessionId)
  const [sessionKey, setSessionKey] = useState(initialForm.sessionKey)

  // Cron / run-once
  const [scheduleMode, setScheduleMode] = useState<'repeats' | 'once'>(initialForm.scheduleMode)
  const [cron, setCron] = useState(initialForm.cron)
  const [tz, setTz] = useState(initialForm.tz)
  const [runAt, setRunAt] = useState(initialForm.runAt)
  const [policy, setPolicy] = useState<TriggerConcurrencyPolicy>(initialForm.policy)

  // Webhook
  const [secretRef, setSecretRef] = useState(initialForm.secretRef)
  const [secretKey, setSecretKey] = useState(initialForm.secretKey)
  const [authMethods, setAuthMethods] = useState<WebhookAuthMethod[]>(initialForm.authMethods)
  const [dedupeHeader, setDedupeHeader] = useState(initialForm.dedupeHeader)
  const [filterRows, setFilterRows] = useState<FilterRow[]>(initialForm.filterRows)

  const serviceCredentialsQuery = useServiceCredentials({ enabled: open && type === 'webhook' })
  const serviceCredentials = useMemo(
    () => serviceCredentialsQuery.data ?? [],
    [serviceCredentialsQuery.data],
  )
  const selectedCredential = useMemo(
    () => serviceCredentials.find((credential) => credential.name === secretRef),
    [secretRef, serviceCredentials],
  )
  const credentialFields = useMemo(
    () => usableCredentialFields(selectedCredential?.keys),
    [selectedCredential],
  )
  const missingCredential = useMemo(
    () =>
      !serviceCredentialsQuery.isLoading &&
      !serviceCredentialsQuery.isError &&
      Boolean(secretRef) &&
      !selectedCredential,
    [
      secretRef,
      selectedCredential,
      serviceCredentialsQuery.isError,
      serviceCredentialsQuery.isLoading,
    ],
  )
  const missingCredentialField = useMemo(
    () =>
      !serviceCredentialsQuery.isLoading &&
      !serviceCredentialsQuery.isError &&
      Boolean(selectedCredential) &&
      Boolean(secretKey) &&
      !credentialFields.includes(secretKey),
    [
      credentialFields,
      secretKey,
      selectedCredential,
      serviceCredentialsQuery.isError,
      serviceCredentialsQuery.isLoading,
    ],
  )

  const agentsQuery = useQuery({
    queryKey: ['agents', scope.key, 'for-trigger'],
    queryFn: () =>
      managedGet<unknown[] | { data: unknown[] }>(
        '/agents?limit=100',
        managedRequestOptions(scope),
      ).then((response) =>
        Array.isArray(response)
          ? response.map(parseAgentOption)
          : { ...response, data: response.data.map(parseAgentOption) },
      ),
    enabled: open && hasManagedRequestScope(scope),
  })
  const agents: AgentOption[] = useMemo(() => {
    const raw = agentsQuery.data
    const list = Array.isArray(raw) ? raw : (raw?.data ?? [])
    return list.filter((a) => !a.archived_at)
  }, [agentsQuery.data])
  const filteredAgents = useMemo(() => {
    if (!agentSearch.trim()) return agents
    const q = agentSearch.toLowerCase()
    return agents.filter(
      (a) =>
        a.name.toLowerCase().includes(q) ||
        a.engine_kind?.toLowerCase().includes(q) ||
        a.model?.id?.toLowerCase().includes(q),
    )
  }, [agents, agentSearch])

  const environmentsQuery = useQuery({
    queryKey: ['environments', scope.key, 'for-trigger'],
    queryFn: () =>
      managedGet<unknown[] | { data: unknown[] }>(
        '/environments?limit=100',
        managedRequestOptions(scope),
      ).then((response) =>
        Array.isArray(response)
          ? response.map(parseEnvironmentOption)
          : { ...response, data: response.data.map(parseEnvironmentOption) },
      ),
    enabled: open && hasManagedRequestScope(scope),
  })
  const environments: EnvironmentOption[] = useMemo(() => {
    const raw = environmentsQuery.data
    const list = Array.isArray(raw) ? raw : (raw?.data ?? [])
    return list.filter((e) => !e.archived_at)
  }, [environmentsQuery.data])
  const filteredEnvironments = useMemo(() => {
    if (!envSearch.trim()) return environments
    const q = envSearch.toLowerCase()
    return environments.filter((e) => e.name.toLowerCase().includes(q))
  }, [environments, envSearch])

  const sessionsQuery = useQuery({
    queryKey: ['agent-sessions', scope.key, agentId, 'for-trigger'],
    queryFn: () =>
      managedGet<{ data: unknown[] } | unknown[]>(
        `/agents/${agentId}/sessions?limit=100`,
        managedRequestOptions(scope),
      ).then((response) =>
        Array.isArray(response)
          ? response.map(parseSessionOption)
          : { ...response, data: response.data.map(parseSessionOption) },
      ),
    enabled: open && !!agentId && hasManagedRequestScope(scope),
  })
  const sessions: SessionOption[] = useMemo(() => {
    const raw = sessionsQuery.data
    const list = Array.isArray(raw) ? raw : (raw?.data ?? [])
    return list.filter((s) => !s.archived_at)
  }, [sessionsQuery.data])

  useEffect(
    () => () => {
      submitRunRef.current += 1
    },
    [],
  )

  const nowMs = useNowMs(open && type === 'cron' && scheduleMode === 'once')
  const runAtIsFuture = useMemo(() => {
    if (!runAt) return false
    const d = new Date(runAt)
    return !Number.isNaN(d.getTime()) && d.getTime() > nowMs
  }, [nowMs, runAt])

  const isUnchangedCompletedOneOff = useMemo(
    () =>
      isEdit &&
      trigger?.type === 'cron' &&
      scheduleMode === 'once' &&
      !!trigger.run_at &&
      !!trigger.last_fired_slot &&
      !trigger.next_run_at &&
      runAt === isoToLocalInput(trigger.run_at),
    [isEdit, runAt, scheduleMode, trigger],
  )

  const filterRowsValid = filterRows.every(
    (row) => Boolean(row.path.trim()) === Boolean(row.value.trim()),
  )

  const webhookCredentialValid =
    !serviceCredentialsQuery.isLoading &&
    !serviceCredentialsQuery.isError &&
    Boolean(selectedCredential) &&
    Boolean(secretKey) &&
    credentialFields.includes(secretKey)

  const canSubmit =
    name.trim().length > 0 &&
    !!agentId &&
    prompt.trim().length > 0 &&
    (sessionMode !== 'pinned' || !!pinnedSessionId) &&
    (sessionMode !== 'keyed' || !!sessionKey.trim()) &&
    Number.isFinite(timeoutSec) &&
    timeoutSec >= 1 &&
    Number.isFinite(maxRetries) &&
    maxRetries >= 0 &&
    (type === 'cron'
      ? scheduleMode === 'once'
        ? runAtIsFuture || isUnchangedCompletedOneOff
        : isValidCron(cron)
      : type === 'webhook'
        ? webhookCredentialValid && authMethods.length > 0 && filterRowsValid
        : true)

  const pending = createMut.isPending || updateMut.isPending

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit || pending) return
    const action = beginAction()
    if (!action) {
      onOpenChange(false)
      return
    }
    const { scope: scopeAtStart } = action
    const runId = submitRunRef.current + 1
    submitRunRef.current = runId

    const sharedBody = {
      name: name.trim(),
      description: description.trim() || null,
      prompt_template: prompt.trim(),
      environment_ref: environmentRef || null,
      session_mode: sessionMode,
      pinned_session_id: sessionMode === 'pinned' ? parseSessionId(pinnedSessionId) : null,
      session_key: sessionMode === 'keyed' ? sessionKey.trim() : null,
      timeout_sec: timeoutSec,
      max_retries: maxRetries,
      enabled,
    }

    const typeBody =
      type === 'cron'
        ? scheduleMode === 'once'
          ? isUnchangedCompletedOneOff
            ? {}
            : {
                cron_expr: null,
                run_at: new Date(runAt).toISOString(),
                timezone: tz,
                concurrency_policy: policy,
              }
          : {
              cron_expr: cron,
              run_at: null,
              timezone: tz,
              concurrency_policy: policy,
            }
        : type === 'webhook'
          ? {
              secret_ref: secretRef,
              secret_key: secretKey,
              auth_methods: authMethods,
              dedupe_header: dedupeHeader.trim() || DEFAULT_DEDUPE_HEADER,
              filter: rowsToFilter(filterRows),
            }
          : {}

    try {
      if (isEdit && trigger) {
        await updateMut.mutateAsync({
          id: trigger.id,
          body: { ...sharedBody, ...typeBody },
        })
      } else {
        await createMut.mutateAsync({
          type,
          agent_id: parseAgentId(agentId),
          ...sharedBody,
          ...typeBody,
        })
      }
      if (!isCurrentAction(runId, scopeAtStart)) return
      onOpenChange(false)
    } catch (err) {
      if (!isCurrentAction(runId, scopeAtStart)) return
      toastOperationError(t, err, 'managed.triggers.saveFailed')
    }
  }

  const handleOpenChange = (nextOpen: boolean) => {
    if (nextOpen && !currentProjectAllowsWrite()) return
    if (nextOpen && !scopeIsActive()) return
    if (!nextOpen) bumpRun()
    onOpenChange(nextOpen)
  }

  const toggleAuthMethod = (method: WebhookAuthMethod) => {
    setAuthMethods((prev) =>
      prev.includes(method) ? prev.filter((m) => m !== method) : [...prev, method],
    )
  }

  const handleServiceCredentialChange = (value: string) => {
    const credential = serviceCredentials.find((item) => item.name === value)
    const fields = usableCredentialFields(credential?.keys)
    setSecretRef(value)
    setSecretKey(fields.includes(DEFAULT_SECRET_KEY) ? DEFAULT_SECRET_KEY : (fields[0] ?? ''))
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {isEdit ? t('managed.triggers.editTitle') : t('managed.triggers.createTitle')}
          </DialogTitle>
          <DialogDescription>{t('managed.triggers.createDescription')}</DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Type segmented control (locked on edit so type-specific runtime state is not rewritten). */}
          <div className="space-y-1.5">
            <Label>{t('managed.triggers.type')}</Label>
            <Tabs value={type} onValueChange={(v) => !isEdit && setType(v as TriggerKind)}>
              <TabsList className="grid w-full grid-cols-3">
                <TabsTrigger value="cron" disabled={isEdit && type !== 'cron'}>
                  {t('managed.triggers.typeOption.cron')}
                </TabsTrigger>
                <TabsTrigger value="webhook" disabled={isEdit && type !== 'webhook'}>
                  {t('managed.triggers.typeOption.webhook')}
                </TabsTrigger>
                <TabsTrigger value="manual" disabled={isEdit && type !== 'manual'}>
                  {t('managed.triggers.typeOption.manual')}
                </TabsTrigger>
              </TabsList>
            </Tabs>
            <p className="text-xs text-muted-foreground">
              {type === 'cron'
                ? t('managed.triggers.typeHintCron')
                : type === 'webhook'
                  ? t('managed.triggers.typeHintWebhook')
                  : t('managed.triggers.typeHintManual')}
            </p>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="trig-name">{t('managed.triggers.name')}</Label>
              <Input
                id="trig-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={t('managed.triggers.namePlaceholder')}
              />
            </div>
            <div className="space-y-1.5">
              <Label>{t('managed.triggers.agent')}</Label>
              <Select
                value={agentId}
                onValueChange={(value) => {
                  setAgentId(parseAgentId(value))
                  setPinnedSessionId('')
                }}
                disabled={isEdit}
              >
                <SelectTrigger>
                  <SelectValue placeholder={t('managed.triggers.selectAgent')} />
                </SelectTrigger>
                <SelectContent
                  className="max-h-[280px]"
                  align="start"
                  side="bottom"
                  sideOffset={4}
                  style={{ width: 'var(--radix-select-trigger-width)' }}
                >
                  <div className="sticky top-0 z-10 bg-popover px-2 pb-2 pt-1.5">
                    <input
                      className="w-full rounded-md bg-muted/60 px-2.5 py-1.5 text-sm outline-none placeholder:text-muted-foreground"
                      placeholder={t('common.search', '搜索') + '…'}
                      value={agentSearch}
                      onChange={(e) => setAgentSearch(e.target.value)}
                      onKeyDown={(e) => e.stopPropagation()}
                    />
                  </div>
                  {agentsQuery.isLoading && (
                    <div className="px-2 py-4 text-center text-xs text-muted-foreground">
                      {t('common.loading')}…
                    </div>
                  )}
                  {!agentsQuery.isLoading && filteredAgents.length === 0 && (
                    <div className="px-2 py-4 text-center text-xs text-muted-foreground">
                      {agentSearch
                        ? t('common.noResults', '无匹配结果')
                        : t('managed.triggers.noAgents')}
                    </div>
                  )}
                  {filteredAgents.map((a) => (
                    <SelectItem key={a.id} value={apiResourceId(a.id)}>
                      <div className="flex items-center gap-2">
                        <span className="truncate">{a.name}</span>
                        {a.engine_kind && (
                          <span className="shrink-0 rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                            {a.engine_kind}
                          </span>
                        )}
                        {a.model?.id && (
                          <span className="shrink-0 truncate text-[10px] text-muted-foreground">
                            {a.model.id}
                          </span>
                        )}
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="trig-description">{t('managed.triggers.description')}</Label>
            <Textarea
              id="trig-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              placeholder={t('managed.triggers.descriptionPlaceholder')}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="trig-prompt">{t('managed.triggers.promptTemplate')}</Label>
            <Textarea
              id="trig-prompt"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={3}
              placeholder={t('managed.triggers.promptPlaceholder')}
            />
            <p className="text-xs text-muted-foreground">
              {t('managed.triggers.promptVarsHint')}{' '}
              <span className="inline-flex flex-wrap gap-1 align-middle">
                {PROMPT_VARIABLE_EXAMPLES[type].map((example) => (
                  <code key={example}>{example}</code>
                ))}
              </span>
            </p>
          </div>

          <div className="space-y-1.5">
            <Label>{t('managed.triggers.runtimeEnvironment')}</Label>
            <Select
              value={environmentRef || FOLLOW_AGENT_ENV}
              onValueChange={(v) => setEnvironmentRef(v === FOLLOW_AGENT_ENV ? '' : v)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="max-h-[280px]">
                <div className="sticky top-0 z-10 bg-popover px-2 pb-2 pt-1.5">
                  <input
                    className="w-full rounded-md bg-muted/60 px-2.5 py-1.5 text-sm outline-none placeholder:text-muted-foreground"
                    placeholder={t('common.search', '搜索') + '…'}
                    value={envSearch}
                    onChange={(e) => setEnvSearch(e.target.value)}
                    onKeyDown={(e) => e.stopPropagation()}
                  />
                </div>
                <SelectItem value={FOLLOW_AGENT_ENV}>
                  {t('managed.triggers.envFollowAgent')}
                </SelectItem>
                {environmentsQuery.isLoading && (
                  <div className="px-2 py-3 text-center text-xs text-muted-foreground">
                    {t('common.loading')}…
                  </div>
                )}
                {filteredEnvironments.map((env) => {
                  const netType = env.config?.networking?.type || env.config?.type
                  return (
                    <SelectItem key={env.id} value={env.id}>
                      <div className="flex items-center gap-2">
                        <span className="truncate">{env.name}</span>
                        {netType && (
                          <span className="shrink-0 rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                            {netType}
                          </span>
                        )}
                      </div>
                    </SelectItem>
                  )
                })}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">{t('managed.triggers.environmentHint')}</p>
          </div>

          {/* Cron tab */}
          {type === 'cron' && (
            <div className="space-y-3 rounded-md border p-3">
              <div className="space-y-1.5">
                <Label>{t('managed.triggers.scheduleMode')}</Label>
                <Tabs
                  value={scheduleMode}
                  onValueChange={(v) => setScheduleMode(v as 'repeats' | 'once')}
                >
                  <TabsList className="grid w-full grid-cols-2">
                    <TabsTrigger value="repeats">{t('managed.triggers.repeats')}</TabsTrigger>
                    <TabsTrigger value="once">{t('managed.triggers.runOnce')}</TabsTrigger>
                  </TabsList>
                </Tabs>
              </div>

              {scheduleMode === 'repeats' ? (
                <>
                  <CronEditor
                    value={cron}
                    timezone={tz}
                    onChange={setCron}
                    onTimezoneChange={setTz}
                    locale={locale}
                  />
                  <div className="space-y-1.5">
                    <Label>{t('managed.triggers.concurrency')}</Label>
                    <Select
                      value={policy}
                      onValueChange={(v) => setPolicy(v as TriggerConcurrencyPolicy)}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {POLICIES.map((p) => (
                          <SelectItem key={p} value={p}>
                            {t(`managed.triggers.policy.${p}`)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <p className="text-xs text-muted-foreground">
                      {t('managed.triggers.concurrencyHint')}
                    </p>
                  </div>
                </>
              ) : (
                <div className="space-y-1.5">
                  <Label htmlFor="trig-runat">{t('managed.triggers.runOnceAt')}</Label>
                  <Input
                    id="trig-runat"
                    type="datetime-local"
                    value={runAt}
                    onChange={(e) => setRunAt(e.target.value)}
                    aria-invalid={!!runAt && !runAtIsFuture}
                  />
                  <p className="text-xs text-muted-foreground">
                    {!!runAt && !runAtIsFuture
                      ? t('managed.triggers.runOnceFuture')
                      : t('managed.triggers.runOnceHint')}
                  </p>
                </div>
              )}
            </div>
          )}

          {/* Webhook tab */}
          {type === 'webhook' && (
            <div className="space-y-3 rounded-md border p-3">
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label>{t('managed.triggers.serviceCredential')}</Label>
                  <ServiceCredentialSelect
                    value={secretRef}
                    onChange={handleServiceCredentialChange}
                    credentials={serviceCredentials}
                    loading={serviceCredentialsQuery.isLoading}
                    ariaLabel={t('managed.triggers.serviceCredential')}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label>{t('managed.triggers.credentialField')}</Label>
                  <Select
                    value={secretKey}
                    onValueChange={setSecretKey}
                    disabled={!selectedCredential || credentialFields.length === 0}
                  >
                    <SelectTrigger aria-label={t('managed.triggers.credentialField')}>
                      <SelectValue
                        placeholder={t('managed.triggers.credentialFieldPlaceholder')}
                      />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectGroup>
                        {credentialFields.map((field) => (
                          <SelectItem key={field} value={field}>
                            {field}
                          </SelectItem>
                        ))}
                      </SelectGroup>
                    </SelectContent>
                  </Select>
                </div>
              </div>

              {serviceCredentialsQuery.isError ? (
                <p className="text-xs text-destructive">
                  {t('managed.triggers.serviceCredentialLoadFailed')}
                </p>
              ) : missingCredential ? (
                <p className="text-xs text-destructive">
                  {t('managed.triggers.serviceCredentialUnavailable')}
                </p>
              ) : selectedCredential && credentialFields.length === 0 ? (
                <p className="text-xs text-destructive">
                  {t('managed.triggers.credentialFieldEmpty')}
                </p>
              ) : missingCredentialField ? (
                <p className="text-xs text-destructive">
                  {t('managed.triggers.credentialFieldUnavailable')}
                </p>
              ) : null}

              <div className="space-y-1.5">
                <Label>{t('managed.triggers.authMethods')}</Label>
                <div className="flex flex-wrap gap-1.5">
                  {AUTH_METHODS.map((method) => {
                    const active = authMethods.includes(method)
                    return (
                      <button
                        key={method}
                        type="button"
                        onClick={() => toggleAuthMethod(method)}
                        className={`rounded-md border px-2.5 py-1 text-xs transition-colors ${
                          active
                            ? 'border-primary bg-primary/10 text-foreground'
                            : 'border-border hover:bg-muted/50'
                        }`}
                      >
                        {t(`managed.triggers.authMethodOption.${method}`)}
                      </button>
                    )
                  })}
                </div>
                <p className="text-xs text-muted-foreground">
                  {t('managed.triggers.authMethodsHint')}
                </p>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="trig-dedupe">{t('managed.triggers.dedupeHeader')}</Label>
                <Input
                  id="trig-dedupe"
                  value={dedupeHeader}
                  onChange={(e) => setDedupeHeader(e.target.value)}
                  className="font-mono"
                  placeholder={DEFAULT_DEDUPE_HEADER}
                />
                <p className="text-xs text-muted-foreground">
                  {t('managed.triggers.dedupeHeaderHint')}
                </p>
              </div>

              <div className="space-y-1.5">
                <Label>{t('managed.triggers.deliveryFilter')}</Label>
                <div className="space-y-2 rounded-md border bg-card px-3 py-2">
                  {filterRows.length === 0 ? (
                    <p className="text-xs text-muted-foreground">
                      {t('managed.triggers.deliveryFilterEmpty')}
                    </p>
                  ) : (
                    filterRows.map((row, index) => (
                      <div key={index} className="flex items-center gap-2">
                        <Input
                          value={row.path}
                          onChange={(e) =>
                            setFilterRows((rows) =>
                              rows.map((r, i) =>
                                i === index ? { ...r, path: e.target.value } : r,
                              ),
                            )
                          }
                          placeholder={t('managed.triggers.deliveryFilterPathPlaceholder')}
                          className="font-mono text-xs"
                        />
                        <span className="shrink-0 text-xs text-muted-foreground">=</span>
                        <Input
                          value={row.value}
                          onChange={(e) =>
                            setFilterRows((rows) =>
                              rows.map((r, i) =>
                                i === index ? { ...r, value: e.target.value } : r,
                              ),
                            )
                          }
                          placeholder={t('managed.triggers.deliveryFilterValuePlaceholder')}
                          className="font-mono text-xs"
                        />
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          aria-label={t('managed.triggers.deliveryFilterRemove')}
                          onClick={() =>
                            setFilterRows((rows) => rows.filter((_, i) => i !== index))
                          }
                        >
                          <Trash2 className="size-4 shrink-0" />
                        </Button>
                      </div>
                    ))
                  )}
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="gap-1.5"
                    onClick={() => setFilterRows((rows) => [...rows, { path: '', value: '' }])}
                  >
                    <Plus className="size-3.5 shrink-0" />
                    {t('managed.triggers.deliveryFilterAdd')}
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">
                  {t('managed.triggers.deliveryFilterHint')}
                </p>
                {!filterRowsValid && (
                  <p className="text-xs text-destructive">
                    {t('managed.triggers.deliveryFilterInvalid')}
                  </p>
                )}
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="trig-timeout">{t('managed.triggers.timeoutSec')}</Label>
              <Input
                id="trig-timeout"
                type="number"
                min={1}
                value={timeoutSec}
                onChange={(e) => setTimeoutSec(Number(e.target.value) || 0)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="trig-retries">{t('managed.triggers.maxRetries')}</Label>
              <Input
                id="trig-retries"
                type="number"
                min={0}
                value={maxRetries}
                onChange={(e) => setMaxRetries(Number(e.target.value) || 0)}
              />
            </div>
          </div>

          <div className="space-y-3 rounded-md border p-3">
            <div className="space-y-1.5">
              <Label>{t('managed.triggers.sessionMode')}</Label>
              <Select
                value={sessionMode}
                onValueChange={(value) => {
                  const mode = value as TriggerSessionMode
                  setSessionMode(mode)
                  if (mode !== 'pinned') setPinnedSessionId('')
                  if (mode !== 'keyed') setSessionKey('')
                }}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SESSION_MODES.map((mode) => (
                    <SelectItem key={mode} value={mode}>
                      {t(`managed.triggers.sessionModeOption.${mode}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                {t(`managed.triggers.sessionModeHint.${sessionMode}`)}
              </p>
            </div>

            {sessionMode === 'pinned' && (
              <div className="space-y-1.5">
                <Label>{t('managed.triggers.pinnedSessionId')}</Label>
                <Select
                  value={pinnedSessionId}
                  onValueChange={(value) => setPinnedSessionId(parseSessionId(value))}
                  disabled={!agentId || sessionsQuery.isLoading}
                >
                  <SelectTrigger>
                    <SelectValue placeholder={t('managed.triggers.selectPinnedSession')} />
                  </SelectTrigger>
                  <SelectContent>
                    {sessions.map((session) => (
                      <SelectItem key={session.id} value={session.id}>
                        {session.title?.trim() || session.id}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  {agentId
                    ? t('managed.triggers.pinnedSessionHint')
                    : t('managed.triggers.selectAgentFirst')}
                </p>
              </div>
            )}

            {sessionMode === 'keyed' && (
              <div className="space-y-1.5">
                <Label htmlFor="trig-session-key">{t('managed.triggers.sessionKey')}</Label>
                <Input
                  id="trig-session-key"
                  value={sessionKey}
                  onChange={(e) => setSessionKey(e.target.value)}
                  className="font-mono"
                  placeholder={t('managed.triggers.sessionKeyPlaceholder')}
                />
                <p className="text-xs text-muted-foreground">
                  {t('managed.triggers.sessionKeyHint')}
                </p>
              </div>
            )}
          </div>

          <div className="flex items-center justify-between rounded-md border p-3">
            <div>
              <Label htmlFor="trig-enabled">{t('managed.triggers.enabled')}</Label>
              <p className="text-xs text-muted-foreground">{t('managed.triggers.enabledHint')}</p>
            </div>
            <Switch id="trig-enabled" checked={enabled} onCheckedChange={setEnabled} />
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
