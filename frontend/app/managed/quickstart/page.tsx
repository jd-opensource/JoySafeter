'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from '@/lib/i18n'
import {
  Check,
  CheckCircle2,
  ChevronDown,
  Copy,
  Search,
  Loader2,
  FileText,
  Globe,
  Database,
  Shield,
  MessageSquare,
  AlertTriangle,
  BarChart3,
  Users,
  ArrowUpRight,
  Sparkles,
  Play,
  Square,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'
import {
  useQuickstartChat,
  type QuickstartEngine,
  type StepId,
} from '@/hooks/managed/use-quickstart-chat'
import { managedGet, managedPost } from '@/lib/api-client'
import { toastOperationError } from '@/lib/managed/errors'
import { shortIdWithPrefix, stripIdPrefix } from '@/lib/managed/id'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useSessionStream } from '@/lib/managed/sse'
import { useRouter } from 'next/navigation'
import type { Environment, PaginatedResponse, Session, SessionEvent, Vault } from '@/types/managed'
import { EventList, EventDetail, EventFilter } from '@/components/managed/session'
import yaml from 'js-yaml'

const TEMPLATE_ICONS: Record<string, typeof FileText> = {
  blank: FileText,
  researcher: Globe,
  extractor: Database,
  monitor: Shield,
  support: MessageSquare,
  incident: AlertTriangle,
  feedback: BarChart3,
  retro: Users,
  escalator: ArrowUpRight,
  analyst: Sparkles,
}

const TEMPLATE_IDS = [
  'blank',
  'researcher',
  'extractor',
  'monitor',
  'support',
  'incident',
  'feedback',
  'retro',
  'escalator',
  'analyst',
]

const STEP_API_ENDPOINTS: Record<number, string> = {
  3: '/agents',
  4: '/environments',
  5: '/vaults',
  6: '/sessions',
}

type QuickstartSecret = {
  name: string
  provider?: string
  protocol?: string
  is_default?: boolean
  keys?: string[]
}

function isSecretCompatible(secret: QuickstartSecret | undefined, engine: QuickstartEngine | null) {
  if (!secret) return false
  if (!engine) return true
  const provider = (secret.provider || '').toLowerCase()
  const protocol = (secret.protocol || '').toLowerCase()
  const keys = new Set(secret.keys || [])
  if (engine === 'codex') {
    return (
      provider === 'codex' ||
      protocol === 'openai_responses' ||
      protocol === 'chat_completions' ||
      keys.has('OPENAI_API_KEY')
    )
  }
  return (
    provider === 'anthropic' ||
    provider === 'claude' ||
    protocol === 'anthropic_messages' ||
    keys.has('ANTHROPIC_API_KEY') ||
    keys.has('ANTHROPIC_AUTH_TOKEN')
  )
}

function secretDetail(secret: QuickstartSecret) {
  const provider = secret.provider && secret.provider !== 'custom' ? secret.provider : ''
  const modelKey = secret.keys?.find((key) => ['ANTHROPIC_MODEL', 'OPENAI_MODEL'].includes(key))
  return [provider, modelKey, secret.is_default ? 'default' : ''].filter(Boolean).join(' · ')
}

function generationProviderForSecret(secret: QuickstartSecret | undefined): QuickstartEngine {
  if (!secret) return 'claude'
  return isSecretCompatible(secret, 'codex') ? 'codex' : 'claude'
}

// -- Stepper ----------------------------------------------------------------

function Stepper({
  currentStep,
  completedSteps,
}: {
  currentStep: StepId
  completedSteps: Set<number>
}) {
  const { t } = useTranslation()
  const steps = [
    { num: 1 as StepId, label: t('managed.quickstart.step.chooseEngine') },
    { num: 2 as StepId, label: t('managed.quickstart.step.chooseSecret') },
    { num: 3 as StepId, label: t('managed.quickstart.step.createAgent') },
    { num: 4 as StepId, label: t('managed.quickstart.step.configureEnv') },
    { num: 5 as StepId, label: t('managed.quickstart.step.configureVault') },
    { num: 6 as StepId, label: t('managed.quickstart.step.startSession') },
  ]

  return (
    <div className="mb-4 flex items-center justify-center gap-2 py-3">
      {steps.map((step, i) => {
        const isDone = completedSteps.has(step.num)
        const isActive = step.num === currentStep

        return (
          <div key={step.num} className="flex items-center gap-2">
            {i > 0 && <span className="mx-1 text-muted-foreground/60">→</span>}
            <div className="flex items-center gap-2 whitespace-nowrap">
              <span
                className={cn(
                  'flex h-6 w-6 items-center justify-center rounded-full border text-[11px] font-semibold',
                  isDone && 'border-green-500 bg-green-500 text-white',
                  isActive && !isDone && 'border-primary bg-primary/10 text-primary',
                  !isDone && !isActive && 'border-border text-muted-foreground',
                )}
              >
                {isDone ? <Check className="h-3 w-3" /> : step.num}
              </span>
              <span
                className={cn(
                  'text-sm font-medium',
                  isActive
                    ? 'text-foreground'
                    : isDone
                      ? 'text-foreground'
                      : 'text-muted-foreground',
                )}
              >
                {step.label}
              </span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

// -- ApiCard ----------------------------------------------------------------

function ApiCard({ endpoint, curl }: { endpoint: string; curl: string }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = () => {
    navigator.clipboard.writeText(curl)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="rounded-xl border border-border bg-background">
      <div className="flex items-center justify-between border-b border-border px-3 py-2 text-xs">
        <div className="flex items-center gap-2">
          <span className="rounded bg-muted px-1.5 py-0.5 font-semibold text-[#4f8cc9]">POST</span>
          <span className="font-mono text-[12px] text-foreground">{endpoint}</span>
        </div>
        <div className="flex items-center gap-2 text-muted-foreground">
          <span className="flex items-center gap-1">
            cURL
            <ChevronDown className="h-3.5 w-3.5" />
          </span>
          <button onClick={handleCopy} className="transition-colors hover:text-foreground">
            {copied ? (
              <Check className="h-3.5 w-3.5 text-green-500" />
            ) : (
              <Copy className="h-3.5 w-3.5" />
            )}
          </button>
        </div>
      </div>
      <pre className="max-h-[320px] overflow-auto px-3 py-2 font-mono text-[12px] leading-6 text-foreground/90">
        {curl}
      </pre>
    </div>
  )
}

// -- ChatBubble -------------------------------------------------------------

function ChatBubble({
  message,
}: {
  message: { role: string; content: string; isStreaming?: boolean }
}) {
  const { t } = useTranslation()
  const isUser = message.role === 'user'

  return (
    <div className={cn('flex', isUser ? 'justify-end' : 'justify-start')}>
      <div
        className={cn(
          'max-w-[365px] rounded-2xl p-4 text-[14px] leading-7',
          isUser ? 'bg-muted text-foreground/90' : 'text-foreground/85',
        )}
      >
        <div className="whitespace-pre-wrap">{message.content}</div>
        {message.isStreaming && !message.content && (
          <div className="flex items-center gap-1.5 text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            <span className="text-xs">{t('managed.quickstart.thinking')}</span>
          </div>
        )}
        {message.isStreaming && message.content && (
          <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-foreground/60 align-text-bottom" />
        )}
      </div>
    </div>
  )
}

// -- StepCompleteCard -------------------------------------------------------

function StepCompleteCard({
  step,
  curl,
  endpoint,
  onNext,
  nextLabel,
}: {
  step: number
  curl: string
  endpoint: string
  onNext: () => void
  nextLabel: string
}) {
  const { t } = useTranslation()
  const titles: Record<number, string> = {
    2: t('managed.quickstart.stepComplete.secretSelected'),
    3: t('managed.quickstart.stepComplete.agentCreated'),
    4: t('managed.quickstart.stepComplete.envCreated'),
    5: t('managed.quickstart.stepComplete.vaultCreated'),
    6: t('managed.quickstart.stepComplete.sessionStarted'),
  }
  const descriptions: Record<number, string> = {
    1: t('managed.quickstart.stepDesc.1'),
    2: t('managed.quickstart.stepDesc.2'),
    3: t('managed.quickstart.stepDesc.3'),
    4: t('managed.quickstart.stepDesc.4'),
    5: t('managed.quickstart.stepDesc.5'),
    6: t('managed.quickstart.stepDesc.6'),
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
        <CheckCircle2 className="h-4 w-4 text-muted-foreground" />
        {titles[step] || t('common.done')}
      </div>
      <ApiCard endpoint={endpoint} curl={curl} />
      {descriptions[step] && (
        <p className="text-[13px] leading-6 text-foreground/80">{descriptions[step]}</p>
      )}
      <Button className="h-10 rounded-xl px-4 text-sm" onClick={onNext}>
        {nextLabel}
      </Button>
    </div>
  )
}

// -- TemplateCard -----------------------------------------------------------

function TemplateCard({ templateId, onClick }: { templateId: string; onClick: () => void }) {
  const { t } = useTranslation()
  const Icon = TEMPLATE_ICONS[templateId] || FileText
  return (
    <button
      onClick={onClick}
      className="flex items-start gap-3 rounded-xl border border-border bg-background p-4 text-left transition-colors hover:bg-muted/50"
    >
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-muted">
        <Icon className="h-4.5 w-4.5 text-muted-foreground" />
      </div>
      <div className="min-w-0">
        <div className="text-[14px] font-semibold text-foreground">
          {t(`quickstart.template.${templateId}.name`)}
        </div>
        <div className="mt-0.5 text-[13px] leading-5 text-muted-foreground">
          {t(`quickstart.template.${templateId}.description`)}
        </div>
      </div>
    </button>
  )
}

// -- NumberedChoiceList ------------------------------------------------------

function NumberedChoiceList({
  question,
  choices,
  onSelect,
  onSkip,
}: {
  question: string
  choices: { num: number; label: string; arrow?: boolean }[]
  onSelect: (num: number) => void
  onSkip?: () => void
}) {
  const { t } = useTranslation()
  return (
    <div className="rounded-xl border border-border bg-background p-4">
      <p className="mb-1 text-[14px] font-semibold text-foreground">{question}</p>
      <div className="mt-2 space-y-0.5">
        {choices.map((c) => (
          <button
            key={c.num}
            onClick={() => onSelect(c.num)}
            className="flex w-full items-center gap-3 rounded-lg px-2 py-2.5 text-left transition-colors hover:bg-muted/50"
          >
            <span
              className={cn(
                'w-5 shrink-0 text-right text-sm',
                c.num === 0 ? 'italic text-muted-foreground/60' : 'text-muted-foreground',
              )}
            >
              {c.num}
            </span>
            <span
              className={cn(
                'flex-1 text-[14px]',
                c.num === 0 ? 'text-muted-foreground' : 'text-foreground',
              )}
            >
              {c.label}
            </span>
            {c.arrow && <span className="text-sm text-muted-foreground">&rarr;</span>}
          </button>
        ))}
      </div>
      {onSkip && (
        <div className="mt-2 flex justify-end">
          <Button
            variant="ghost"
            size="sm"
            className="text-xs text-muted-foreground"
            onClick={onSkip}
          >
            {t('common.skip')}
          </Button>
        </div>
      )}
    </div>
  )
}

// -- QADisplay --------------------------------------------------------------

function QADisplay({ question, answer }: { question: string; answer: string }) {
  const { t } = useTranslation()

  return (
    <div className="flex justify-end">
      <div className="max-w-[365px] rounded-2xl bg-muted p-4 text-[14px] leading-7 text-foreground/90">
        <div className="whitespace-pre-wrap">
          <span className="font-semibold">{t('managed.quickstart.questionLabel')}:</span> {question}
          {'\n'}
          <span className="font-semibold">{t('managed.quickstart.answerLabel')}:</span> {answer}
        </div>
      </div>
    </div>
  )
}

// -- StepDoneBadge ----------------------------------------------------------

function StepDoneBadge({
  label,
  curl,
  endpoint,
}: {
  label: string
  curl?: string
  endpoint?: string
}) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div className="rounded-xl border border-border bg-muted/30 p-3">
      <button
        className="flex w-full items-center gap-2 text-left text-sm"
        onClick={() => setExpanded(!expanded)}
      >
        <CheckCircle2 className="h-4 w-4 shrink-0 text-muted-foreground" />
        <span className="flex-1 font-semibold text-foreground">{label}</span>
        <ChevronDown
          className={cn(
            'h-3.5 w-3.5 text-muted-foreground transition-transform',
            expanded && 'rotate-180',
          )}
        />
      </button>
      {expanded && curl && endpoint && (
        <div className="mt-3">
          <ApiCard endpoint={endpoint} curl={curl} />
        </div>
      )}
    </div>
  )
}

// -- TrialRunBanner ---------------------------------------------------------

function TrialRunBanner({
  status,
  onGoBack,
  onContinue,
}: {
  status: 'idle' | 'testing' | 'success' | 'error'
  onGoBack: () => void
  onContinue: () => void
}) {
  const { t } = useTranslation()
  if (status === 'idle') return null

  return (
    <div
      className={cn(
        'flex items-center gap-3 border-b border-border px-4 py-2.5 text-sm',
        status === 'testing' && 'bg-blue-50 dark:bg-blue-950/20',
        status === 'success' && 'bg-green-50 dark:bg-green-950/20',
        status === 'error' && 'bg-amber-50 dark:bg-amber-950/20',
      )}
    >
      {status === 'testing' && (
        <>
          <Loader2 className="h-4 w-4 animate-spin text-blue-500" />
          <span className="text-blue-700 dark:text-blue-400">
            {t('managed.quickstart.trialRun.testing')}
          </span>
        </>
      )}
      {status === 'success' && (
        <>
          <CheckCircle2 className="h-4 w-4 text-green-500" />
          <span className="text-green-700 dark:text-green-400">
            {t('managed.quickstart.trialRun.success')}
          </span>
        </>
      )}
      {status === 'error' && (
        <>
          <AlertTriangle className="h-4 w-4 text-amber-500" />
          <span className="text-amber-700 dark:text-amber-400">
            {t('managed.quickstart.trialRun.error')}
          </span>
          <div className="ml-auto flex items-center gap-2">
            <Button variant="outline" size="sm" className="text-xs" onClick={onGoBack}>
              {t('managed.quickstart.trialRun.goBack')}
            </Button>
            <Button variant="ghost" size="sm" className="text-xs" onClick={onContinue}>
              {t('managed.quickstart.trialRun.continue')}
            </Button>
          </div>
        </>
      )}
    </div>
  )
}

// -- Main Quickstart Page ---------------------------------------------------

export default function QuickstartPage() {
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
  const [editorTab, setEditorTab] = useState<'yaml' | 'json'>('yaml')
  const [rightTab, setRightTab] = useState<'config' | 'preview'>('config')
  const [secretRef, setSecretRef] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const configScrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const [inputValue, setInputValue] = useState('')
  const [templateSearch, setTemplateSearch] = useState('')
  const [selectedEnvId, setSelectedEnvId] = useState<string>('')
  const [localSessionId, setLocalSessionId] = useState('')
  const [isTestRunning, setIsTestRunning] = useState(false)
  const [isStoppingSession, setIsStoppingSession] = useState(false)
  const [previewTab, setPreviewTab] = useState<'transcript' | 'debug'>('debug')
  const [previewFilter, setPreviewFilter] = useState<Set<string>>(new Set())
  const [previewSearch, setPreviewSearch] = useState('')
  const [showPreviewSearch, setShowPreviewSearch] = useState(false)
  const [selectedPreviewEvent, setSelectedPreviewEvent] = useState<SessionEvent | null>(null)
  const autoIntroSentRef = useRef<Set<number>>(new Set())

  // Sub-step state for environment (step 2) inline flow
  const [envSubStep, setEnvSubStep] = useState<
    'choose' | 'networking' | 'hosts' | 'selected' | null
  >('choose')
  const [envUsesAI, setEnvUsesAI] = useState(false)
  const [envAnswers, setEnvAnswers] = useState<{
    choiceLabel?: string
    networkingLabel?: string
  }>({})
  const [envHosts, setEnvHosts] = useState('')
  const [pendingEnvId, setPendingEnvId] = useState<string | null>(null)

  // Sub-step state for vault (step 3) inline flow
  const [vaultSubStep, setVaultSubStep] = useState<'choose' | 'name' | 'selected' | null>('choose')
  const [vaultUsesAI, setVaultUsesAI] = useState(false)
  const [vaultAnswers, setVaultAnswers] = useState<{ choiceLabel?: string }>({})
  const [vaultName, setVaultName] = useState('')
  const [pendingVaultId, setPendingVaultId] = useState<string | null>(null)

  const { data: secretsRes } = useQuery({
    queryKey: ['secrets'],
    queryFn: () => managedGet<{ data: QuickstartSecret[] }>('/secrets'),
  })
  const secrets = secretsRes?.data

  const { data: environments } = useQuery({
    queryKey: ['environments-active'],
    queryFn: async () => {
      const res = await managedGet<PaginatedResponse<Environment>>('/environments')
      return res.data || []
    },
  })

  const { data: vaultsRes } = useQuery({
    queryKey: ['vaults-active'],
    queryFn: () => managedGet<{ data: Vault[] }>('/vaults'),
  })
  const vaults = vaultsRes?.data

  const defaultGenerationSecret = useMemo(() => {
    if (!secrets || secrets.length === 0) return undefined
    return secrets.find((secret) => secret.is_default) || secrets[0]
  }, [secrets])

  const generationSecret = useMemo(() => {
    if (!defaultGenerationSecret) return undefined
    return {
      secretRef: defaultGenerationSecret.name,
      provider: generationProviderForSecret(defaultGenerationSecret),
    }
  }, [defaultGenerationSecret])

  const {
    messages,
    currentStep,
    selectedEngine,
    config,
    isStreaming,
    curls,
    resourceIds,
    completedSteps,
    pendingConfirmation,
    isCreating,
    sendMessage,
    selectEngine,
    selectAgentSecret,
    advanceStep,
    confirmStep,
    keepRefining,
    createSession,
    createEnvironment,
    selectExistingEnvironment,
    createVault,
    selectExistingVault,
    goToStep,
    sendAutoIntro,
    generateTestMessage,
  } = useQuickstartChat(secretRef, generationSecret)

  const compatibleSecrets = useMemo(() => {
    return (secrets || []).filter((secret) => isSecretCompatible(secret, selectedEngine))
  }, [secrets, selectedEngine])

  const selectedSecret = useMemo(() => {
    return (secrets || []).find((secret) => secret.name === secretRef)
  }, [secrets, secretRef])

  const selectedSecretCompatible = isSecretCompatible(selectedSecret, selectedEngine)

  useEffect(() => {
    if (!secrets || secrets.length === 0) return
    const candidates = compatibleSecrets.length > 0 ? compatibleSecrets : secrets
    const currentIsAllowed = candidates.some((secret) => secret.name === secretRef)
    if (!secretRef || !currentIsAllowed) {
      setSecretRef((candidates.find((secret) => secret.is_default) || candidates[0]).name)
    }
  }, [compatibleSecrets, secrets, secretRef])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const isLanding = messages.length === 0 && !isStreaming
  const rawSessionId = resourceIds[6] || localSessionId
  const sessionId = rawSessionId ? stripIdPrefix(rawSessionId) : ''
  const isSessionActive = !!sessionId

  const { events: sessionEvents } = useSessionStream(sessionId, isSessionActive)

  const { data: activeSession } = useQuery({
    queryKey: ['session', rawSessionId],
    queryFn: () => managedGet<Session>(`/sessions/${sessionId}`),
    enabled: isSessionActive,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'running' ? 3000 : false
    },
  })

  const previewAvailableTypes = useMemo(() => {
    const types = new Set<string>()
    for (const e of sessionEvents) {
      const t = e.type || ''
      if (t) types.add(t)
    }
    return Array.from(types).sort()
  }, [sessionEvents])

  const mergedSessionEvents = useMemo(() => {
    const TRANSCRIPT_TYPES = new Set([
      'user.message',
      'agent.message',
      'agent.mcp_tool_use',
      'agent.mcp_tool_result',
      'agent.tool_use',
      'agent.tool_result',
      'agent.custom_tool_use',
      'user.custom_tool_result',
      'user.tool_result',
      'session.status_idle',
      'session.status_running',
      'session.status_terminated',
    ])

    let filtered = sessionEvents
    if (previewTab === 'transcript') {
      filtered = sessionEvents.filter((e) => TRANSCRIPT_TYPES.has(e.type || ''))
    } else if (previewFilter.size > 0) {
      filtered = sessionEvents.filter((e) => previewFilter.has(e.type || ''))
    }

    if (previewSearch) {
      const lower = previewSearch.toLowerCase()
      filtered = filtered.filter((e) => JSON.stringify(e).toLowerCase().includes(lower))
    }

    const MERGEABLE = new Set([
      'agent.message',
      'agent.thinking',
      'agent.tool_use',
      'agent.tool_result',
    ])
    const merged: typeof filtered = []
    const extractText = (e: SessionEvent): string => {
      if (Array.isArray(e.content)) return e.content.map((b) => b.text || '').join('')
      if (typeof e.content === 'string') return e.content
      return ''
    }
    for (const evt of filtered) {
      const t = evt.type || ''
      if (MERGEABLE.has(t)) {
        const prev = merged[merged.length - 1]
        if (prev && (prev.type || '') === t) {
          if (t === 'agent.message' || t === 'agent.thinking') {
            const combined = extractText(prev) + extractText(evt)
            merged[merged.length - 1] = {
              ...prev,
              content: [{ type: 'text', text: combined }],
            }
          } else {
            merged[merged.length - 1] = {
              ...prev,
              ...(evt.name ? { name: evt.name } : {}),
              ...(evt.input !== undefined ? { input: evt.input } : {}),
              ...(evt.output !== undefined ? { output: evt.output } : {}),
              ...(evt.tool_name ? { tool_name: evt.tool_name } : {}),
            }
          }
          continue
        }
      }
      merged.push(evt)
    }
    return merged
  }, [sessionEvents, previewTab, previewFilter, previewSearch])

  useEffect(() => {
    if (isSessionActive) setRightTab('preview')
  }, [isSessionActive])
  const [sessionMsgInput, setSessionMsgInput] = useState('')
  const [isSendingMsg, setIsSendingMsg] = useState(false)

  const isSessionRunning = useMemo(() => {
    if (activeSession?.status) return activeSession.status === 'running'
    if (sessionEvents.length === 0) return false
    for (let i = sessionEvents.length - 1; i >= 0; i--) {
      const evtType = sessionEvents[i].type || sessionEvents[i].event_type || ''
      if (
        evtType === 'session.status_idle' ||
        evtType === 'session.status_terminated' ||
        evtType === 'task.complete'
      )
        return false
      if (evtType === 'session.status_running' || evtType === 'user.message') return true
    }
    return false
  }, [activeSession?.status, sessionEvents])

  const handleStopSession = async () => {
    if (!sessionId || isStoppingSession) return
    setIsStoppingSession(true)
    try {
      await managedPost(`/sessions/${sessionId}/stop`, {})
      queryClient.invalidateQueries({ queryKey: ['session', rawSessionId] })
    } catch (e) {
      toastOperationError(t, e, 'common.operationFailed')
    } finally {
      setIsStoppingSession(false)
    }
  }

  const handleSendSessionMessage = async () => {
    const text = sessionMsgInput.trim()
    if (!text || !sessionId || isSendingMsg || isSessionRunning) return
    setIsSendingMsg(true)
    setSessionMsgInput('')
    try {
      await managedPost(`/sessions/${sessionId}/events`, {
        events: [{ type: 'user.message', content: [{ type: 'text', text }] }],
      })
    } catch (e) {
      const msg = (e as Error).message
      if (!msg.includes('409') && !msg.includes('running')) {
        toastOperationError(t, e, 'common.operationFailed')
      }
    } finally {
      setIsSendingMsg(false)
    }
  }

  const activeEnvironments = useMemo(() => {
    return (environments || []).filter((e) => !e.archived_at)
  }, [environments])

  const activeVaults = useMemo(() => {
    return (vaults || []).filter((v) => !v.archived_at)
  }, [vaults])

  const selectedEnvironmentName = useMemo(() => {
    return (
      activeEnvironments.find((env) => env.id === selectedEnvId)?.name ||
      activeSession?.environment_id ||
      ''
    )
  }, [activeEnvironments, activeSession?.environment_id, selectedEnvId])

  // Auto-send AI intro only when user chose "Something else" (AI mode)
  useEffect(() => {
    if (currentStep === 4 && envUsesAI && !completedSteps.has(4) && !isStreaming) {
      if (!autoIntroSentRef.current.has(4)) {
        autoIntroSentRef.current.add(4)
        sendAutoIntro(4 as StepId)
      }
    }
    if (currentStep === 5 && vaultUsesAI && !completedSteps.has(5) && !isStreaming) {
      if (!autoIntroSentRef.current.has(5)) {
        autoIntroSentRef.current.add(5)
        sendAutoIntro(5 as StepId)
      }
    }
  }, [currentStep, completedSteps, isStreaming, sendAutoIntro, envUsesAI, vaultUsesAI])

  // Auto-switch to preview and generate test message when session is created
  useEffect(() => {
    const sid = resourceIds[6] || localSessionId
    if (sid) {
      setRightTab('preview')
      generateTestMessage().then((msg) => {
        if (msg) setSessionMsgInput(msg)
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resourceIds[6], localSessionId])

  // Sync environment created in quickstart to the preview panel dropdown
  useEffect(() => {
    if (resourceIds[4]) setSelectedEnvId(resourceIds[4])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resourceIds[4]])

  const handleEnvSkip = () => {
    advanceStep()
  }

  const handleVaultSkip = () => {
    advanceStep()
  }

  // Trial run status derived from session events
  const trialRunStatus = useMemo(() => {
    if (!isSessionActive || sessionEvents.length === 0) return 'idle' as const
    const hasUserMessage = sessionEvents.some((e) => e.type === 'user.message')
    if (!hasUserMessage) return 'idle' as const
    const hasAgentMessage = sessionEvents.some((e) => e.type === 'agent.message')
    const isTerminated = sessionEvents.some((e) => e.type === 'session.status_terminated')
    const isIdle = sessionEvents.some((e) => e.type === 'session.status_idle')
    if (isTerminated) return 'error' as const
    if (hasAgentMessage && isIdle) return 'success' as const
    return 'testing' as const
  }, [isSessionActive, sessionEvents])

  const handleTestRun = async () => {
    const agentId = resourceIds[3]
    if (!agentId) return
    setIsTestRunning(true)
    try {
      const body: Record<string, unknown> = { agent: agentId }
      if (selectedEnvId) body.environment_id = stripIdPrefix(selectedEnvId)
      const res = await managedPost<{ id: string }>('/sessions', body)
      setLocalSessionId(res.id)
      setRightTab('preview')
    } catch (e) {
      toastOperationError(t, e, 'common.operationFailed')
    } finally {
      setIsTestRunning(false)
    }
  }

  const filteredTemplates = useMemo(() => {
    if (!templateSearch.trim()) return TEMPLATE_IDS
    const q = templateSearch.toLowerCase()
    return TEMPLATE_IDS.filter(
      (id) =>
        t(`quickstart.template.${id}.name`).toLowerCase().includes(q) ||
        t(`quickstart.template.${id}.description`).toLowerCase().includes(q),
    )
  }, [templateSearch, t])

  const handleTemplateClick = (templateId: string) => {
    const name = t(`quickstart.template.${templateId}.name`)
    const desc = t(`quickstart.template.${templateId}.description`)
    if (templateId === 'blank') {
      sendMessage('Create a blank agent with default configuration')
    } else {
      sendMessage(`Create a ${name.toLowerCase()} agent: ${desc}`)
    }
  }

  const configObj = useMemo(() => {
    if (currentStep === 4 && config.environment) {
      return config.environment
    }
    if (currentStep === 5 && config.vault) {
      return config.vault
    }
    if (!config.agent) return null
    const a = config.agent
    const ordered: Record<string, unknown> = {}
    if (a.name) ordered.name = a.name
    if (a.model) ordered.model = a.model
    if (a.description) ordered.description = a.description
    if (a.system_prompt || a.system) ordered.system = a.system_prompt || a.system
    if (a.tools) ordered.tools = a.tools
    if (a.metadata) ordered.metadata = a.metadata
    return ordered
  }, [config, currentStep])

  const configText = useMemo(() => {
    if (!configObj) {
      const label = currentStep === 4 ? 'Environment' : currentStep === 5 ? 'Vault' : 'Agent'
      return editorTab === 'yaml'
        ? `# ${label} configuration will appear here\n# as the AI generates it...`
        : `{\n  // ${label} configuration will appear here\n  // as the AI generates it...\n}`
    }
    try {
      if (editorTab === 'yaml') return yaml.dump(configObj, { lineWidth: -1, noRefs: true })
      return JSON.stringify(configObj, null, 2)
    } catch {
      return JSON.stringify(configObj, null, 2)
    }
  }, [configObj, editorTab, currentStep])

  const codeLines = configText.split('\n')

  useEffect(() => {
    const el = configScrollRef.current
    if (!el || rightTab !== 'config') return

    el.scrollTop = el.scrollHeight
  }, [configText, rightTab])

  const handleSend = () => {
    const text = inputValue.trim()
    if (!text || isStreaming || isSessionRunning) return
    setInputValue('')
    sendMessage(text)
  }

  const handleQuickstartEngineSelect = (engine: QuickstartEngine) => {
    const engineSecrets = (secrets || []).filter((secret) => isSecretCompatible(secret, engine))
    const currentSecretIsCompatible = isSecretCompatible(selectedSecret, engine)
    const nextSecret = currentSecretIsCompatible
      ? selectedSecret
      : engineSecrets.find((secret) => secret.is_default) || engineSecrets[0]

    if (nextSecret && nextSecret.name !== secretRef) {
      setSecretRef(nextSecret.name)
    }
    selectEngine(engine)
  }

  const handleAgentSecretSelect = (name: string) => {
    setSecretRef(name)
    selectAgentSecret()
  }

  const isMainInputDisabled =
    isStreaming ||
    currentStep === 2 ||
    !generationSecret?.secretRef ||
    (currentStep >= 3 && (!secretRef || !selectedSecretCompatible))
  const isMainSendDisabled = isMainInputDisabled || isSessionRunning || !inputValue.trim()

  return (
    <div className="w-full">
      <h1 className="px-1 pt-1 text-lg font-semibold text-foreground">
        {t('managed.quickstart.title')}
      </h1>

      <Stepper currentStep={currentStep} completedSteps={completedSteps} />

      {!isLanding && (
        <div className="flex items-center justify-end gap-2 px-1 pb-3">
          {isSessionActive && isSessionRunning ? (
            <Button
              size="sm"
              className="gap-1.5 bg-foreground text-xs text-background hover:bg-foreground/90"
              disabled={isStoppingSession}
              onClick={handleStopSession}
            >
              {isStoppingSession ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Square className="h-3.5 w-3.5" />
              )}
              {t('managed.quickstart.stopSession')}
            </Button>
          ) : !isSessionActive ? (
            <Button
              size="sm"
              className="gap-1.5 text-xs"
              disabled={!resourceIds[3] || isTestRunning}
              onClick={handleTestRun}
            >
              {isTestRunning ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Play className="h-3.5 w-3.5" />
              )}
              {t('managed.quickstart.testRun')}
            </Button>
          ) : (
            <div className="h-8" />
          )}
        </div>
      )}

      {secrets && secrets.length === 0 && (
        <div className="mb-4 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-amber-950 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-100">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex gap-3">
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
              <div>
                <div className="text-sm font-semibold">
                  {t('managed.quickstart.secretRequiredTitle')}
                </div>
                <p className="mt-1 text-sm leading-relaxed text-amber-900/80 dark:text-amber-100/80">
                  {t('managed.quickstart.secretRequiredDescription')}
                </p>
              </div>
            </div>
            <Button size="sm" className="shrink-0" onClick={() => router.push('/managed/secrets')}>
              {t('managed.quickstart.configureSecret')}
            </Button>
          </div>
        </div>
      )}

      {isLanding ? (
        <div className="grid min-h-[calc(100vh-160px)] gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
          <section className="flex flex-col rounded-2xl border border-border bg-card p-6">
            <div className="flex flex-1 flex-col justify-center">
              <h2 className="whitespace-pre-line text-[32px] font-bold leading-tight tracking-tight text-foreground">
                {t('managed.quickstart.whatToBuild')}
              </h2>
              <p className="mt-3 max-w-[340px] text-[15px] leading-relaxed text-muted-foreground">
                {t('managed.quickstart.subtitle')}
              </p>
            </div>
            <div className="rounded-xl border border-border bg-background px-3 py-2.5">
              <div className="flex items-center gap-2">
                <input
                  ref={inputRef}
                  type="text"
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault()
                      handleSend()
                    }
                  }}
                  disabled={isMainInputDisabled}
                  placeholder={
                    !generationSecret?.secretRef
                      ? t('managed.quickstart.noApiKey')
                      : currentStep === 2
                        ? t('managed.quickstart.chooseSecret')
                        : currentStep >= 3 && !selectedSecretCompatible
                          ? t('managed.quickstart.noCompatibleSecret')
                          : isSessionRunning
                            ? t('managed.quickstart.agentProcessing')
                            : isStreaming
                              ? t('managed.quickstart.waitingForResponse')
                              : t('managed.quickstart.describeAgent')
                  }
                  className="h-8 flex-1 border-0 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground disabled:opacity-50"
                />
                <button
                  onClick={handleSend}
                  disabled={isMainSendDisabled}
                  className={cn(
                    'inline-flex h-6 w-6 items-center justify-center rounded-md text-xs font-semibold text-primary-foreground shadow-sm transition-colors',
                    isMainSendDisabled
                      ? 'cursor-not-allowed bg-muted-foreground/30 text-white shadow-none'
                      : 'bg-primary hover:bg-primary/90',
                  )}
                  aria-label={t('managed.quickstart.sendMessage')}
                >
                  &uarr;
                </button>
              </div>
            </div>
          </section>

          <section className="overflow-auto rounded-2xl border border-border bg-card p-6">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-[16px] font-semibold text-foreground">
                {t('managed.quickstart.browseTemplates')}
              </h3>
            </div>
            <div className="relative mb-4">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <input
                type="text"
                value={templateSearch}
                onChange={(e) => setTemplateSearch(e.target.value)}
                placeholder={t('managed.quickstart.searchTemplates')}
                className="h-9 w-full rounded-lg border border-border bg-background pl-9 pr-3 text-sm text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-ring"
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              {filteredTemplates.map((id) => (
                <TemplateCard key={id} templateId={id} onClick={() => handleTemplateClick(id)} />
              ))}
            </div>
            {filteredTemplates.length === 0 && (
              <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
                {t('managed.quickstart.noTemplatesMatch')}
              </div>
            )}
          </section>
        </div>
      ) : (
        <div className="rounded-2xl border border-border bg-card p-2 shadow-[0_6px_18px_rgba(15,23,42,0.05)]">
          <div className="grid min-h-[calc(100vh-168px)] gap-0 lg:grid-cols-[420px_minmax(0,1fr)]">
            {/* Left panel: chat */}
            <section className="relative border-r border-border bg-background px-5 pb-16 pt-5">
              <div className="h-[calc(100vh-250px)] space-y-4 overflow-y-auto pr-1">
                {messages.map((msg) => (
                  <ChatBubble key={msg.id} message={msg} />
                ))}

                {currentStep === 1 && !completedSteps.has(1) && (
                  <NumberedChoiceList
                    question={t('managed.quickstart.engineQuestion')}
                    choices={[
                      { num: 1, label: t('managed.quickstart.engineClaudecode'), arrow: true },
                      { num: 2, label: t('managed.quickstart.engineCodex') },
                      { num: 3, label: t('managed.quickstart.engineNative') },
                    ]}
                    onSelect={(num) =>
                      handleQuickstartEngineSelect(
                        num === 2 ? 'codex' : num === 3 ? 'native' : 'claude',
                      )
                    }
                  />
                )}

                {currentStep === 2 &&
                  !completedSteps.has(2) &&
                  (compatibleSecrets.length > 0 ? (
                    <NumberedChoiceList
                      question={t('managed.quickstart.secretQuestion')}
                      choices={compatibleSecrets.map((secret, index) => ({
                        num: index + 1,
                        label: `${secret.name}${secretDetail(secret) ? ` · ${secretDetail(secret)}` : ''}`,
                      }))}
                      onSelect={(num) => {
                        const secret = compatibleSecrets[num - 1]
                        if (secret) handleAgentSecretSelect(secret.name)
                      }}
                    />
                  ) : (
                    <div className="space-y-3 rounded-xl border border-border bg-background p-4">
                      <p className="text-sm font-semibold text-foreground">
                        {t('managed.quickstart.noCompatibleSecret')}
                      </p>
                      <Button
                        className="h-9 rounded-xl px-4 text-sm"
                        onClick={() => router.push('/managed/secrets')}
                      >
                        {t('managed.quickstart.configureSecret')}
                      </Button>
                    </div>
                  ))}

                {/* Step 2 secret: show completed badge before the next step actions */}
                {currentStep > 2 && completedSteps.has(2) && selectedSecret && (
                  <StepDoneBadge
                    label={`${t('managed.quickstart.stepComplete.secretSelected')}: ${selectedSecret.name}`}
                  />
                )}

                {pendingConfirmation && pendingConfirmation.step === currentStep && (
                  <div className="flex items-center gap-3 pt-1">
                    <Button
                      className="h-10 rounded-xl px-5 text-sm font-semibold"
                      onClick={confirmStep}
                      disabled={isCreating}
                    >
                      {isCreating ? (
                        <>
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          {t('managed.quickstart.creating')}
                        </>
                      ) : currentStep === 3 ? (
                        t('managed.quickstart.createThisAgent')
                      ) : currentStep === 4 ? (
                        t('managed.quickstart.createThisEnvironment')
                      ) : currentStep === 5 ? (
                        t('managed.quickstart.createThisVault')
                      ) : (
                        t('common.create')
                      )}
                    </Button>
                    <Button
                      variant="outline"
                      className="h-10 rounded-xl px-4 text-sm font-semibold"
                      onClick={keepRefining}
                      disabled={isCreating}
                    >
                      {t('managed.quickstart.keepRefining')}
                    </Button>
                  </div>
                )}

                {/* Step 3 agent: show completed badge when past step 3 */}
                {currentStep > 3 && completedSteps.has(3) && (
                  <StepDoneBadge
                    label={`${t('managed.quickstart.stepComplete.agentCreated')}${config.agent?.name ? `: ${config.agent.name}` : ''}`}
                    curl={curls[3]}
                    endpoint={STEP_API_ENDPOINTS[3]}
                  />
                )}

                {/* Step 4 env: show completed summary when past step 4, or active UI when on step 4 */}
                {currentStep > 4 &&
                  completedSteps.has(4) &&
                  !envUsesAI &&
                  envAnswers.choiceLabel && (
                    <StepDoneBadge
                      label={`${t('managed.quickstart.stepComplete.envCreated')}: ${envAnswers.choiceLabel}`}
                      curl={curls[4]}
                      endpoint={STEP_API_ENDPOINTS[4]}
                    />
                  )}

                {currentStep === 4 &&
                  (!completedSteps.has(4) || envSubStep === 'selected') &&
                  !pendingConfirmation &&
                  !envUsesAI && (
                    <>
                      {envSubStep === 'choose' && (
                        <NumberedChoiceList
                          question={t('managed.quickstart.envReuseOrCreate')}
                          choices={[
                            ...activeEnvironments.map((e, i) => ({ num: i + 1, label: e.name })),
                            {
                              num: activeEnvironments.length + 1,
                              label: t('managed.quickstart.envCreateNew'),
                            },
                            { num: 0, label: t('managed.quickstart.envSomethingElse') },
                          ]}
                          onSelect={(num) => {
                            if (num === 0) {
                              setEnvSubStep(null)
                              setEnvUsesAI(true)
                            } else if (num <= activeEnvironments.length) {
                              const env = activeEnvironments[num - 1]
                              setPendingEnvId(env.id)
                              setEnvAnswers({ choiceLabel: env.name })
                              setEnvSubStep('selected')
                            } else {
                              setEnvAnswers({ choiceLabel: t('managed.quickstart.envCreateNew') })
                              setEnvSubStep('networking')
                            }
                          }}
                          onSkip={handleEnvSkip}
                        />
                      )}

                      {envSubStep === 'selected' && (
                        <>
                          <QADisplay
                            question={t('managed.quickstart.envReuseOrCreate')}
                            answer={envAnswers.choiceLabel || ''}
                          />
                          <div className="flex items-center gap-2 pt-1">
                            <Button
                              className="h-10 rounded-xl px-5 text-sm font-semibold"
                              onClick={() => {
                                if (pendingEnvId) selectExistingEnvironment(pendingEnvId)
                                advanceStep()
                              }}
                            >
                              {t('managed.quickstart.nextConfigureVault')}
                            </Button>
                          </div>
                        </>
                      )}

                      {envSubStep === 'networking' && (
                        <>
                          <QADisplay
                            question={t('managed.quickstart.envReuseOrCreate')}
                            answer={envAnswers.choiceLabel || ''}
                          />
                          <NumberedChoiceList
                            question={t('managed.quickstart.envNetworkingQuestion')}
                            choices={[
                              { num: 1, label: t('managed.quickstart.envLimited'), arrow: true },
                              { num: 2, label: t('managed.quickstart.envUnrestricted') },
                              { num: 0, label: t('managed.quickstart.envSomethingElse') },
                            ]}
                            onSelect={(num) => {
                              if (num === 0) {
                                setEnvSubStep(null)
                                setEnvUsesAI(true)
                              } else if (num === 1) {
                                setEnvAnswers((prev) => ({
                                  ...prev,
                                  networkingLabel: t('managed.quickstart.envLimited'),
                                }))
                                setEnvSubStep('hosts')
                              } else {
                                createEnvironment('unrestricted', [])
                                setEnvAnswers((prev) => ({
                                  ...prev,
                                  networkingLabel: t('managed.quickstart.envUnrestricted'),
                                }))
                                setEnvSubStep('selected')
                              }
                            }}
                            onSkip={handleEnvSkip}
                          />
                        </>
                      )}

                      {envSubStep === 'hosts' && (
                        <>
                          <QADisplay
                            question={t('managed.quickstart.envReuseOrCreate')}
                            answer={envAnswers.choiceLabel || ''}
                          />
                          <QADisplay
                            question={t('managed.quickstart.envNetworkingQuestion')}
                            answer={envAnswers.networkingLabel || ''}
                          />
                          <div className="space-y-3 rounded-xl border border-border bg-background p-4">
                            <p className="text-[14px] font-semibold text-foreground">
                              {t('managed.quickstart.envHostsQuestion')}
                            </p>
                            <input
                              type="text"
                              value={envHosts}
                              onChange={(e) => setEnvHosts(e.target.value)}
                              placeholder={t('managed.quickstart.envHostsPlaceholder')}
                              className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-ring"
                            />
                            <p className="text-xs text-muted-foreground">
                              {t('managed.quickstart.envHostsHint')}
                            </p>
                            <div className="flex items-center justify-between">
                              <Button
                                className="h-9 rounded-xl px-4 text-sm"
                                disabled={isCreating}
                                onClick={() => {
                                  const hosts = envHosts
                                    .split(',')
                                    .map((h) => h.trim())
                                    .filter(Boolean)
                                  createEnvironment('limited', hosts)
                                  setEnvSubStep('selected')
                                }}
                              >
                                {isCreating ? (
                                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                                ) : null}
                                {t('managed.quickstart.createEnvironment')}
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="text-xs text-muted-foreground"
                                onClick={handleEnvSkip}
                              >
                                {t('common.skip')}
                              </Button>
                            </div>
                          </div>
                        </>
                      )}
                    </>
                  )}

                {/* Step 5 vault: show completed summary when past step 5, or active UI when on step 5 */}
                {currentStep > 5 &&
                  completedSteps.has(5) &&
                  !vaultUsesAI &&
                  vaultAnswers.choiceLabel && (
                    <StepDoneBadge
                      label={`${t('managed.quickstart.stepComplete.vaultCreated')}: ${vaultAnswers.choiceLabel}`}
                      curl={curls[5]}
                      endpoint={STEP_API_ENDPOINTS[5]}
                    />
                  )}

                {currentStep === 5 &&
                  (!completedSteps.has(5) || vaultSubStep === 'selected') &&
                  !pendingConfirmation &&
                  !vaultUsesAI && (
                    <>
                      {vaultSubStep === 'choose' && (
                        <NumberedChoiceList
                          question={t('managed.quickstart.vaultReuseOrCreate')}
                          choices={[
                            ...activeVaults.map((v, i) => ({ num: i + 1, label: v.name })),
                            {
                              num: activeVaults.length + 1,
                              label: t('managed.quickstart.vaultCreateNew'),
                            },
                            { num: 0, label: t('managed.quickstart.vaultSomethingElse') },
                          ]}
                          onSelect={(num) => {
                            if (num === 0) {
                              setVaultSubStep(null)
                              setVaultUsesAI(true)
                            } else if (num <= activeVaults.length) {
                              const vault = activeVaults[num - 1]
                              setPendingVaultId(vault.id)
                              setVaultAnswers({ choiceLabel: vault.name })
                              setVaultSubStep('selected')
                            } else {
                              setVaultAnswers({
                                choiceLabel: t('managed.quickstart.vaultCreateNew'),
                              })
                              setVaultSubStep('name')
                            }
                          }}
                          onSkip={handleVaultSkip}
                        />
                      )}

                      {vaultSubStep === 'selected' && (
                        <>
                          <QADisplay
                            question={t('managed.quickstart.vaultReuseOrCreate')}
                            answer={vaultAnswers.choiceLabel || ''}
                          />
                          <div className="flex items-center gap-2 pt-1">
                            <Button
                              className="h-10 rounded-xl px-5 text-sm font-semibold"
                              onClick={() => {
                                if (pendingVaultId) selectExistingVault(pendingVaultId)
                                advanceStep()
                              }}
                            >
                              {t('managed.quickstart.nextStartSession')}
                            </Button>
                          </div>
                        </>
                      )}

                      {vaultSubStep === 'name' && (
                        <>
                          <QADisplay
                            question={t('managed.quickstart.vaultReuseOrCreate')}
                            answer={vaultAnswers.choiceLabel || ''}
                          />
                          <div className="space-y-3 rounded-xl border border-border bg-background p-4">
                            <p className="text-[14px] font-semibold text-foreground">
                              {t('managed.quickstart.vaultNameQuestion')}
                            </p>
                            <input
                              type="text"
                              value={vaultName}
                              onChange={(e) => setVaultName(e.target.value)}
                              placeholder={t('managed.quickstart.vaultNamePlaceholder')}
                              className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-ring"
                            />
                            <div className="flex items-center justify-between">
                              <Button
                                className="h-9 rounded-xl px-4 text-sm"
                                disabled={isCreating || !vaultName.trim()}
                                onClick={() => {
                                  createVault(vaultName.trim())
                                  setVaultAnswers((prev) => ({
                                    ...prev,
                                    choiceLabel: vaultName.trim(),
                                  }))
                                  setVaultSubStep('selected')
                                }}
                              >
                                {isCreating ? (
                                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                                ) : null}
                                {t('managed.quickstart.createVault')}
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="text-xs text-muted-foreground"
                                onClick={handleVaultSkip}
                              >
                                {t('common.skip')}
                              </Button>
                            </div>
                          </div>
                        </>
                      )}
                    </>
                  )}

                {/* Step 6: Start Session confirmation */}
                {currentStep === 6 && !completedSteps.has(6) && (
                  <div className="space-y-3">
                    <p className="text-sm font-semibold text-foreground">
                      {t('managed.quickstart.readyToStart')}
                    </p>
                    <div className="space-y-1 rounded-lg border border-border bg-muted/50 p-3 font-mono text-xs">
                      <div>
                        <span className="text-muted-foreground">agent:</span>{' '}
                        {resourceIds[3] ? shortIdWithPrefix(resourceIds[3], 'agent_') : '—'}
                      </div>
                      {resourceIds[4] && (
                        <div>
                          <span className="text-muted-foreground">environment_id:</span>{' '}
                          {shortIdWithPrefix(resourceIds[4], 'env_')}
                        </div>
                      )}
                      {resourceIds[5] && (
                        <div>
                          <span className="text-muted-foreground">vault_ids:</span>{' '}
                          {`["${shortIdWithPrefix(resourceIds[5], 'vlt_')}"]`}
                        </div>
                      )}
                    </div>
                    <Button
                      className="h-10 rounded-xl px-5 text-sm"
                      disabled={isCreating || !resourceIds[3]}
                      onClick={createSession}
                    >
                      {isCreating ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                      {t('managed.quickstart.startSession')}
                    </Button>
                  </div>
                )}

                {completedSteps.has(currentStep) &&
                  curls[currentStep] &&
                  (currentStep >= 5 ||
                    (envSubStep !== 'selected' && vaultSubStep !== 'selected')) && (
                    <>
                      {currentStep === 6 ? (
                        <>
                          <StepDoneBadge
                            label={t('managed.quickstart.stepComplete.sessionStarted')}
                            curl={curls[6]}
                            endpoint={STEP_API_ENDPOINTS[6] || '/sessions'}
                          />
                          {trialRunStatus === 'idle' && (
                            <p className="mt-1 text-[13px] leading-6 text-muted-foreground">
                              {t('managed.quickstart.sessionLiveHint')}
                            </p>
                          )}
                          {trialRunStatus === 'testing' && (
                            <div className="mt-1 flex items-center gap-2 text-sm text-muted-foreground">
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              <span>{t('managed.quickstart.agentRunningHint')}</span>
                            </div>
                          )}
                          {trialRunStatus === 'success' && (
                            <>
                              <p className="text-[13px] leading-6 text-foreground/80">
                                {t('managed.quickstart.stepDesc.6')}
                              </p>
                            </>
                          )}
                        </>
                      ) : (
                        <StepCompleteCard
                          step={currentStep}
                          curl={curls[currentStep]}
                          endpoint={STEP_API_ENDPOINTS[currentStep] || '/unknown'}
                          onNext={advanceStep}
                          nextLabel={
                            currentStep === 3
                              ? t('managed.quickstart.nextConfigureEnv')
                              : currentStep === 4
                                ? t('managed.quickstart.nextConfigureVault')
                                : currentStep === 5
                                  ? t('managed.quickstart.nextStartSession')
                                  : t('common.done')
                          }
                        />
                      )}
                    </>
                  )}

                <div ref={messagesEndRef} />
              </div>

              <div className="absolute bottom-4 left-5 right-5 rounded-[14px] border border-border bg-background px-3 py-2.5 shadow-[0_8px_18px_rgba(15,23,42,0.06)]">
                <div className="flex items-center gap-2">
                  <input
                    ref={inputRef}
                    type="text"
                    value={inputValue}
                    onChange={(e) => setInputValue(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault()
                        handleSend()
                      }
                    }}
                    disabled={isMainInputDisabled}
                    placeholder={
                      !generationSecret?.secretRef
                        ? t('managed.quickstart.noApiKey')
                        : currentStep === 2
                          ? t('managed.quickstart.chooseSecret')
                          : currentStep >= 3 && !selectedSecretCompatible
                            ? t('managed.quickstart.noCompatibleSecret')
                            : isSessionRunning
                              ? t('managed.quickstart.agentProcessing')
                              : isStreaming
                                ? t('managed.quickstart.waitingForResponse')
                                : t('managed.quickstart.reply')
                    }
                    className="h-8 flex-1 border-0 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground disabled:opacity-50"
                  />
                  <button
                    onClick={handleSend}
                    disabled={isMainSendDisabled}
                    className={cn(
                      'inline-flex h-6 w-6 items-center justify-center rounded-md text-xs font-semibold text-primary-foreground shadow-sm transition-colors',
                      isMainSendDisabled
                        ? 'cursor-not-allowed bg-muted-foreground/30 text-white shadow-none'
                        : 'bg-primary hover:bg-primary/90',
                    )}
                    aria-label={t('managed.quickstart.sendMessage')}
                  >
                    &uarr;
                  </button>
                </div>
              </div>
            </section>

            {/* Right panel: config / preview */}
            <section className="relative bg-background">
              <div className="border-b border-border px-4 pt-2.5">
                <div className="flex items-end gap-5">
                  <button
                    className={cn(
                      'pb-2 text-sm font-semibold transition-colors',
                      rightTab === 'config'
                        ? 'border-b-2 border-foreground text-foreground'
                        : 'text-muted-foreground hover:text-foreground',
                    )}
                    onClick={() => setRightTab('config')}
                  >
                    {t('managed.quickstart.config')}
                  </button>
                  <button
                    className={cn(
                      'pb-2 text-sm font-semibold transition-colors',
                      rightTab === 'preview'
                        ? 'border-b-2 border-foreground text-foreground'
                        : 'text-muted-foreground hover:text-foreground',
                    )}
                    onClick={() => setRightTab('preview')}
                  >
                    {t('managed.quickstart.preview')}
                  </button>
                </div>
              </div>

              {rightTab === 'config' && (
                <>
                  <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
                    <div className="flex items-center gap-2 text-sm font-medium">
                      <button
                        onClick={() => setEditorTab('yaml')}
                        className={cn(
                          'rounded-xl px-3 py-1.5',
                          editorTab === 'yaml'
                            ? 'bg-muted text-foreground'
                            : 'text-muted-foreground',
                        )}
                      >
                        YAML
                      </button>
                      <button
                        onClick={() => setEditorTab('json')}
                        className={cn(
                          'rounded-xl px-3 py-1.5',
                          editorTab === 'json'
                            ? 'bg-muted text-foreground'
                            : 'text-muted-foreground',
                        )}
                      >
                        JSON
                      </button>
                    </div>
                    <button
                      className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                      aria-label={t('managed.quickstart.searchInConfig')}
                    >
                      <Search className="h-4 w-4" />
                    </button>
                  </div>
                  <div
                    ref={configScrollRef}
                    className="h-[calc(100vh-285px)] overflow-auto px-3 py-3"
                  >
                    <div className="font-mono text-[14px] leading-7">
                      {codeLines.map((line, i) => (
                        <div
                          key={`${i}-${line.slice(0, 16)}`}
                          className="grid grid-cols-[34px_minmax(0,1fr)] gap-3"
                        >
                          <span className="select-none text-right text-muted-foreground/80">
                            {i + 1}
                          </span>
                          <span className="whitespace-pre-wrap break-words text-foreground/95">
                            {line}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                </>
              )}

              {rightTab === 'preview' && (
                <div className="flex h-[calc(100vh-240px)] flex-col">
                  <div className="flex items-center justify-between border-b border-border px-4 py-3">
                    {isSessionActive ? (
                      <div className="min-w-0 text-xs text-muted-foreground">
                        {selectedEnvironmentName ? (
                          <>
                            {t('managed.quickstart.environment')}
                            <span className="ml-1 font-medium text-foreground">
                              {selectedEnvironmentName}
                            </span>
                          </>
                        ) : (
                          t('managed.quickstart.sessionLiveHint')
                        )}
                      </div>
                    ) : (
                      <Select value={selectedEnvId || undefined} onValueChange={setSelectedEnvId}>
                        <SelectTrigger className="w-[220px] max-w-[40vw]">
                          <SelectValue placeholder={t('managed.quickstart.selectEnv')} />
                        </SelectTrigger>
                        <SelectContent>
                          {activeEnvironments.map((env) => (
                            <SelectItem key={env.id} value={env.id}>
                              {env.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    )}
                    {isSessionActive ? (
                      <button
                        className="whitespace-nowrap text-xs text-primary hover:underline"
                        onClick={() => router.push(`/managed/sessions/${rawSessionId}`)}
                      >
                        {t('managed.quickstart.viewSession')} &uarr;
                      </button>
                    ) : null}
                  </div>

                  {isSessionActive ? (
                    <>
                      <TrialRunBanner
                        status={trialRunStatus}
                        onGoBack={() => goToStep(1 as StepId)}
                        onContinue={advanceStep}
                      />
                      <div className="flex items-center gap-3 border-b border-border px-4 py-2">
                        <button
                          onClick={() => {
                            setPreviewTab('transcript')
                            setSelectedPreviewEvent(null)
                          }}
                          className={cn(
                            'rounded px-2 py-0.5 text-xs font-semibold transition-colors',
                            previewTab === 'transcript'
                              ? 'bg-foreground text-background'
                              : 'text-muted-foreground hover:text-foreground',
                          )}
                        >
                          {t('managed.sessions.tab.transcript')}
                        </button>
                        <button
                          onClick={() => setPreviewTab('debug')}
                          className={cn(
                            'rounded px-2 py-0.5 text-xs font-semibold transition-colors',
                            previewTab === 'debug'
                              ? 'bg-foreground text-background'
                              : 'text-muted-foreground hover:text-foreground',
                          )}
                        >
                          {t('managed.sessions.tab.debug')}
                        </button>
                        <EventFilter
                          selected={
                            previewFilter.size > 0 ? previewFilter : new Set(previewAvailableTypes)
                          }
                          onChange={setPreviewFilter}
                          availableTypes={previewAvailableTypes}
                        />
                        <button
                          type="button"
                          className="text-muted-foreground transition-colors hover:text-foreground"
                          onClick={() => setShowPreviewSearch(!showPreviewSearch)}
                        >
                          <Search className="h-3.5 w-3.5" />
                        </button>
                      </div>
                      {showPreviewSearch && (
                        <div className="border-b border-border px-4 py-1.5">
                          <input
                            type="text"
                            value={previewSearch}
                            onChange={(e) => setPreviewSearch(e.target.value)}
                            placeholder={t('managed.quickstart.searchEvents')}
                            className="w-full bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
                            autoFocus
                          />
                        </div>
                      )}
                      <div className="flex-1 overflow-y-auto">
                        {selectedPreviewEvent ? (
                          <EventDetail
                            event={selectedPreviewEvent}
                            mode={previewTab}
                            sessionStart={
                              mergedSessionEvents[0]?.created_at || mergedSessionEvents[0]?.id || ''
                            }
                            onClose={() => setSelectedPreviewEvent(null)}
                          />
                        ) : mergedSessionEvents.length === 0 ? (
                          <div className="flex h-full flex-1 items-center justify-center py-12">
                            <p className="text-sm text-muted-foreground">
                              {t('managed.quickstart.noEventsYet')}
                            </p>
                          </div>
                        ) : (
                          <EventList
                            events={mergedSessionEvents}
                            sessionStart={
                              mergedSessionEvents[0]?.created_at || mergedSessionEvents[0]?.id || ''
                            }
                            selectedId={null}
                            onSelect={(evt) => {
                              setSelectedPreviewEvent(evt)
                              setPreviewTab('debug')
                            }}
                            mode={previewTab}
                          />
                        )}
                      </div>
                      <div className="border-t border-border px-4 py-3">
                        <div className="flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-2">
                          <input
                            type="text"
                            value={sessionMsgInput}
                            onChange={(e) => setSessionMsgInput(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter' && !e.shiftKey) {
                                e.preventDefault()
                                handleSendSessionMessage()
                              }
                            }}
                            disabled={isSendingMsg}
                            placeholder={
                              isSessionRunning
                                ? t('managed.quickstart.agentProcessing')
                                : t('managed.quickstart.sendMessage')
                            }
                            className="flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
                          />
                          {isSessionRunning ? (
                            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                          ) : (
                            <button
                              onClick={handleSendSessionMessage}
                              disabled={isSendingMsg || !sessionMsgInput.trim()}
                              className={cn(
                                'inline-flex h-6 w-6 items-center justify-center rounded-md text-xs font-semibold text-primary-foreground shadow-sm transition-colors',
                                isSendingMsg || !sessionMsgInput.trim()
                                  ? 'cursor-not-allowed bg-muted-foreground/30 text-white shadow-none'
                                  : 'bg-primary hover:bg-primary/90',
                              )}
                            >
                              &uarr;
                            </button>
                          )}
                        </div>
                      </div>
                    </>
                  ) : (
                    <div className="flex flex-1 flex-col items-center justify-center gap-4 px-6 text-center">
                      <p className="max-w-[320px] text-sm text-muted-foreground">
                        {t('managed.quickstart.selectEnvPrompt')}
                      </p>
                      <Button
                        variant="outline"
                        size="sm"
                        className="gap-1.5"
                        disabled={!resourceIds[3] || isTestRunning}
                        onClick={handleTestRun}
                      >
                        {isTestRunning ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Play className="h-3.5 w-3.5" />
                        )}
                        {t('managed.quickstart.testRun')}
                      </Button>
                    </div>
                  )}
                </div>
              )}
            </section>
          </div>
        </div>
      )}
    </div>
  )
}
