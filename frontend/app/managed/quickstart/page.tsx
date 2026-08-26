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
  ClipboardCheck,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  isQuickstartCompletionStep,
  QuickstartCompletionDescription,
  QuickstartCompletionTitle,
  type QuickstartCompletionStep,
} from './components/quickstart-completion-copy'
import { QuickstartAgentBlueprintReview } from './components/quickstart-agent-blueprint'
import { QuickstartCapabilityEvidence } from './components/quickstart-capability-evidence'
import { QuickstartGenerationStatus } from './components/quickstart-generation-status'
import { QuickstartLlmStep } from './components/quickstart-llm-step'
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
import { ApiError, managedGet, managedPost } from '@/lib/api-client'
import { apiResourceId, apiResourcePath, apiResourceSubpath } from '@/lib/managed/api-paths'
import { toastOperationError } from '@/lib/managed/errors'
import {
  hasManagedRequestScope,
  managedRequestOptions,
  managedScopeKey,
  type ManagedRequestScope,
  useManagedRequestScope,
} from '@/lib/managed/request-scope'
import { shortEntityId } from '@/lib/managed/entity-id-display'
import { getEnabledEngines } from '@/lib/managed/llm-catalog'
import {
  recommendQuickstartModelConnection,
  type QuickstartModelRecommendationReason,
} from '@/lib/managed/quickstart-model-recommendation'
import {
  normalizeQuickstartAllowedHosts,
  recommendQuickstartSafetyDefaults,
} from '@/lib/managed/quickstart-safety-recommendation'
import { useLlmCatalog } from '@/hooks/managed/use-llm-catalog'
import { generateUUID } from '@/lib/utils/uuid'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useSessionStream } from '@/lib/managed/sse'
import { useRouter } from 'next/navigation'
import type {
  Agent,
  Environment,
  PaginatedResponse,
  QuickstartTaskSummary,
  Credential,
  CredentialDetail,
  Session,
  SessionEvent,
  CredentialGroup,
  SkillRecord,
} from '@/types/managed'
import { EventList, EventDetail, EventFilter } from '@/components/managed/session'
import yaml from 'js-yaml'
import { useProjectStore } from '@/stores/managed/project-store'
import {
  parseAgentId,
  parseEnvironmentId,
  parseSessionId,
  tryParseAgentId,
  tryParseEnvironmentId,
  tryParseCredentialGroupId,
  type SessionId,
  type CredentialGroupId,
} from '@/types/entity-id'
import { parseEnvironmentListResponse } from '@/lib/managed/environment-response-parsers'
import {
  parseCredentialGroupCredentialListResponse,
  parseCredentialGroupListResponse,
} from '@/lib/managed/credential-group-response-parsers'
import { quickstartQueryOptions } from '@/lib/managed/quickstart-query-options'
import { quickstartInputPlaceholderKey } from '@/lib/managed/quickstart-input-state'
import { validateUrlScheme } from '@/lib/utils/url-validation'
import { parseQuickstartTaskPage } from '@/lib/managed/quickstart-task-response-parsers'
import {
  deriveQuickstartTrialStatus,
  type QuickstartTrialStatus,
} from '@/lib/managed/quickstart-trial-status'
import {
  parseSessionCreateResponse,
  parseSessionResponse,
} from '@/lib/managed/session-response-parsers'
import {
  currentProjectAllowsWrite,
  useCurrentProjectReadOnly,
} from '@/hooks/managed/use-current-project-read-only'
import {
  useActiveModelConnections,
  compatibleCredentialsQueryPrefix,
  useCompatibleCredentials,
} from '@/hooks/managed/use-compatible-credentials'
import { buildQuickstartEngineOptions } from '@/lib/managed/quickstart-engine-recommendation'
import { deriveQuickstartLaunchAssurance } from '@/lib/managed/quickstart-launch-assurance'
import { normalizeQuickstartAgentBlueprint } from '@/lib/managed/quickstart-agent-blueprint'
import { deriveQuickstartOutcomes } from '@/lib/managed/quickstart-outcomes'
import {
  deriveQuickstartCapabilityEvidence,
  isMcpServerAuthorized,
  quickstartAuthorizedMcpServerUrls,
  quickstartConfiguredSkillNames,
  toQuickstartAvailableSkills,
} from '@/lib/managed/quickstart-capabilities'
import { quickstartCredentialGroupRecommendation } from '@/lib/managed/quickstart-credential-group-recommendation'
import { deriveQuickstartObservableChecks } from '@/lib/managed/quickstart-acceptance-checks'
import { parseSkillResponse } from '@/lib/managed/skill-response-parsers'

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

const QUICKSTART_SECURITY_HIGHLIGHTS = [
  {
    icon: Shield,
    titleKey: 'managed.quickstart.safety.sandbox.title',
    descriptionKey: 'managed.quickstart.safety.sandbox.description',
  },
  {
    icon: Database,
    titleKey: 'managed.quickstart.safety.credentials.title',
    descriptionKey: 'managed.quickstart.safety.credentials.description',
  },
  {
    icon: CheckCircle2,
    titleKey: 'managed.quickstart.safety.permissions.title',
    descriptionKey: 'managed.quickstart.safety.permissions.description',
  },
  {
    icon: FileText,
    titleKey: 'managed.quickstart.safety.audit.title',
    descriptionKey: 'managed.quickstart.safety.audit.description',
  },
]

const MODEL_RECOMMENDATION_REASON_KEYS: Record<QuickstartModelRecommendationReason, string> = {
  onlyCompatible: 'managed.quickstart.modelRecommendation.reason.onlyCompatible',
  preferredProtocolDefault:
    'managed.quickstart.modelRecommendation.reason.preferredProtocolDefault',
  protocolDefault: 'managed.quickstart.modelRecommendation.reason.protocolDefault',
  preferredProtocol: 'managed.quickstart.modelRecommendation.reason.preferredProtocol',
  recentCompatible: 'managed.quickstart.modelRecommendation.reason.recentCompatible',
}

const TEMPLATE_META: Record<string, { categoryKey: string; badgeKey: string }> = {
  blank: {
    categoryKey: 'managed.quickstart.templateCategory.basic',
    badgeKey: 'managed.quickstart.templateBadge.basic',
  },
  researcher: {
    categoryKey: 'managed.quickstart.templateCategory.research',
    badgeKey: 'managed.quickstart.templateBadge.web',
  },
  extractor: {
    categoryKey: 'managed.quickstart.templateCategory.data',
    badgeKey: 'managed.quickstart.templateBadge.data',
  },
  monitor: {
    categoryKey: 'managed.quickstart.templateCategory.ops',
    badgeKey: 'managed.quickstart.templateBadge.alert',
  },
  support: {
    categoryKey: 'managed.quickstart.templateCategory.service',
    badgeKey: 'managed.quickstart.templateBadge.chat',
  },
  incident: {
    categoryKey: 'managed.quickstart.templateCategory.ops',
    badgeKey: 'managed.quickstart.templateBadge.workflow',
  },
  feedback: {
    categoryKey: 'managed.quickstart.templateCategory.data',
    badgeKey: 'managed.quickstart.templateBadge.insight',
  },
  retro: {
    categoryKey: 'managed.quickstart.templateCategory.service',
    badgeKey: 'managed.quickstart.templateBadge.meeting',
  },
  escalator: {
    categoryKey: 'managed.quickstart.templateCategory.service',
    badgeKey: 'managed.quickstart.templateBadge.workflow',
  },
  analyst: {
    categoryKey: 'managed.quickstart.templateCategory.data',
    badgeKey: 'managed.quickstart.templateBadge.report',
  },
}

const TEMPLATE_BASE_CONFIGS: Record<string, Record<string, unknown>> = {
  blank: {
    name: 'Blank Agent',
    description: 'A minimal general-purpose agent configuration.',
    system:
      'You are a helpful assistant. Clarify the user goal, plan briefly, and complete the task safely and accurately.',
    tools: [],
    metadata: { quickstart_template: 'blank' },
  },
  researcher: {
    name: 'Deep Researcher',
    description: 'Research topics in depth and produce concise, sourced summaries.',
    system:
      'You are a deep research agent. Break down the research question, gather relevant information, compare sources, identify uncertainties, and produce a structured answer with concise citations or source notes when available.',
    tools: [{ type: 'agent_toolset_20260401' }],
    metadata: { quickstart_template: 'researcher' },
  },
  extractor: {
    name: 'Structured Extractor',
    description: 'Extract structured data from unstructured text.',
    system:
      'You extract structured data from unstructured input. Preserve source meaning, avoid inventing missing fields, and return clean JSON or tables that match the requested schema.',
    tools: [{ type: 'agent_toolset_20260401' }],
    metadata: { quickstart_template: 'extractor' },
  },
  monitor: {
    name: 'Site Monitor',
    description: 'Monitor data sources and summarize changes or alerts.',
    system:
      'You are a monitoring agent. Check the configured sources, detect meaningful changes, classify severity, and produce clear alerts with recommended next actions.',
    tools: [{ type: 'agent_toolset_20260401' }],
    metadata: { quickstart_template: 'monitor' },
  },
  support: {
    name: 'Customer Support Agent',
    description: 'Handle support conversations with clear troubleshooting steps.',
    system:
      'You are a customer support agent. Be empathetic, ask focused clarifying questions, troubleshoot step by step, and summarize the resolution or escalation path.',
    tools: [{ type: 'agent_toolset_20260401' }],
    metadata: { quickstart_template: 'support' },
  },
  incident: {
    name: 'Incident Commander',
    description: 'Coordinate incident response workflows.',
    system:
      'You are an incident commander. Establish impact, timeline, owners, mitigation, communication updates, and post-incident follow-up. Keep responses action-oriented and time-aware.',
    tools: [{ type: 'agent_toolset_20260401' }],
    metadata: { quickstart_template: 'incident' },
  },
  feedback: {
    name: 'Feedback Miner',
    description: 'Analyze user feedback for themes and insights.',
    system:
      'You analyze user feedback. Cluster comments into themes, extract representative examples, estimate impact, and propose prioritized product actions.',
    tools: [{ type: 'agent_toolset_20260401' }],
    metadata: { quickstart_template: 'feedback' },
  },
  retro: {
    name: 'Sprint Retro Host',
    description: 'Host retrospectives and record action items.',
    system:
      'You facilitate sprint retrospectives. Collect wins, pain points, root causes, action items, owners, and follow-up dates. Keep the discussion balanced and constructive.',
    tools: [{ type: 'agent_toolset_20260401' }],
    metadata: { quickstart_template: 'retro' },
  },
  escalator: {
    name: 'Support to Engineering',
    description: 'Triage and escalate support tickets to engineering teams.',
    system:
      'You triage support tickets for engineering. Reproduce the issue from available evidence, classify severity, identify affected systems, and write a concise engineering-ready escalation.',
    tools: [{ type: 'agent_toolset_20260401' }],
    metadata: { quickstart_template: 'escalator' },
  },
  analyst: {
    name: 'Data Analyst',
    description: 'Analyze datasets and generate reports.',
    system:
      'You are a data analyst. Inspect data quality, compute relevant summaries, identify trends or anomalies, and produce clear recommendations with assumptions stated.',
    tools: [{ type: 'agent_toolset_20260401' }],
    metadata: { quickstart_template: 'analyst' },
  },
}

const TEMPLATE_ACCEPTANCE_MESSAGES: Record<string, string> = {
  blank: 'Help me turn this goal into a clear plan: prepare a product launch checklist.',
  researcher: 'Research the main tradeoffs of adopting passkeys for a B2B SaaS product.',
  extractor:
    'Extract the customer, issue, severity, and requested resolution from this support note.',
  monitor: 'Compare the latest source state with the prior snapshot and report meaningful changes.',
  support:
    'A customer cannot sign in after enabling MFA. Diagnose the issue and propose next steps.',
  incident: 'Coordinate the first 15 minutes of an API outage affecting checkout.',
  feedback: 'Analyze these customer comments and prioritize the top product opportunities.',
  retro: 'Run a retrospective for a sprint that missed its release target.',
  escalator: 'Turn this intermittent login failure into an engineering-ready escalation.',
  analyst: 'Analyze this dataset summary and recommend the next decision with assumptions stated.',
}

const TEMPLATE_PROFILES: Record<
  string,
  {
    runtimeIntent: string
    safetyPosture: { environment: 'optional' | 'recommended'; network: 'closed' | 'limited' }
  }
> = {
  blank: {
    runtimeIntent: 'general',
    safetyPosture: { environment: 'optional', network: 'closed' },
  },
  researcher: {
    runtimeIntent: 'web_research',
    safetyPosture: { environment: 'recommended', network: 'limited' },
  },
  extractor: {
    runtimeIntent: 'structured_data',
    safetyPosture: { environment: 'optional', network: 'closed' },
  },
  monitor: {
    runtimeIntent: 'monitoring',
    safetyPosture: { environment: 'recommended', network: 'limited' },
  },
  support: {
    runtimeIntent: 'customer_support',
    safetyPosture: { environment: 'optional', network: 'closed' },
  },
  incident: {
    runtimeIntent: 'incident_response',
    safetyPosture: { environment: 'recommended', network: 'limited' },
  },
  feedback: {
    runtimeIntent: 'feedback_analysis',
    safetyPosture: { environment: 'optional', network: 'closed' },
  },
  retro: {
    runtimeIntent: 'facilitation',
    safetyPosture: { environment: 'optional', network: 'closed' },
  },
  escalator: {
    runtimeIntent: 'support_escalation',
    safetyPosture: { environment: 'recommended', network: 'limited' },
  },
  analyst: {
    runtimeIntent: 'data_analysis',
    safetyPosture: { environment: 'recommended', network: 'limited' },
  },
}

const TEMPLATE_CONFIGS: Record<string, Record<string, unknown>> = Object.fromEntries(
  Object.entries(TEMPLATE_BASE_CONFIGS).map(([templateId, config]) => {
    const description = typeof config.description === 'string' ? config.description : ''
    const profile = TEMPLATE_PROFILES[templateId] || TEMPLATE_PROFILES.blank
    // Templates are generic starters, NOT tailored professional blueprints: only
    // ship the fields that are genuinely template-specific (mission + a realistic
    // acceptance test). The rest of the blueprint is left for the user to refine in
    // chat rather than fabricating identical filler for every template.
    return [
      templateId,
      {
        ...config,
        metadata: {
          ...(typeof config.metadata === 'object' && config.metadata ? config.metadata : {}),
          quickstart_runtime_intent: profile.runtimeIntent,
          quickstart_safety_posture: JSON.stringify({
            ...profile.safetyPosture,
            externalTools: 'not_authorized',
          }),
        },
        blueprint: {
          mission: description,
          acceptance_test: {
            message: TEMPLATE_ACCEPTANCE_MESSAGES[templateId] || 'Complete a representative task.',
            checks: [
              'Follows the declared workflow and boundaries.',
              'Produces the promised output format without inventing evidence.',
            ],
          },
        },
      },
    ]
  }),
)

const STEP_API_ENDPOINTS: Record<number, string> = {
  3: '/agents',
  4: '/environments',
  5: '/credential-groups',
  6: '/sessions',
}

type ActiveCredentialGroupsCache = { data?: CredentialGroup[] } | CredentialGroup[]

function unwrapActiveCredentialGroupsCache(value: ActiveCredentialGroupsCache | undefined) {
  if (!value) return undefined
  return Array.isArray(value) ? value : value.data || []
}

function SafetyPlanStatusBadge({
  tone,
  label,
}: {
  tone: 'ready' | 'warning' | 'muted' | 'primary'
  label: string
}) {
  const Icon = tone === 'warning' ? AlertTriangle : tone === 'muted' ? Shield : CheckCircle2
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold',
        tone === 'ready' && 'border-emerald-200 bg-emerald-50 text-emerald-700',
        tone === 'warning' && 'border-amber-200 bg-amber-50 text-amber-700',
        tone === 'muted' && 'border-border bg-muted text-muted-foreground',
        tone === 'primary' && 'border-primary/20 bg-primary/10 text-primary',
      )}
    >
      <Icon className="h-3 w-3" />
      {label}
    </span>
  )
}

function getCurrentManagedScope() {
  const { currentOrgId, currentProjectId } = useProjectStore.getState()
  return managedScopeKey(currentOrgId, currentProjectId)
}

// -- Stepper ----------------------------------------------------------------

function Stepper({
  currentStep,
  completedSteps,
  skippedSteps,
  trialStatus,
}: {
  currentStep: StepId
  completedSteps: Set<number>
  skippedSteps: Set<number>
  trialStatus: QuickstartTrialStatus
}) {
  const { t } = useTranslation()
  const outcomes = deriveQuickstartOutcomes({
    currentStep,
    completedSteps,
    skippedSteps,
    trialStatus,
  })

  return (
    <nav
      aria-label={t('managed.quickstart.outcome.navigationLabel')}
      className="mb-2 flex items-center justify-center gap-3 py-2"
    >
      {outcomes.map((outcome, index) => {
        const isDone = outcome.status === 'complete'
        const hasGaps = outcome.status === 'complete_with_gaps'
        const isActive = outcome.status === 'active'

        return (
          <div key={outcome.id} className="flex items-center gap-3">
            {index > 0 && <span className="text-muted-foreground/50">→</span>}
            <div className="flex items-center gap-2 whitespace-nowrap">
              <span
                className={cn(
                  'flex h-6 w-6 items-center justify-center rounded-full border text-[11px] font-semibold',
                  isDone && 'border-green-500 bg-green-500 text-white',
                  hasGaps && 'border-amber-500 bg-amber-500/10 text-amber-700',
                  isActive && !isDone && !hasGaps && 'border-primary bg-primary/10 text-primary',
                  !isDone && !hasGaps && !isActive && 'border-border text-muted-foreground',
                )}
              >
                {isDone ? (
                  <Check className="h-3 w-3" />
                ) : hasGaps ? (
                  <AlertTriangle className="h-3 w-3" />
                ) : (
                  outcome.ordinal
                )}
              </span>
              <span
                className={cn(
                  'text-sm font-medium',
                  isActive
                    ? 'text-foreground'
                    : isDone || hasGaps
                      ? 'text-foreground'
                      : 'text-muted-foreground',
                )}
              >
                {t(`managed.quickstart.outcome.${outcome.id}.title`)}
              </span>
              {hasGaps ? (
                <span className="rounded-full bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700">
                  {t('managed.quickstart.outcome.reviewedWithGaps')}
                </span>
              ) : null}
            </div>
          </div>
        )
      })}
    </nav>
  )
}

// -- ApiCard ----------------------------------------------------------------

function ApiCard({ endpoint, curl }: { endpoint: string; curl: string }) {
  const [copied, setCopied] = useState(false)
  const copiedResetTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(
    () => () => {
      if (copiedResetTimerRef.current) {
        clearTimeout(copiedResetTimerRef.current)
      }
    },
    [],
  )

  const showCopiedFeedback = () => {
    if (copiedResetTimerRef.current) {
      clearTimeout(copiedResetTimerRef.current)
    }
    setCopied(true)
    copiedResetTimerRef.current = setTimeout(() => {
      setCopied(false)
      copiedResetTimerRef.current = null
    }, 2000)
  }

  const handleCopy = () => {
    navigator.clipboard.writeText(curl)
    showCopiedFeedback()
  }

  return (
    <div className="rounded-xl border border-border bg-background">
      <div className="flex items-center justify-between border-b border-border px-3 py-2 text-xs">
        <div className="flex items-center gap-2">
          <span className="rounded bg-muted px-1.5 py-0.5 font-semibold text-blue-600 dark:text-blue-400">
            POST
          </span>
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
  step: QuickstartCompletionStep
  curl: string
  endpoint: string
  onNext: () => void
  nextLabel: string
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
        <CheckCircle2 className="h-4 w-4 text-muted-foreground" />
        <QuickstartCompletionTitle step={step} />
      </div>
      <ApiCard endpoint={endpoint} curl={curl} />
      <QuickstartCompletionDescription
        step={step}
        className="text-[13px] leading-6 text-foreground/80"
      />
      <Button className="h-10 rounded-xl px-4 text-sm" onClick={onNext}>
        {nextLabel}
      </Button>
    </div>
  )
}

// -- TemplateCard -----------------------------------------------------------

function TemplateCard({
  templateId,
  onClick,
  disabled = false,
}: {
  templateId: string
  onClick: () => void
  disabled?: boolean
}) {
  const { t } = useTranslation()
  const Icon = TEMPLATE_ICONS[templateId] || FileText
  const meta = TEMPLATE_META[templateId]
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={cn(
        'group relative flex min-h-[104px] items-start gap-3 rounded-2xl border border-border bg-background p-4 text-left shadow-sm transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:bg-muted/30 hover:shadow-md focus:outline-none focus:ring-2 focus:ring-ring',
        disabled && 'cursor-not-allowed opacity-60 hover:bg-background',
      )}
    >
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-muted transition-colors group-hover:bg-primary/10">
        <Icon className="h-5 w-5 text-muted-foreground transition-colors group-hover:text-primary" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          <div className="truncate text-[14px] font-semibold text-foreground">
            {t(`quickstart.template.${templateId}.name`)}
          </div>
          {meta && (
            <span className="shrink-0 rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">
              {t(meta.badgeKey)}
            </span>
          )}
        </div>
        <div className="mt-0.5 text-[13px] leading-5 text-muted-foreground">
          {t(`quickstart.template.${templateId}.description`)}
        </div>
        <div className="mt-2 flex items-start gap-1.5 rounded-lg bg-muted/40 px-2 py-1.5 text-[11px] leading-4 text-muted-foreground">
          <Shield className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{t('managed.quickstart.templateSecurityHint')}</span>
        </div>
        <div className="mt-2 flex items-center justify-between gap-2 text-[12px]">
          <span className="text-muted-foreground">
            {meta ? t(meta.categoryKey) : t('managed.quickstart.templateCategory.basic')}
          </span>
          <span className="font-medium text-primary opacity-0 transition-opacity group-hover:opacity-100">
            {t('managed.quickstart.useTemplate')}
          </span>
        </div>
      </div>
    </button>
  )
}

// -- NumberedChoiceList ------------------------------------------------------

function NumberedChoiceList({
  question,
  hint,
  choices,
  onSelect,
  onSkip,
}: {
  question: string
  hint?: string
  choices: { num: number; label: string; arrow?: boolean }[]
  onSelect: (num: number) => void
  onSkip?: () => void
}) {
  const { t } = useTranslation()
  return (
    <div className="rounded-xl border border-border bg-background p-4">
      <p className="mb-1 text-[14px] font-semibold text-foreground">{question}</p>
      {hint ? <p className="text-xs leading-5 text-muted-foreground">{hint}</p> : null}
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
  onRetry,
  onViewSession,
}: {
  status: QuickstartTrialStatus
  onGoBack: () => void
  onContinue: () => void
  onRetry: () => void
  onViewSession: () => void
}) {
  const { t } = useTranslation()
  if (status === 'idle') return null

  return (
    <div
      className={cn(
        'flex items-center gap-3 border-b border-border px-4 py-2.5 text-sm',
        status === 'testing' && 'bg-blue-50 dark:bg-blue-950/20',
        status === 'response_received' && 'bg-sky-50 dark:bg-sky-950/20',
        (status === 'error' || status === 'access_rejected') && 'bg-amber-50 dark:bg-amber-950/20',
        status === 'runtime_unavailable' && 'bg-red-50 dark:bg-red-950/20',
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
      {status === 'response_received' && (
        <>
          <ClipboardCheck className="h-4 w-4 text-sky-600" />
          <span className="text-sky-700 dark:text-sky-300">
            {t('managed.quickstart.trialRun.responseReceived')}
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
      {status === 'access_rejected' && (
        <>
          <Shield className="h-4 w-4 text-amber-600" />
          <span className="text-amber-800 dark:text-amber-300">
            {t('managed.quickstart.trialRun.accessRejected')}
          </span>
          <div className="ml-auto flex items-center gap-2">
            <Button variant="outline" size="sm" className="text-xs" onClick={onGoBack}>
              {t('managed.quickstart.trialRun.reviewControls')}
            </Button>
            <Button variant="ghost" size="sm" className="text-xs" onClick={onViewSession}>
              {t('managed.quickstart.trialRun.viewSession')}
            </Button>
          </div>
        </>
      )}
      {status === 'runtime_unavailable' && (
        <>
          <AlertTriangle className="h-4 w-4 text-red-500" />
          <span className="text-red-700 dark:text-red-400">
            {t('managed.quickstart.trialRun.runtimeUnavailable')}
          </span>
          <div className="ml-auto flex items-center gap-2">
            <Button variant="outline" size="sm" className="text-xs" onClick={onRetry}>
              {t('managed.quickstart.trialRun.checkAgain')}
            </Button>
            <Button variant="ghost" size="sm" className="text-xs" onClick={onViewSession}>
              {t('managed.quickstart.trialRun.viewSession')}
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
  const currentProjectReadOnly = useCurrentProjectReadOnly()
  const managedScope = useManagedRequestScope()
  const catalogQuery = useLlmCatalog()
  const enabledEngines = useMemo(
    () => (catalogQuery.data ? getEnabledEngines(catalogQuery.data) : []),
    [catalogQuery.data],
  )
  const catalogEngines = useMemo(
    () => catalogQuery.data?.engines ?? enabledEngines,
    [catalogQuery.data, enabledEngines],
  )
  const [editorTab, setEditorTab] = useState<'yaml' | 'json'>('yaml')
  const [rightTab, setRightTab] = useState<'blueprint' | 'advanced' | 'preview'>('blueprint')
  const [secretRef, setSecretRef] = useState('')
  const [secretSelectionCleared, setSecretSelectionCleared] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const configScrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const [inputValue, setInputValue] = useState('')
  const [pendingEngineRecommendation, setPendingEngineRecommendation] = useState<{
    intent: string
    engineId: QuickstartEngine
  } | null>(null)
  const [templateSearch, setTemplateSearch] = useState('')
  const [selectedEnvId, setSelectedEnvId] = useState<string>('')
  const [localSessionId, setLocalSessionId] = useState<SessionId | null>(null)
  const [isTestRunning, setIsTestRunning] = useState(false)
  const [isStoppingSession, setIsStoppingSession] = useState(false)
  const [previewTab, setPreviewTab] = useState<'transcript' | 'debug'>('debug')
  const [previewFilter, setPreviewFilter] = useState<Set<string>>(new Set())
  const [previewSearch, setPreviewSearch] = useState('')
  const [showPreviewSearch, setShowPreviewSearch] = useState(false)
  const [selectedPreviewEvent, setSelectedPreviewEvent] = useState<SessionEvent | null>(null)
  const autoIntroSentRef = useRef<Set<number>>(new Set())
  const managedScopeRef = useRef(managedScope.key)
  const managedRequestScopeRef = useRef<ManagedRequestScope>(managedScope)
  const pageActionRunRef = useRef(0)

  // Sub-step state for the environment inline flow
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

  // Sub-step state for the vault inline flow
  const [vaultSubStep, setVaultSubStep] = useState<'choose' | 'name' | 'selected' | null>('choose')
  const [vaultUsesAI, setVaultUsesAI] = useState(false)
  const [vaultAnswers, setVaultAnswers] = useState<{ choiceLabel?: string }>({})
  const [vaultName, setVaultName] = useState('')
  const [vaultCredentialName, setVaultCredentialName] = useState('')
  const [vaultMcpServerUrl, setVaultMcpServerUrl] = useState('')
  const [vaultTokenValue, setVaultTokenValue] = useState('')
  const [pendingVaultId, setPendingVaultId] = useState<CredentialGroupId | null>(null)

  useEffect(() => {
    if (managedScopeRef.current === managedScope.key) return
    managedScopeRef.current = managedScope.key
    managedRequestScopeRef.current = managedScope
    pageActionRunRef.current += 1
    setSelectedEnvId('')
    setSecretRef('')
    setSecretSelectionCleared(false)
    setPendingEngineRecommendation(null)
    setLocalSessionId(null)
    setIsTestRunning(false)
    setIsStoppingSession(false)
    sessionMsgDraftVersionRef.current += 1
    sessionMsgInputRef.current = ''
    setSessionMsgInput('')
    setIsSendingMsg(false)
    setSelectedPreviewEvent(null)
    setPreviewFilter(new Set())
    setPreviewSearch('')
    setShowPreviewSearch(false)
    setPendingEnvId(null)
    setPendingVaultId(null)
    setEnvSubStep('choose')
    setEnvUsesAI(false)
    setEnvAnswers({})
    setEnvHosts('')
    setVaultSubStep('choose')
    setVaultUsesAI(false)
    setVaultAnswers({})
    setVaultName('')
    setVaultCredentialName('')
    setVaultMcpServerUrl('')
    setVaultTokenValue('')
    autoIntroSentRef.current = new Set()
  }, [managedScope.key])

  const nextPageAction = () => {
    const runId = pageActionRunRef.current + 1
    pageActionRunRef.current = runId
    return { runId, scope: managedScopeRef.current }
  }

  const isCurrentPageAction = (runId: number, scope: string) =>
    pageActionRunRef.current === runId &&
    managedScopeRef.current === scope &&
    getCurrentManagedScope() === scope

  const currentPageScopeIsActive = () => getCurrentManagedScope() === managedScopeRef.current
  const currentPageProjectAllowsWrite = () =>
    currentPageScopeIsActive() && currentProjectAllowsWrite()

  const { data: environments } = useQuery(
    quickstartQueryOptions({
      queryKey: ['environments-active', managedScope.key],
      queryFn: async () => {
        const res = await managedGet<PaginatedResponse<Environment>>(
          '/environments',
          managedRequestOptions(managedScope),
        )
        return parseEnvironmentListResponse(res.data || [])
      },
      enabled: hasManagedRequestScope(managedScope),
    }),
  )

  const { data: vaultsRes } = useQuery(
    quickstartQueryOptions({
      queryKey: ['credential-groups-active', managedScope.key],
      queryFn: () =>
        managedGet<{ data: unknown[] }>(
          '/credential-groups',
          managedRequestOptions(managedScope),
        ).then((response) => ({
          ...response,
          data: parseCredentialGroupListResponse(response.data),
        })),
      enabled: hasManagedRequestScope(managedScope),
    }),
  )
  const vaults = vaultsRes?.data

  const { data: skillRecords } = useQuery(
    quickstartQueryOptions({
      queryKey: ['skills', managedScope.key],
      queryFn: async () => {
        const response = await managedGet<{ data: unknown[] }>(
          '/skills',
          managedRequestOptions(managedScope),
        )
        return (response.data || []).map(parseSkillResponse) as SkillRecord[]
      },
      enabled: hasManagedRequestScope(managedScope),
    }),
  )
  const availableSkills = useMemo(
    () => toQuickstartAvailableSkills(skillRecords || []),
    [skillRecords],
  )

  const {
    messages,
    currentStep,
    selectedEngine,
    config,
    isStreaming,
    generationState,
    curls,
    resourceIds,
    createdResourceIds = new Set<string>(),
    completedSteps,
    skippedSteps,
    pendingConfirmation,
    isCreating,
    sendMessage,
    cancelGeneration,
    retryGeneration,
    applyTemplate,
    selectEngine,
    selectAgentSecret,
    advanceStep,
    skipStep,
    setAgentSkills,
    confirmStep,
    keepRefining,
    createSession,
    createEnvironment,
    selectExistingEnvironment,
    createCredentialGroup,
    selectExistingCredentialGroup,
    goToStep,
    reopenStep,
    sendAutoIntro,
    generateTestMessage,
  } = useQuickstartChat(secretRef, { availableSkills })

  const compatibleSecretsQuery = useCompatibleCredentials({
    engineId: selectedEngine ?? '',
    enabled: Boolean(selectedEngine),
  })
  const compatibleSecrets = compatibleSecretsQuery.data
  const activeModelConnectionsQuery = useActiveModelConnections()
  const activeModelConnections = activeModelConnectionsQuery.data ?? []

  const selectedSecret = useMemo(() => {
    return compatibleSecrets?.find((secret) => secret.id === secretRef)
  }, [compatibleSecrets, secretRef])

  const selectedSecretCompatible = Boolean(selectedSecret)
  const hasQuickstartIntent = useMemo(
    () => messages.some((message) => message.role === 'user') || Boolean(config.agent),
    [config.agent, messages],
  )
  const selectedEngineCapability = useMemo(
    () => enabledEngines.find((engine) => engine.id === selectedEngine) ?? null,
    [enabledEngines, selectedEngine],
  )
  const modelRecommendation = useMemo(
    () => recommendQuickstartModelConnection(compatibleSecrets ?? [], selectedEngineCapability),
    [compatibleSecrets, selectedEngineCapability],
  )
  const safetyRecommendation = useMemo(
    () =>
      recommendQuickstartSafetyDefaults({
        messages,
        agentConfig: config.agent,
      }),
    [config.agent, messages],
  )
  const suggestedAllowlist = safetyRecommendation.recommendedHosts.join(', ')
  const suggestedMcpServerUrl = safetyRecommendation.recommendedMcpServerUrls[0] || ''

  useEffect(() => {
    if (!selectedEngine || !compatibleSecretsQuery.isSuccess || !compatibleSecrets) return
    const compatibleIds = new Set<string>(compatibleSecrets.map((secret) => secret.id))
    if (secretRef) {
      if (compatibleIds.has(secretRef)) return
      setSecretRef('')
      setSecretSelectionCleared(true)
      return
    }
    if (secretSelectionCleared) return
    if (modelRecommendation) {
      const recommendedId = modelRecommendation.secret.id
      setSecretRef(recommendedId)
      if (hasQuickstartIntent && modelRecommendation.autoContinue) {
        selectAgentSecret(recommendedId)
      }
    }
  }, [
    compatibleSecrets,
    compatibleSecretsQuery.isSuccess,
    hasQuickstartIntent,
    modelRecommendation,
    secretRef,
    secretSelectionCleared,
    selectAgentSecret,
    selectedEngine,
  ])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const isLanding = messages.length === 0 && !isStreaming
  const quickstartAgentId = tryParseAgentId(resourceIds[3])
  const quickstartEnvironmentId = tryParseEnvironmentId(resourceIds[4])
  const quickstartVaultId = tryParseCredentialGroupId(resourceIds[5])
  const rawSessionId = resourceIds[6] || localSessionId
  const sessionId = rawSessionId ? parseSessionId(rawSessionId) : null
  const isSessionActive = !!sessionId

  // Real MCP authorization: a credential group only authorizes an agent's MCP
  // server when it actually holds a member credential for that server URL.
  const { data: quickstartVaultMembers } = useQuery({
    queryKey: ['credential-group-members', managedScope.key, quickstartVaultId],
    queryFn: () =>
      managedGet<{ data: unknown[] }>(
        apiResourceSubpath('credential-groups', quickstartVaultId!, ['members'], { limit: 100 }),
        managedRequestOptions(managedScope),
      ).then((response) => parseCredentialGroupCredentialListResponse(response.data || [])),
    enabled: Boolean(quickstartVaultId) && hasManagedRequestScope(managedScope),
  })
  const authorizedMcpServerUrls = useMemo(
    () => quickstartAuthorizedMcpServerUrls(quickstartVaultMembers ?? []),
    [quickstartVaultMembers],
  )
  const agentMcpServerUrls = useMemo(() => {
    const servers = (config.agent as Record<string, unknown> | undefined)?.mcp_servers
    if (!Array.isArray(servers)) return [] as string[]
    return servers
      .map((server) =>
        server && typeof server === 'object' && !Array.isArray(server)
          ? String((server as Record<string, unknown>).url || '')
          : '',
      )
      .filter(Boolean)
  }, [config.agent])
  const externalToolsAuthorized = useMemo(
    () => agentMcpServerUrls.some((url) => isMcpServerAuthorized(url, authorizedMcpServerUrls)),
    [agentMcpServerUrls, authorizedMcpServerUrls],
  )
  const vaultRecommendation = useMemo(
    () =>
      quickstartCredentialGroupRecommendation(config.vault as Record<string, unknown> | undefined),
    [config.vault],
  )

  const launchAssurance = deriveQuickstartLaunchAssurance({
    hasRuntime: Boolean(selectedEngine),
    hasModelConnection: Boolean(selectedSecret),
    hasEnvironment: Boolean(quickstartEnvironmentId),
    hasExternalToolAuthorization: externalToolsAuthorized,
  })
  const safetyPlanNeedsHardening = launchAssurance.needsHardening
  const safetyPlanSummaryKey = safetyPlanNeedsHardening ? 'hardening' : 'ready'
  const agentBlueprint = useMemo(
    () => normalizeQuickstartAgentBlueprint(config.agent),
    [config.agent],
  )

  const { events: sessionEvents } = useSessionStream(
    sessionId,
    isSessionActive && hasManagedRequestScope(managedScope),
  )
  const hasTrialUserMessage = useMemo(
    () => sessionEvents.some((event) => event.type === 'user.message'),
    [sessionEvents],
  )

  const { data: trialTasksResponse, refetch: refetchTrialTasks } = useQuery<
    PaginatedResponse<QuickstartTaskSummary>
  >({
    queryKey: ['quickstart-trial-tasks', managedScope.key, sessionId] as const,
    queryFn: () => {
      if (!sessionId) {
        return Promise.resolve({ data: [] })
      }
      return managedGet<unknown>(
        `/tasks?session_id=${encodeURIComponent(apiResourceId(sessionId))}&limit=1`,
        managedRequestOptions(managedScope),
      ).then(parseQuickstartTaskPage)
    },
    enabled: isSessionActive && hasTrialUserMessage && hasManagedRequestScope(managedScope),
    refetchOnMount: 'always',
    refetchInterval: (query) => {
      const status = query.state.data?.data?.[0]?.status
      return status === 'pending' || status === 'scheduling' || status === 'running' ? 3000 : false
    },
  })
  const trialTask = trialTasksResponse?.data?.[0] || null
  const [trialStatusNowMs, setTrialStatusNowMs] = useState(() => Date.now())

  useEffect(() => {
    if (!trialTask || (trialTask.status !== 'pending' && trialTask.status !== 'scheduling')) return
    setTrialStatusNowMs(Date.now())
    const interval = window.setInterval(() => setTrialStatusNowMs(Date.now()), 1000)
    return () => window.clearInterval(interval)
  }, [trialTask])

  const { data: activeSession } = useQuery({
    queryKey: ['session', managedScope.key, rawSessionId],
    queryFn: () =>
      managedGet<unknown>(
        apiResourcePath('sessions', sessionId!),
        managedRequestOptions(managedScope),
      ).then(parseSessionResponse),
    enabled: isSessionActive && hasManagedRequestScope(managedScope),
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
  const sessionMsgInputRef = useRef('')
  const sessionMsgDraftVersionRef = useRef(0)

  const setSessionMessageDraft = (value: string, options: { userEdit?: boolean } = {}) => {
    if (options.userEdit) {
      sessionMsgDraftVersionRef.current += 1
    }
    sessionMsgInputRef.current = value
    setSessionMsgInput(value)
  }

  const isSessionRunning = useMemo(() => {
    if (activeSession?.status) return activeSession.status === 'running'
    if (sessionEvents.length === 0) return false
    for (let i = sessionEvents.length - 1; i >= 0; i--) {
      const evtType = sessionEvents[i].type
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
    if (!sessionId || isStoppingSession || !currentPageProjectAllowsWrite()) return
    const requestScope = managedRequestScopeRef.current
    const currentSession = rawSessionId
      ? queryClient.getQueryData<Session>(['session', requestScope.key, rawSessionId])
      : null
    if (currentSession) {
      if (
        currentSession.id !== sessionId ||
        currentSession.status !== 'running' ||
        currentSession.archived_at
      ) {
        return
      }
    } else if (activeSession?.status && activeSession.status !== 'running') {
      return
    }
    const { runId, scope } = nextPageAction()
    const targetRawSessionId = rawSessionId
    const targetSessionId = sessionId
    setIsStoppingSession(true)
    try {
      await managedPost(
        apiResourcePath('sessions', targetSessionId, 'stop'),
        {},
        managedRequestOptions(requestScope),
      )
      if (!isCurrentPageAction(runId, scope)) return
      queryClient.invalidateQueries({ queryKey: ['session', scope, targetRawSessionId] })
    } catch (e) {
      if (!isCurrentPageAction(runId, scope)) return
      toastOperationError(t, e, 'common.operationFailed')
    } finally {
      if (isCurrentPageAction(runId, scope)) {
        setIsStoppingSession(false)
      }
    }
  }

  const handleSendSessionMessage = async () => {
    const text = sessionMsgInput.trim()
    if (!text || !sessionId || isSendingMsg || isSessionRunning || !currentPageProjectAllowsWrite())
      return
    const requestScope = managedRequestScopeRef.current
    const currentSession = rawSessionId
      ? queryClient.getQueryData<Session>(['session', requestScope.key, rawSessionId])
      : null
    if (currentSession) {
      if (
        currentSession.id !== sessionId ||
        currentSession.status !== 'idle' ||
        currentSession.archived_at
      ) {
        return
      }
    } else if (activeSession?.status && activeSession.status !== 'idle') {
      return
    }
    const { runId, scope } = nextPageAction()
    const targetSessionId = sessionId
    setIsSendingMsg(true)
    setSessionMessageDraft('', { userEdit: true })
    try {
      const requestOptions = managedRequestOptions(requestScope)
      await managedPost(
        apiResourcePath('sessions', targetSessionId, 'events'),
        {
          events: [{ type: 'user.message', content: [{ type: 'text', text }] }],
        },
        {
          ...requestOptions,
          headers: {
            ...requestOptions.headers,
            'Idempotency-Key': `session-message:${generateUUID()}`,
          },
        },
      )
    } catch (e) {
      if (!isCurrentPageAction(runId, scope)) return
      const sessionBusy =
        e instanceof ApiError &&
        (e.code === 'SESSION_ALREADY_RUNNING' || e.code === 'SESSION_ACTIVE_TASK')
      if (!sessionBusy) {
        toastOperationError(t, e, 'common.operationFailed')
      }
    } finally {
      if (isCurrentPageAction(runId, scope)) {
        setIsSendingMsg(false)
      }
    }
  }

  const activeEnvironments = useMemo(() => {
    return (environments || []).filter((e) => !e.archived_at)
  }, [environments])

  const activeVaults = useMemo(() => {
    return (vaults || []).filter((v) => !v.archived_at)
  }, [vaults])

  const readCurrentActiveEnvironments = () => {
    const currentEnvironmentData = queryClient.getQueryData<Environment[]>([
      'environments-active',
      managedScope.key,
    ])
    return (currentEnvironmentData || activeEnvironments).filter((env) => !env.archived_at)
  }

  const readCurrentActiveVaults = () => {
    const currentVaultData = queryClient.getQueryData<ActiveCredentialGroupsCache>([
      'credential-groups-active',
      managedScope.key,
    ])
    return (unwrapActiveCredentialGroupsCache(currentVaultData) || activeVaults).filter(
      (vault) => !vault.archived_at,
    )
  }

  const confirmSelectedEnvironment = () => {
    if (!currentPageProjectAllowsWrite()) return
    if (!pendingEnvId) {
      advanceStep()
      return
    }
    const currentEnv = readCurrentActiveEnvironments().find((env) => env.id === pendingEnvId)
    if (!currentEnv) return
    selectExistingEnvironment(currentEnv.id)
    advanceStep()
  }

  const confirmSelectedVault = () => {
    if (!currentPageProjectAllowsWrite()) return
    if (!pendingVaultId) {
      advanceStep()
      return
    }
    const currentVault = readCurrentActiveVaults().find((vault) => vault.id === pendingVaultId)
    if (!currentVault) return
    selectExistingCredentialGroup(currentVault.id)
    advanceStep()
  }

  const currentSessionAgentIsActive = () => {
    if (!currentProjectAllowsWrite()) return false
    const agentId = resourceIds[3]
    if (!agentId) return false
    const currentAgent = queryClient.getQueryData<Agent>(['agent', managedScope.key, agentId])
    if (currentAgent) return currentAgent.id === agentId && !currentAgent.archived_at
    return createdResourceIds.has(agentId)
  }

  const resolveSessionEnvironmentId = () => {
    const envId = tryParseEnvironmentId(resourceIds[4])
    if (!envId) return null
    const currentEnvironmentData = queryClient.getQueryData<Environment[]>([
      'environments-active',
      managedScope.key,
    ])
    const currentEnvRecord = currentEnvironmentData?.find((env) => env.id === envId)
    if (currentEnvRecord?.archived_at) return null
    if (readCurrentActiveEnvironments().some((env) => env.id === envId)) return envId
    return createdResourceIds.has(envId) ? envId : null
  }

  const resolveSessionCredentialGroupId = () => {
    const credentialGroupId = tryParseCredentialGroupId(resourceIds[5])
    if (!credentialGroupId) return null
    const currentVaultData = queryClient.getQueryData<ActiveCredentialGroupsCache>([
      'credential-groups-active',
      managedScope.key,
    ])
    const currentVaultRecord = unwrapActiveCredentialGroupsCache(currentVaultData)?.find(
      (credentialGroup) => credentialGroup.id === credentialGroupId,
    )
    if (currentVaultRecord?.archived_at) return null
    if (
      readCurrentActiveVaults().some((credentialGroup) => credentialGroup.id === credentialGroupId)
    ) {
      return credentialGroupId
    }
    return createdResourceIds.has(credentialGroupId) ? credentialGroupId : null
  }

  const handleCreateSession = () => {
    if (!currentPageProjectAllowsWrite()) return
    if (!currentSessionAgentIsActive()) return
    createSession({
      environmentId: resolveSessionEnvironmentId(),
      credentialGroupId: resolveSessionCredentialGroupId(),
    })
  }

  const selectedEnvironmentName = useMemo(() => {
    return (
      activeEnvironments.find((env) => env.id === selectedEnvId)?.name ||
      activeSession?.environment_id ||
      ''
    )
  }, [activeEnvironments, activeSession?.environment_id, selectedEnvId])

  // Auto-send AI intro only when user chose "Something else" (AI mode)
  useEffect(() => {
    if (
      !currentProjectReadOnly &&
      currentStep === 4 &&
      envUsesAI &&
      !completedSteps.has(4) &&
      !isStreaming
    ) {
      if (!autoIntroSentRef.current.has(4)) {
        autoIntroSentRef.current.add(4)
        sendAutoIntro(4 as StepId)
      }
    }
    if (
      !currentProjectReadOnly &&
      currentStep === 5 &&
      vaultUsesAI &&
      !completedSteps.has(5) &&
      !isStreaming
    ) {
      if (!autoIntroSentRef.current.has(5)) {
        autoIntroSentRef.current.add(5)
        sendAutoIntro(5 as StepId)
      }
    }
  }, [
    currentStep,
    completedSteps,
    currentProjectReadOnly,
    isStreaming,
    sendAutoIntro,
    envUsesAI,
    vaultUsesAI,
  ])

  // Auto-switch to preview and generate test message when session is created
  useEffect(() => {
    const sid = resourceIds[6] || localSessionId
    const scopeAtStart = managedScopeRef.current
    const draftVersionAtStart = sessionMsgDraftVersionRef.current
    if (sid) {
      setRightTab('preview')
      generateTestMessage().then((msg) => {
        if (
          managedScopeRef.current === scopeAtStart &&
          sid === (resourceIds[6] || localSessionId) &&
          msg &&
          sessionMsgDraftVersionRef.current === draftVersionAtStart &&
          !sessionMsgInputRef.current.trim()
        ) {
          setSessionMessageDraft(msg)
        }
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resourceIds[6], localSessionId])

  // Sync environment created in quickstart to the preview panel dropdown
  useEffect(() => {
    const quickstartEnvId = tryParseEnvironmentId(resourceIds[4])
    if (!quickstartEnvId) return

    setSelectedEnvId(quickstartEnvId)
    if (!createdResourceIds.has(quickstartEnvId)) return
    queryClient.setQueryData<Environment[] | undefined>(
      ['environments-active', managedScope.key],
      (current) => {
        if (!current || current.some((env) => env.id === quickstartEnvId)) return current
        const generatedName =
          typeof config.environment?.name === 'string' ? config.environment.name : ''
        return [
          ...current,
          {
            id: quickstartEnvId,
            name:
              envAnswers.choiceLabel ||
              generatedName ||
              shortEntityId(quickstartEnvId, 'environment'),
            created_at: '',
            updated_at: '',
            archived_at: null,
          },
        ]
      },
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resourceIds[4], createdResourceIds])

  const handleEnvSkip = () => {
    skipStep(4)
  }

  const handleVaultSkip = () => {
    skipStep(5)
  }

  const handleSafetyPlanEdit = (step: StepId) => {
    if (!currentPageProjectAllowsWrite()) return
    reopenStep(step)
    setRightTab('blueprint')
    setLocalSessionId(null)
    setIsTestRunning(false)
    if (step <= 2) {
      setSecretRef('')
      setSecretSelectionCleared(true)
    }
    if (step <= 4) {
      setSelectedEnvId('')
      setPendingEnvId(null)
      setEnvSubStep('choose')
      setEnvUsesAI(false)
      setEnvAnswers({})
      setEnvHosts('')
    }
    if (step <= 5) {
      setPendingVaultId(null)
      setVaultSubStep('choose')
      setVaultUsesAI(false)
      setVaultAnswers({})
      setVaultName('')
      setVaultCredentialName('')
      setVaultMcpServerUrl('')
      setVaultTokenValue('')
    }
  }

  // Trial run status derived from session events
  const trialRunStatus = useMemo(() => {
    return deriveQuickstartTrialStatus({
      isSessionActive,
      events: sessionEvents,
      task: trialTask,
      nowMs: trialStatusNowMs,
    })
  }, [isSessionActive, sessionEvents, trialStatusNowMs, trialTask])
  const capabilityEvidence = useMemo(
    () =>
      deriveQuickstartCapabilityEvidence({
        responseReceived: trialRunStatus === 'response_received',
        environmentId: quickstartEnvironmentId,
        externalToolsAuthorized,
        configuredSkills: quickstartConfiguredSkillNames(config.agent, availableSkills),
        events: sessionEvents,
      }),
    [
      availableSkills,
      config.agent,
      quickstartEnvironmentId,
      externalToolsAuthorized,
      sessionEvents,
      trialRunStatus,
    ],
  )
  const observableChecks = useMemo(() => {
    const agent = config.agent as Record<string, unknown> | undefined
    const declaredArray = (key: string) =>
      Array.isArray(agent?.[key]) && (agent![key] as unknown[]).length > 0
    const hasDeclaredCapabilities =
      agentMcpServerUrls.length > 0 || declaredArray('skills') || declaredArray('tools')
    return deriveQuickstartObservableChecks({
      trialStatus: trialRunStatus,
      evidence: capabilityEvidence,
      hasDeclaredCapabilities,
    })
  }, [config.agent, agentMcpServerUrls, trialRunStatus, capabilityEvidence])

  const handleTestRun = async () => {
    const agentId = resourceIds[3]
    if (!agentId || !currentPageProjectAllowsWrite()) return
    const requestScope = managedRequestScopeRef.current
    const { runId, scope } = nextPageAction()
    setIsTestRunning(true)
    try {
      const body: Record<string, unknown> = { agent: apiResourceId(parseAgentId(agentId)) }
      const currentEnvironmentData = queryClient.getQueryData<Environment[]>([
        'environments-active',
        requestScope.key,
      ])
      const currentActiveEnvironments = readCurrentActiveEnvironments()
      const currentSelectedEnv = currentActiveEnvironments.find((env) => env.id === selectedEnvId)
      const currentSelectedEnvRecord = currentEnvironmentData?.find(
        (env) => env.id === selectedEnvId,
      )
      const selectedEnvIsCurrentQuickstartResource =
        selectedEnvId === resourceIds[4] &&
        createdResourceIds.has(selectedEnvId) &&
        !currentSelectedEnvRecord?.archived_at
      const selectedEnvCanBeSubmitted =
        !!currentSelectedEnv || selectedEnvIsCurrentQuickstartResource
      if (selectedEnvId && selectedEnvCanBeSubmitted) {
        body.environment_id = apiResourceId(
          currentSelectedEnv?.id || parseEnvironmentId(selectedEnvId),
        )
      }
      const res = parseSessionCreateResponse(
        await managedPost<unknown>('/sessions', body, managedRequestOptions(requestScope)),
      )
      if (!isCurrentPageAction(runId, scope)) return
      setLocalSessionId(res.id)
      setRightTab('preview')
    } catch (e) {
      if (!isCurrentPageAction(runId, scope)) return
      toastOperationError(t, e, 'common.operationFailed')
    } finally {
      if (isCurrentPageAction(runId, scope)) {
        setIsTestRunning(false)
      }
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
    if (!currentPageProjectAllowsWrite()) return
    const name = t(`quickstart.template.${templateId}.name`)
    const description = t(`quickstart.template.${templateId}.description`)
    const config = TEMPLATE_CONFIGS[templateId] || TEMPLATE_CONFIGS.blank
    if (!selectedEngine) {
      const recommendedEngine = engineOptionsForIntent(`${templateId} ${name} ${description}`).find(
        (option) => option.recommended,
      )?.engineId as QuickstartEngine | undefined
      if (recommendedEngine) selectEngine(recommendedEngine)
    }
    applyTemplate({
      message: t('managed.quickstart.templateApplyMessage', {
        name,
        defaultValue: `Create an agent from the "${name}" template`,
      }),
      agent: {
        ...config,
        name,
        description,
      },
    })
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
    if (a.system) ordered.system = a.system
    if (a.tools) ordered.tools = a.tools
    if (a.mcp_servers) ordered.mcp_servers = a.mcp_servers
    if (a.skills) ordered.skills = a.skills
    if (a.env) ordered.env = a.env
    if (a.multiagent) ordered.multiagent = a.multiagent
    if (a.metadata) ordered.metadata = a.metadata
    return ordered
  }, [config, currentStep])

  const configText = useMemo(() => {
    if (!configObj) {
      const label =
        currentStep === 4
          ? t('managed.quickstart.resourceKindEnvironment')
          : currentStep === 5
            ? t('managed.quickstart.resourceKindMcpCredentialSet')
            : t('managed.quickstart.resourceKindAgent')
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
  }, [configObj, editorTab, currentStep, t])

  const codeLines = configText.split('\n')

  useEffect(() => {
    const el = configScrollRef.current
    if (!el || rightTab !== 'advanced') return

    el.scrollTop = el.scrollHeight
  }, [configText, rightTab])

  const handleInputChange = (value: string) => {
    setInputValue(value)
    setPendingEngineRecommendation(null)
  }

  const engineOptionsForIntent = (intent: string) =>
    buildQuickstartEngineOptions({
      enabledEngines: catalogEngines,
      modelConnections: activeModelConnections,
      intentText: intent,
    })

  const confirmRecommendedEngine = (engineId: QuickstartEngine) => {
    const text = (pendingEngineRecommendation?.intent || inputValue).trim()
    if (!text || isStreaming || isSessionRunning || !currentPageProjectAllowsWrite()) return
    const selectedOption = engineOptionsForIntent(text).find(
      (option) => option.engineId === engineId,
    )
    if (!selectedOption || selectedOption.readiness === 'unavailable') return
    setPendingEngineRecommendation(null)
    setInputValue('')
    selectEngine(engineId)
    void sendMessage(text, { engineKindOverride: engineId })
  }

  const handleSend = () => {
    const text = inputValue.trim()
    if (!text || isStreaming || isSessionRunning || !currentPageProjectAllowsWrite()) return
    if (!selectedEngine) {
      const recommendedEngine = engineOptionsForIntent(text).find((option) => option.recommended)
        ?.engineId as QuickstartEngine | undefined
      if (!recommendedEngine) return
      setPendingEngineRecommendation({ intent: text, engineId: recommendedEngine })
      return
    }
    setPendingEngineRecommendation(null)
    setInputValue('')
    void sendMessage(text)
  }

  const handleQuickstartEngineSelect = (engine: QuickstartEngine) => {
    selectEngine(engine)
  }

  const handleAgentSecretSelect = (credentialId: string) => {
    if (!currentPageProjectAllowsWrite()) return
    setSecretRef(credentialId)
    setSecretSelectionCleared(false)
    selectAgentSecret(credentialId)
  }

  const handleInlineSecretCreated = (created: CredentialDetail) => {
    if (!selectedEngine) return
    const listItem: Credential = created
    queryClient.setQueriesData<Credential[]>(
      { queryKey: compatibleCredentialsQueryPrefix(managedScope.key, selectedEngine) },
      (current) => [...(current ?? []).filter((secret) => secret.id !== listItem.id), listItem],
    )
    setSecretRef(created.id)
    setSecretSelectionCleared(false)
    selectAgentSecret(created.id)
  }

  const inputEngineOptions = engineOptionsForIntent(inputValue)
  const pendingEngineOptions = pendingEngineRecommendation
    ? engineOptionsForIntent(pendingEngineRecommendation.intent)
    : []
  const recommendedPendingEngine = pendingEngineOptions.find((option) => option.recommended)
  const recommendedInputOption = inputEngineOptions.find((option) => option.recommended)
  const recommendedInputEngine =
    selectedEngine ?? recommendedPendingEngine?.engineId ?? recommendedInputOption?.engineId
  const pendingEngineCapability = pendingEngineRecommendation
    ? catalogEngines.find((engine) => engine.id === pendingEngineRecommendation.engineId)
    : null
  const isMainInputBlockedBySetup =
    currentStep !== 1 &&
    (!selectedEngine ||
      currentStep === 2 ||
      !secretRef ||
      (currentStep >= 3 && (!secretRef || !selectedSecretCompatible)))
  const isMainInputDisabled = currentProjectReadOnly || isStreaming || isMainInputBlockedBySetup
  const isMainSendDisabled =
    isMainInputDisabled ||
    isSessionRunning ||
    !inputValue.trim() ||
    (!selectedEngine && (!activeModelConnectionsQuery.isSuccess || !recommendedInputEngine))
  const mainInputPlaceholderKey = quickstartInputPlaceholderKey({
    selectedEngine: selectedEngine ?? '',
    secretRef,
    currentStep,
    selectedSecretCompatible,
    isSessionRunning,
    isStreaming,
    readyKey: isLanding ? 'managed.quickstart.describeAgent' : 'managed.quickstart.reply',
  })

  return (
    <div className="w-full">
      <h1 className="px-1 pt-1 text-lg font-semibold text-foreground">
        {t('managed.quickstart.title')}
      </h1>

      <Stepper
        currentStep={currentStep}
        completedSteps={completedSteps}
        skippedSteps={skippedSteps}
        trialStatus={trialRunStatus}
      />

      {!isLanding && (isSessionActive || Boolean(resourceIds[3])) && (
        <div className="flex items-center justify-end gap-2 px-1 pb-3">
          {isSessionActive && isSessionRunning ? (
            <Button
              size="sm"
              className="gap-1.5 bg-foreground text-xs text-background hover:bg-foreground/90"
              disabled={isStoppingSession || currentProjectReadOnly}
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
              disabled={!resourceIds[3] || isTestRunning || currentProjectReadOnly}
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

      {isLanding ? (
        <div className="grid min-h-[calc(100vh-160px)] gap-6 lg:h-[calc(100vh-160px)] lg:min-h-0 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
          <section className="flex flex-col rounded-2xl border border-border bg-card p-6 lg:min-h-0">
            <div className="flex flex-1 flex-col justify-center">
              <h2 className="whitespace-pre-line text-[32px] font-bold leading-tight tracking-tight text-foreground">
                {t('managed.quickstart.whatToBuild')}
              </h2>
              <p className="mt-3 max-w-[340px] text-[15px] leading-relaxed text-muted-foreground">
                {t('managed.quickstart.subtitle')}
              </p>
              <div className="mt-6 grid gap-2 sm:grid-cols-2">
                {QUICKSTART_SECURITY_HIGHLIGHTS.map((item) => {
                  const Icon = item.icon
                  return (
                    <div
                      key={item.titleKey}
                      className="border-border/80 rounded-xl border bg-background/70 p-3 shadow-sm"
                    >
                      <div className="flex items-center gap-2 text-xs font-semibold text-foreground">
                        <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-primary/10 text-primary">
                          <Icon className="h-3.5 w-3.5" />
                        </span>
                        {t(item.titleKey)}
                      </div>
                      <p className="mt-1.5 text-[11px] leading-4 text-muted-foreground">
                        {t(item.descriptionKey)}
                      </p>
                    </div>
                  )
                })}
              </div>
            </div>
            <div className="rounded-xl border border-border bg-background px-3 py-2.5">
              <div className="flex items-center gap-2">
                <input
                  ref={inputRef}
                  type="text"
                  value={inputValue}
                  onChange={(e) => handleInputChange(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault()
                      handleSend()
                    }
                  }}
                  disabled={isMainInputDisabled}
                  placeholder={t(mainInputPlaceholderKey)}
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
              {pendingEngineRecommendation && !selectedEngine ? (
                <div className="mt-3 rounded-xl border border-primary/20 bg-primary/5 p-3">
                  <p className="text-xs font-semibold text-foreground">
                    {t('managed.quickstart.engineRecommendation.title')}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t('managed.quickstart.engineRecommendation.description')}
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {pendingEngineOptions.map((option) => {
                      const engine = option.engine
                      const recommended = option.recommended
                      return (
                        <Button
                          key={engine.id}
                          type="button"
                          size="sm"
                          variant={recommended ? 'default' : 'outline'}
                          disabled={option.readiness === 'unavailable'}
                          onClick={() => confirmRecommendedEngine(engine.id as QuickstartEngine)}
                        >
                          {recommended
                            ? t('managed.quickstart.engineRecommendation.useRecommended', {
                                engine:
                                  pendingEngineCapability?.display_name || engine.display_name,
                              })
                            : engine.display_name}
                          <span className="ml-1 text-[10px] opacity-75">
                            <span>
                              {t(
                                option.readiness === 'ready'
                                  ? 'managed.quickstart.engineRecommendation.readyNow'
                                  : option.readiness === 'setup_required'
                                    ? 'managed.quickstart.engineRecommendation.setupRequired'
                                    : 'managed.quickstart.engineRecommendation.unavailable',
                              )}
                            </span>
                            {option.readiness === 'ready' ? (
                              <>
                                {' · '}
                                <span>
                                  {t('managed.quickstart.engineRecommendation.connectionCount', {
                                    count: option.compatibleConnectionCount,
                                  })}
                                </span>
                              </>
                            ) : null}
                          </span>
                        </Button>
                      )
                    })}
                  </div>
                </div>
              ) : null}
            </div>
          </section>

          <section className="overflow-auto rounded-2xl border border-border bg-card p-6 shadow-sm lg:min-h-0 lg:overflow-y-auto">
            <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <h3 className="text-[17px] font-semibold text-foreground">
                  {t('managed.quickstart.browseTemplates')}
                </h3>
                <p className="mt-1 text-sm text-muted-foreground">
                  {t('managed.quickstart.templateBrowseHint')}
                </p>
              </div>
              <div className="rounded-full bg-muted px-3 py-1 text-xs text-muted-foreground">
                {t('managed.quickstart.templateCount', { count: filteredTemplates.length })}
              </div>
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
            <div className="grid gap-3 xl:grid-cols-2">
              {filteredTemplates.map((id) => (
                <TemplateCard
                  key={id}
                  templateId={id}
                  disabled={currentProjectReadOnly}
                  onClick={() => handleTemplateClick(id)}
                />
              ))}
            </div>
            {filteredTemplates.length === 0 && (
              <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-border bg-muted/20 px-4 py-12 text-center">
                <Search className="mb-3 h-6 w-6 text-muted-foreground" />
                <div className="text-sm font-medium text-foreground">
                  {t('managed.quickstart.noTemplatesMatch')}
                </div>
                <button
                  type="button"
                  onClick={() => setTemplateSearch('')}
                  className="mt-2 text-xs font-medium text-primary hover:underline"
                >
                  {t('managed.quickstart.clearTemplateSearch')}
                </button>
              </div>
            )}
          </section>
        </div>
      ) : (
        <div className="rounded-2xl border border-border bg-card p-2 shadow-sm">
          <div className="grid min-h-[calc(100vh-168px)] gap-0 lg:grid-cols-[420px_minmax(0,1fr)]">
            {/* Left panel: chat */}
            <section className="relative border-r border-border bg-background px-5 pb-16 pt-5">
              <div className="h-[calc(100vh-250px)] space-y-4 overflow-y-auto pr-1">
                {messages.map((msg) => (
                  <ChatBubble key={msg.id} message={msg} />
                ))}

                {currentStep === 1 &&
                  !completedSteps.has(1) &&
                  (catalogQuery.isLoading ? (
                    <div className="rounded-xl border border-dashed p-4 text-sm text-muted-foreground">
                      {t('managed.llm.loadingCatalog')}
                    </div>
                  ) : catalogQuery.isError ? (
                    <div className="flex items-center justify-between gap-3 rounded-xl border border-destructive/40 bg-destructive/5 p-4">
                      <span className="text-sm text-destructive">
                        {t('managed.llm.catalogLoadFailed')}
                      </span>
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => catalogQuery.refetch()}
                      >
                        {t('common.retry')}
                      </Button>
                    </div>
                  ) : enabledEngines.length > 0 ? (
                    <NumberedChoiceList
                      question={t('managed.quickstart.engineQuestion')}
                      hint={t('managed.quickstart.engineHint')}
                      choices={enabledEngines.map((engine, index) => ({
                        num: index + 1,
                        label: engine.display_name,
                        arrow: index === 0,
                      }))}
                      onSelect={(num) => {
                        const engine = enabledEngines[num - 1]
                        if (engine) handleQuickstartEngineSelect(engine.id as QuickstartEngine)
                      }}
                    />
                  ) : (
                    <div className="rounded-xl border border-dashed p-4 text-sm text-muted-foreground">
                      {t('managed.llm.noEnabledEngines')}
                    </div>
                  ))}

                {currentStep === 2 && !completedSteps.has(2) && selectedEngine && (
                  <div className="space-y-3 rounded-xl border border-border bg-background p-4">
                    <p className="text-sm font-semibold text-foreground">
                      {t('managed.quickstart.secretQuestion')}
                    </p>
                    <p className="text-xs leading-5 text-muted-foreground">
                      {t('managed.quickstart.secretHint')}
                    </p>
                    {modelRecommendation ? (
                      <div className="rounded-xl border border-primary/20 bg-primary/5 p-3">
                        <div className="flex items-center gap-2 text-xs font-semibold text-primary">
                          <Sparkles className="h-3.5 w-3.5" />
                          {t('managed.quickstart.modelRecommendation.title')}
                        </div>
                        <div className="mt-2 flex flex-col gap-1 text-sm text-foreground">
                          <span className="font-medium">{modelRecommendation.secret.name}</span>
                          <span className="text-xs leading-5 text-muted-foreground">
                            {t(MODEL_RECOMMENDATION_REASON_KEYS[modelRecommendation.reason])}
                          </span>
                        </div>
                      </div>
                    ) : null}
                    <QuickstartLlmStep
                      key={selectedEngine}
                      engineId={selectedEngine}
                      value={secretRef}
                      disabled={currentProjectReadOnly}
                      onSelect={handleAgentSecretSelect}
                      onCreated={handleInlineSecretCreated}
                    />
                    {secretRef ? (
                      <Button
                        type="button"
                        className="h-10 rounded-xl px-5 text-sm font-semibold"
                        onClick={() => handleAgentSecretSelect(secretRef)}
                        disabled={currentProjectReadOnly}
                      >
                        {t('managed.quickstart.useSelectedModelConnection')}
                      </Button>
                    ) : null}
                  </div>
                )}

                {/* Step 2 secret: show completed badge before the next step actions */}
                {currentStep > 2 && completedSteps.has(2) && selectedSecret && (
                  <StepDoneBadge
                    label={`${t('managed.quickstart.stepComplete.secretSelected')}: ${selectedSecret.name}`}
                  />
                )}

                {pendingConfirmation &&
                  pendingConfirmation.step === currentStep &&
                  (currentStep === 5 && vaultRecommendation.requiresCredential ? (
                    <div className="space-y-3 rounded-xl border border-border bg-background p-4">
                      <div className="flex items-start gap-2">
                        <Shield className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
                        <div className="space-y-1">
                          <p className="text-sm font-semibold text-foreground">
                            {t('managed.quickstart.vaultCredentialTitle')}
                          </p>
                          <p className="text-xs leading-5 text-muted-foreground">
                            {t('managed.quickstart.vaultCredentialHint')}
                          </p>
                        </div>
                      </div>
                      <div className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs">
                        <p className="font-medium text-foreground">
                          {vaultRecommendation.name ||
                            t('managed.quickstart.resourceKindMcpCredentialSet')}
                        </p>
                        <p className="mt-0.5 break-all text-muted-foreground">
                          {vaultRecommendation.mcpServerUrl}
                        </p>
                      </div>
                      <input
                        type="password"
                        value={vaultTokenValue}
                        onChange={(e) => setVaultTokenValue(e.target.value)}
                        placeholder={t('managed.quickstart.vaultTokenPlaceholder')}
                        className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-ring"
                      />
                      <div className="flex items-center gap-3">
                        <Button
                          className="h-10 rounded-xl px-5 text-sm font-semibold"
                          disabled={isCreating || currentProjectReadOnly || !vaultTokenValue.trim()}
                          onClick={async () => {
                            const urlError = validateUrlScheme(vaultRecommendation.mcpServerUrl)
                            if (urlError) {
                              alert(urlError)
                              return
                            }
                            const created = await createCredentialGroup(
                              vaultRecommendation.name || 'quickstart-vault',
                              {
                                credential: {
                                  name: vaultRecommendation.credentialName,
                                  mcpServerUrl: vaultRecommendation.mcpServerUrl,
                                  tokenValue: vaultTokenValue.trim(),
                                },
                              },
                            )
                            if (!created) return
                            setVaultAnswers((prev) => ({
                              ...prev,
                              choiceLabel: vaultRecommendation.name,
                            }))
                            setVaultTokenValue('')
                            advanceStep()
                          }}
                        >
                          {isCreating ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                          {t('managed.quickstart.createThisCredentialGroup')}
                        </Button>
                        <Button
                          variant="outline"
                          className="h-10 rounded-xl px-4 text-sm font-semibold"
                          onClick={keepRefining}
                          disabled={isCreating}
                        >
                          {t('managed.quickstart.keepRefining')}
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-xs text-muted-foreground"
                          onClick={handleVaultSkip}
                          disabled={isCreating}
                        >
                          {t('common.skip')}
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-center gap-3 pt-1">
                      <Button
                        className="h-10 rounded-xl px-5 text-sm font-semibold"
                        onClick={confirmStep}
                        disabled={isCreating || currentProjectReadOnly}
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
                          t('managed.quickstart.createThisCredentialGroup')
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
                  ))}

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
                      {envSubStep === 'choose' ? (
                        <p className="rounded-xl border border-primary/20 bg-primary/5 p-3 text-xs leading-5 text-muted-foreground">
                          {t('managed.quickstart.envIntro')}
                        </p>
                      ) : null}
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
                              const currentEnv = readCurrentActiveEnvironments().find(
                                (current) => current.id === env.id,
                              )
                              if (!currentEnv) return
                              setPendingEnvId(currentEnv.id)
                              setEnvAnswers({ choiceLabel: currentEnv.name })
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
                              onClick={confirmSelectedEnvironment}
                            >
                              {t('managed.quickstart.nextConfigureCredentialGroup')}
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
                              { num: 0, label: t('managed.quickstart.envSomethingElse') },
                            ]}
                            onSelect={async (num) => {
                              if (num === 0) {
                                setEnvSubStep(null)
                                setEnvUsesAI(true)
                              } else {
                                setEnvAnswers((prev) => ({
                                  ...prev,
                                  networkingLabel: t('managed.quickstart.envLimited'),
                                }))
                                if (!envHosts.trim() && suggestedAllowlist) {
                                  setEnvHosts(suggestedAllowlist)
                                }
                                setEnvSubStep('hosts')
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
                            <div
                              className={cn(
                                'rounded-xl border p-3 text-xs',
                                suggestedAllowlist
                                  ? 'border-primary/20 bg-primary/5'
                                  : 'border-border bg-muted/30',
                              )}
                            >
                              <div className="flex items-start gap-2">
                                <Sparkles
                                  className={cn(
                                    'mt-0.5 h-3.5 w-3.5 shrink-0',
                                    suggestedAllowlist ? 'text-primary' : 'text-muted-foreground',
                                  )}
                                />
                                <div className="min-w-0 flex-1 space-y-2">
                                  <div>
                                    <p className="font-semibold text-foreground">
                                      {t('managed.quickstart.smartDefaults.allowlist.title')}
                                    </p>
                                    <p className="mt-0.5 leading-5 text-muted-foreground">
                                      {suggestedAllowlist
                                        ? t(
                                            `managed.quickstart.smartDefaults.allowlist.reason.${safetyRecommendation.hostReason}`,
                                          )
                                        : t(
                                            'managed.quickstart.smartDefaults.allowlist.emptyDescription',
                                          )}
                                    </p>
                                  </div>
                                  {safetyRecommendation.recommendedHosts.length > 0 ? (
                                    <div className="flex flex-wrap gap-1.5">
                                      {safetyRecommendation.recommendedHosts.map((host) => (
                                        <span
                                          key={host}
                                          className="rounded-full border border-primary/20 bg-background px-2 py-0.5 font-mono text-[11px] text-foreground"
                                        >
                                          {host}
                                        </span>
                                      ))}
                                    </div>
                                  ) : null}
                                </div>
                                {suggestedAllowlist ? (
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="h-7 shrink-0 px-2 text-xs"
                                    disabled={currentProjectReadOnly}
                                    onClick={() => setEnvHosts(suggestedAllowlist)}
                                  >
                                    {t('managed.quickstart.smartDefaults.allowlist.useSuggested')}
                                  </Button>
                                ) : null}
                              </div>
                            </div>
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
                                disabled={isCreating || currentProjectReadOnly}
                                onClick={async () => {
                                  const hosts = normalizeQuickstartAllowedHosts(envHosts)
                                  const created = await createEnvironment('limited', hosts)
                                  if (!created) return
                                  setEnvSubStep('selected')
                                  advanceStep()
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
                        <div className="space-y-3">
                          <p className="rounded-xl border border-primary/20 bg-primary/5 p-3 text-xs leading-5 text-muted-foreground">
                            {t('managed.quickstart.vaultIntro')}
                          </p>
                          <div
                            className={cn(
                              'rounded-xl border p-3 text-xs',
                              safetyRecommendation.externalToolsRecommended
                                ? 'border-primary/20 bg-primary/5'
                                : 'border-border bg-muted/30',
                            )}
                          >
                            <div className="flex items-start gap-2">
                              <Sparkles
                                className={cn(
                                  'mt-0.5 h-3.5 w-3.5 shrink-0',
                                  safetyRecommendation.externalToolsRecommended
                                    ? 'text-primary'
                                    : 'text-muted-foreground',
                                )}
                              />
                              <div className="space-y-1">
                                <p className="font-semibold text-foreground">
                                  {t('managed.quickstart.smartDefaults.externalTools.title')}
                                </p>
                                <p className="leading-5 text-muted-foreground">
                                  {t(
                                    `managed.quickstart.smartDefaults.externalTools.reason.${safetyRecommendation.externalToolsReason}`,
                                  )}
                                </p>
                              </div>
                            </div>
                          </div>
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
                                const currentVault = readCurrentActiveVaults().find(
                                  (current) => current.id === vault.id,
                                )
                                if (!currentVault) return
                                setPendingVaultId(currentVault.id)
                                setVaultAnswers({ choiceLabel: currentVault.name })
                                setVaultSubStep('selected')
                              } else {
                                setVaultAnswers({
                                  choiceLabel: t('managed.quickstart.vaultCreateNew'),
                                })
                                if (!vaultMcpServerUrl.trim() && suggestedMcpServerUrl) {
                                  setVaultMcpServerUrl(suggestedMcpServerUrl)
                                }
                                setVaultSubStep('name')
                              }
                            }}
                            onSkip={handleVaultSkip}
                          />
                        </div>
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
                              onClick={confirmSelectedVault}
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
                            <div className="rounded-xl border border-primary/20 bg-primary/5 p-3 text-xs">
                              <div className="flex items-start gap-2">
                                <Shield className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
                                <div className="space-y-1">
                                  <p className="font-semibold text-foreground">
                                    {t('managed.quickstart.vaultCredentialTitle')}
                                  </p>
                                  <p className="leading-5 text-muted-foreground">
                                    {t('managed.quickstart.vaultCredentialHint')}
                                  </p>
                                </div>
                              </div>
                            </div>
                            <input
                              type="text"
                              value={vaultMcpServerUrl}
                              onChange={(e) => setVaultMcpServerUrl(e.target.value)}
                              placeholder={t('managed.quickstart.vaultMcpServerUrlPlaceholder')}
                              className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-ring"
                            />
                            <input
                              type="text"
                              value={vaultCredentialName}
                              onChange={(e) => setVaultCredentialName(e.target.value)}
                              placeholder={t('managed.quickstart.vaultCredentialNamePlaceholder')}
                              className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-ring"
                            />
                            <input
                              type="password"
                              value={vaultTokenValue}
                              onChange={(e) => setVaultTokenValue(e.target.value)}
                              placeholder={t('managed.quickstart.vaultTokenPlaceholder')}
                              className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-ring"
                            />
                            <div className="flex items-center justify-between">
                              <Button
                                className="h-9 rounded-xl px-4 text-sm"
                                disabled={
                                  isCreating ||
                                  currentProjectReadOnly ||
                                  !vaultName.trim() ||
                                  (Boolean(
                                    safetyRecommendation.externalToolsRecommended ||
                                    vaultMcpServerUrl.trim() ||
                                    vaultTokenValue.trim(),
                                  ) &&
                                    (!vaultMcpServerUrl.trim() || !vaultTokenValue.trim()))
                                }
                                onClick={async () => {
                                  const credential =
                                    vaultMcpServerUrl.trim() && vaultTokenValue.trim()
                                      ? {
                                          name: vaultCredentialName.trim(),
                                          mcpServerUrl: vaultMcpServerUrl.trim(),
                                          tokenValue: vaultTokenValue.trim(),
                                        }
                                      : undefined
                                  if (credential) {
                                    const urlError = validateUrlScheme(credential.mcpServerUrl)
                                    if (urlError) {
                                      alert(urlError)
                                      return
                                    }
                                  }
                                  const created = await createCredentialGroup(vaultName.trim(), {
                                    credential,
                                  })
                                  if (!created) return
                                  setVaultAnswers((prev) => ({
                                    ...prev,
                                    choiceLabel: vaultName.trim(),
                                  }))
                                  setVaultSubStep('selected')
                                  advanceStep()
                                }}
                              >
                                {isCreating ? (
                                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                                ) : null}
                                {t('managed.quickstart.createCredentialGroup')}
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
                    <div className="rounded-xl border border-primary/20 bg-primary/5 p-4">
                      <div className="flex items-start gap-2">
                        <Shield className="mt-0.5 h-4 w-4 text-primary" />
                        <div className="space-y-1">
                          <p className="text-sm font-semibold text-foreground">
                            {t('managed.quickstart.safetyPlan.title')}
                          </p>
                          <p className="text-xs leading-5 text-muted-foreground">
                            {t('managed.quickstart.safetyPlan.description')}
                          </p>
                        </div>
                      </div>
                      <div
                        className={cn(
                          'mt-3 rounded-lg border px-3 py-2 text-xs',
                          safetyPlanNeedsHardening
                            ? 'border-amber-200 bg-amber-50 text-amber-800'
                            : 'border-emerald-200 bg-emerald-50 text-emerald-800',
                        )}
                      >
                        <div className="flex items-start gap-2">
                          {safetyPlanNeedsHardening ? (
                            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                          ) : (
                            <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                          )}
                          <div className="space-y-0.5">
                            <p className="font-semibold">
                              {t(`managed.quickstart.safetyPlan.summary.${safetyPlanSummaryKey}`)}
                            </p>
                            <p className="leading-5">
                              {t(
                                `managed.quickstart.safetyPlan.summary.${safetyPlanSummaryKey}Description`,
                              )}
                            </p>
                          </div>
                        </div>
                      </div>
                      <div className="mt-3 space-y-2 text-xs">
                        <div className="rounded-lg bg-background/70 px-3 py-2">
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0 space-y-1">
                              <span className="font-medium text-foreground">
                                {t('managed.quickstart.safetyPlan.runtime')}
                              </span>
                              <p className="text-[11px] leading-4 text-muted-foreground">
                                {t('managed.quickstart.safetyPlan.hint.runtime')}
                              </p>
                            </div>
                            <div className="flex shrink-0 items-center gap-2">
                              <SafetyPlanStatusBadge
                                tone={selectedEngine ? 'ready' : 'warning'}
                                label={t(
                                  selectedEngine
                                    ? 'managed.quickstart.safetyPlan.status.ready'
                                    : 'managed.quickstart.safetyPlan.status.required',
                                )}
                              />
                              <span className="max-w-[180px] truncate text-right font-medium text-foreground">
                                {selectedEngineCapability?.display_name ||
                                  selectedEngine ||
                                  t('managed.quickstart.safetyPlan.notConfigured')}
                              </span>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-7 px-2 text-xs"
                                disabled={currentProjectReadOnly}
                                onClick={() => handleSafetyPlanEdit(1)}
                              >
                                {t('managed.quickstart.safetyPlan.action.changeRuntime')}
                              </Button>
                            </div>
                          </div>
                        </div>
                        <div className="rounded-lg bg-background/70 px-3 py-2">
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0 space-y-1">
                              <span className="font-medium text-foreground">
                                {t('managed.quickstart.safetyPlan.modelConnection')}
                              </span>
                              <p className="text-[11px] leading-4 text-muted-foreground">
                                {t('managed.quickstart.safetyPlan.hint.modelConnection')}
                              </p>
                            </div>
                            <div className="flex shrink-0 items-center gap-2">
                              <SafetyPlanStatusBadge
                                tone={selectedSecret ? 'ready' : 'warning'}
                                label={t(
                                  selectedSecret
                                    ? 'managed.quickstart.safetyPlan.status.ready'
                                    : 'managed.quickstart.safetyPlan.status.required',
                                )}
                              />
                              <span className="max-w-[180px] truncate text-right font-medium text-foreground">
                                {selectedSecret?.name ||
                                  t('managed.quickstart.safetyPlan.notConfigured')}
                              </span>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-7 px-2 text-xs"
                                disabled={currentProjectReadOnly}
                                onClick={() => handleSafetyPlanEdit(2)}
                              >
                                {t('managed.quickstart.safetyPlan.action.changeModelConnection')}
                              </Button>
                            </div>
                          </div>
                        </div>
                        <div className="rounded-lg bg-background/70 px-3 py-2">
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0 space-y-1">
                              <span className="font-medium text-foreground">
                                {t('managed.quickstart.safetyPlan.environment')}
                              </span>
                              <p className="text-[11px] leading-4 text-muted-foreground">
                                {quickstartEnvironmentId
                                  ? t('managed.quickstart.safetyPlan.hint.environment')
                                  : suggestedAllowlist
                                    ? t(
                                        'managed.quickstart.safetyPlan.hint.recommendedEnvironment',
                                        {
                                          hosts: suggestedAllowlist,
                                        },
                                      )
                                    : t('managed.quickstart.safetyPlan.hint.noEnvironment')}
                              </p>
                            </div>
                            <div className="flex shrink-0 items-center gap-2">
                              <SafetyPlanStatusBadge
                                tone={quickstartEnvironmentId ? 'ready' : 'warning'}
                                label={t(
                                  quickstartEnvironmentId
                                    ? 'managed.quickstart.safetyPlan.status.enforced'
                                    : 'managed.quickstart.safetyPlan.status.recommended',
                                )}
                              />
                              <span className="max-w-[180px] truncate text-right font-medium text-foreground">
                                {quickstartEnvironmentId
                                  ? shortEntityId(quickstartEnvironmentId, 'environment')
                                  : t('managed.quickstart.safetyPlan.noEnvironment')}
                              </span>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-7 px-2 text-xs"
                                disabled={currentProjectReadOnly}
                                onClick={() => handleSafetyPlanEdit(4)}
                              >
                                {quickstartEnvironmentId
                                  ? t('managed.quickstart.safetyPlan.action.changeEnvironment')
                                  : t('managed.quickstart.safetyPlan.action.configureEnvironment')}
                              </Button>
                            </div>
                          </div>
                        </div>
                        <div className="rounded-lg bg-background/70 px-3 py-2">
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0 space-y-1">
                              <span className="font-medium text-foreground">
                                {t('managed.quickstart.safetyPlan.externalTools')}
                              </span>
                              <p className="text-[11px] leading-4 text-muted-foreground">
                                {quickstartVaultId
                                  ? t('managed.quickstart.safetyPlan.hint.externalTools')
                                  : t('managed.quickstart.safetyPlan.hint.noExternalTools')}
                              </p>
                            </div>
                            <div className="flex shrink-0 items-center gap-2">
                              <SafetyPlanStatusBadge
                                tone={quickstartVaultId ? 'primary' : 'muted'}
                                label={t(
                                  quickstartVaultId
                                    ? 'managed.quickstart.safetyPlan.status.ready'
                                    : 'managed.quickstart.safetyPlan.status.notAuthorized',
                                )}
                              />
                              <span className="max-w-[180px] truncate text-right font-medium text-foreground">
                                {quickstartVaultId
                                  ? shortEntityId(quickstartVaultId, 'credentialGroup')
                                  : t('managed.quickstart.safetyPlan.notAuthorized')}
                              </span>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-7 px-2 text-xs"
                                disabled={currentProjectReadOnly}
                                onClick={() => handleSafetyPlanEdit(5)}
                              >
                                {quickstartVaultId
                                  ? t('managed.quickstart.safetyPlan.action.changeTools')
                                  : t('managed.quickstart.safetyPlan.action.authorizeTools')}
                              </Button>
                            </div>
                          </div>
                        </div>
                        <div className="rounded-lg bg-background/70 px-3 py-2">
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0 space-y-1">
                              <span className="font-medium text-foreground">
                                {t('managed.quickstart.safetyPlan.audit')}
                              </span>
                              <p className="text-[11px] leading-4 text-muted-foreground">
                                {t('managed.quickstart.safetyPlan.hint.audit')}
                              </p>
                            </div>
                            <div className="flex shrink-0 items-center gap-2">
                              <SafetyPlanStatusBadge
                                tone="ready"
                                label={t('managed.quickstart.safetyPlan.status.automatic')}
                              />
                              <span className="text-right font-medium text-foreground">
                                {t('managed.quickstart.safetyPlan.auditValue')}
                              </span>
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                    <div className="space-y-1 rounded-lg border border-border bg-muted/50 p-3 font-mono text-xs">
                      <div>
                        <span className="text-muted-foreground">agent:</span>{' '}
                        {quickstartAgentId ? shortEntityId(quickstartAgentId, 'agent') : '—'}
                      </div>
                      {quickstartEnvironmentId && (
                        <div>
                          <span className="text-muted-foreground">environment_id:</span>{' '}
                          {shortEntityId(quickstartEnvironmentId, 'environment')}
                        </div>
                      )}
                      {quickstartVaultId && (
                        <div>
                          <span className="text-muted-foreground">credential_group_ids:</span>{' '}
                          {`["${shortEntityId(quickstartVaultId, 'credentialGroup')}"]`}
                        </div>
                      )}
                    </div>
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
                          {trialRunStatus === 'response_received' && (
                            <QuickstartCompletionDescription
                              step={6}
                              className="text-[13px] leading-6 text-foreground/80"
                            />
                          )}
                        </>
                      ) : isQuickstartCompletionStep(currentStep) ? (
                        <StepCompleteCard
                          step={currentStep}
                          curl={curls[currentStep]}
                          endpoint={STEP_API_ENDPOINTS[currentStep] || '/unknown'}
                          onNext={advanceStep}
                          nextLabel={
                            currentStep === 3
                              ? t('managed.quickstart.nextConfigureEnv')
                              : currentStep === 4
                                ? t('managed.quickstart.nextConfigureCredentialGroup')
                                : currentStep === 5
                                  ? t('managed.quickstart.nextStartSession')
                                  : t('common.done')
                          }
                        />
                      ) : null}
                    </>
                  )}

                <div ref={messagesEndRef} />
              </div>

              {currentStep === 6 && !completedSteps.has(6) ? (
                <div
                  data-quickstart-launch-footer
                  className="absolute bottom-4 left-5 right-5 rounded-[14px] border border-border bg-background/95 p-3 shadow-md backdrop-blur"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <p className="line-clamp-2 text-[11px] leading-4 text-muted-foreground">
                        {t(`managed.quickstart.safetyPlan.launchHint.${safetyPlanSummaryKey}`)}
                      </p>
                    </div>
                    <Button
                      className="h-10 shrink-0 rounded-xl px-5 text-sm"
                      disabled={isCreating || currentProjectReadOnly || !resourceIds[3]}
                      onClick={handleCreateSession}
                    >
                      {isCreating ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                      {t('managed.quickstart.startSession')}
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="absolute bottom-4 left-5 right-5 rounded-[14px] border border-border bg-background px-3 py-2.5 shadow-md">
                  <div className="flex items-center gap-2">
                    <input
                      ref={inputRef}
                      type="text"
                      value={inputValue}
                      onChange={(e) => handleInputChange(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && !e.shiftKey) {
                          e.preventDefault()
                          handleSend()
                        }
                      }}
                      disabled={isMainInputDisabled}
                      placeholder={t(mainInputPlaceholderKey)}
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
                  {pendingEngineRecommendation && !selectedEngine ? (
                    <div className="mt-3 rounded-xl border border-primary/20 bg-primary/5 p-3">
                      <p className="text-xs font-semibold text-foreground">
                        {t('managed.quickstart.engineRecommendation.title')}
                      </p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {t('managed.quickstart.engineRecommendation.description')}
                      </p>
                      <div className="mt-3 flex flex-wrap gap-2">
                        {pendingEngineOptions.map((option) => {
                          const engine = option.engine
                          const recommended = option.recommended
                          return (
                            <Button
                              key={engine.id}
                              type="button"
                              size="sm"
                              variant={recommended ? 'default' : 'outline'}
                              disabled={option.readiness === 'unavailable'}
                              onClick={() =>
                                confirmRecommendedEngine(engine.id as QuickstartEngine)
                              }
                            >
                              {recommended
                                ? t('managed.quickstart.engineRecommendation.useRecommended', {
                                    engine:
                                      pendingEngineCapability?.display_name || engine.display_name,
                                  })
                                : engine.display_name}
                              <span className="ml-1 text-[10px] opacity-75">
                                <span>
                                  {t(
                                    option.readiness === 'ready'
                                      ? 'managed.quickstart.engineRecommendation.readyNow'
                                      : option.readiness === 'setup_required'
                                        ? 'managed.quickstart.engineRecommendation.setupRequired'
                                        : 'managed.quickstart.engineRecommendation.unavailable',
                                  )}
                                </span>
                                {option.readiness === 'ready' ? (
                                  <>
                                    {' · '}
                                    <span>
                                      {t(
                                        'managed.quickstart.engineRecommendation.connectionCount',
                                        { count: option.compatibleConnectionCount },
                                      )}
                                    </span>
                                  </>
                                ) : null}
                              </span>
                            </Button>
                          )
                        })}
                      </div>
                    </div>
                  ) : null}
                </div>
              )}
            </section>

            {/* Right panel: config / preview */}
            <section className="relative bg-background">
              <div className="border-b border-border px-4 pt-2.5">
                <div className="flex items-end gap-5">
                  <button
                    className={cn(
                      'pb-2 text-sm font-semibold transition-colors',
                      rightTab === 'blueprint'
                        ? 'border-b-2 border-foreground text-foreground'
                        : 'text-muted-foreground hover:text-foreground',
                    )}
                    onClick={() => setRightTab('blueprint')}
                  >
                    {t('managed.quickstart.blueprint.title')}
                  </button>
                  <button
                    className={cn(
                      'pb-2 text-sm font-semibold transition-colors',
                      rightTab === 'advanced'
                        ? 'border-b-2 border-foreground text-foreground'
                        : 'text-muted-foreground hover:text-foreground',
                    )}
                    onClick={() => setRightTab('advanced')}
                  >
                    {t('managed.quickstart.blueprint.advanced')}
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

              {rightTab === 'blueprint' && (
                <div className="flex h-[calc(100vh-240px)] flex-col">
                  <QuickstartGenerationStatus
                    state={generationState}
                    onCancel={cancelGeneration}
                    onRetry={retryGeneration}
                  />
                  <div className="min-h-0 flex-1">
                    <QuickstartAgentBlueprintReview
                      agentConfig={config.agent}
                      generationStatus={generationState.status}
                      onShowAdvanced={() => setRightTab('advanced')}
                      availableSkills={availableSkills}
                      disabled={currentProjectReadOnly || Boolean(resourceIds[3]) || isCreating}
                      authorizedMcpServerUrls={authorizedMcpServerUrls}
                      isGenericStarter={Boolean(
                        (config.agent?.metadata as Record<string, unknown> | undefined)
                          ?.quickstart_template,
                      )}
                      onSkillsChange={setAgentSkills}
                    />
                  </div>
                </div>
              )}

              {rightTab === 'advanced' && (
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
                        onRetry={() => void refetchTrialTasks()}
                        onViewSession={() => router.push(`/managed/sessions/${sessionId}`)}
                      />
                      <QuickstartCapabilityEvidence evidence={capabilityEvidence} />
                      {(agentBlueprint.acceptanceTest.message ||
                        agentBlueprint.acceptanceTest.checks.length > 0) && (
                        <div className="border-b border-border bg-muted/20 px-4 py-3">
                          <div className="flex items-start gap-2">
                            <ClipboardCheck className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                            <div className="min-w-0 flex-1">
                              <p className="text-sm font-semibold text-foreground">
                                {t('managed.quickstart.trialRun.acceptanceEvidence.title')}
                              </p>
                              <p className="mt-0.5 text-xs leading-5 text-muted-foreground">
                                {t('managed.quickstart.trialRun.acceptanceEvidence.description')}
                              </p>
                              {agentBlueprint.acceptanceTest.message ? (
                                <div className="mt-2 rounded-lg border border-border bg-background px-3 py-2">
                                  <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                                    {t(
                                      'managed.quickstart.trialRun.acceptanceEvidence.testMessage',
                                    )}
                                  </p>
                                  <p className="mt-1 text-sm text-foreground">
                                    {agentBlueprint.acceptanceTest.message}
                                  </p>
                                </div>
                              ) : null}
                              <div className="mt-3 rounded-lg border border-border bg-background px-3 py-2">
                                <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                                  {t(
                                    'managed.quickstart.trialRun.acceptanceEvidence.observableTitle',
                                  )}
                                </p>
                                <p className="mt-0.5 text-[11px] leading-4 text-muted-foreground">
                                  {t(
                                    'managed.quickstart.trialRun.acceptanceEvidence.observableDescription',
                                  )}
                                </p>
                                <div className="mt-2 space-y-1.5">
                                  {observableChecks.map((check) => (
                                    <div
                                      key={check.id}
                                      className="flex items-center justify-between gap-2 text-xs"
                                    >
                                      <div className="flex items-center gap-2">
                                        {check.status === 'passed' ? (
                                          <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-600" />
                                        ) : check.status === 'failed' ? (
                                          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-600" />
                                        ) : (
                                          <span className="h-2 w-2 shrink-0 rounded-full border border-muted-foreground/50" />
                                        )}
                                        <span className="text-foreground/90">
                                          {t(
                                            `managed.quickstart.trialRun.acceptanceEvidence.check.${check.id}`,
                                          )}
                                        </span>
                                      </div>
                                      <span
                                        className={cn(
                                          'text-[11px] font-medium',
                                          check.status === 'passed' && 'text-emerald-600',
                                          check.status === 'failed' && 'text-amber-600',
                                          check.status === 'not_observed' &&
                                            'text-muted-foreground',
                                        )}
                                      >
                                        {t(
                                          check.status === 'passed'
                                            ? 'managed.quickstart.trialRun.acceptanceEvidence.checkStatus.passed'
                                            : check.status === 'failed'
                                              ? 'managed.quickstart.trialRun.acceptanceEvidence.checkStatus.failed'
                                              : 'managed.quickstart.trialRun.acceptanceEvidence.checkStatus.notObserved',
                                        )}
                                      </span>
                                    </div>
                                  ))}
                                </div>
                              </div>
                              {agentBlueprint.acceptanceTest.checks.length > 0 ? (
                                <div className="mt-3">
                                  <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                                    {t(
                                      'managed.quickstart.trialRun.acceptanceEvidence.manualTitle',
                                    )}
                                  </p>
                                  <p className="mt-0.5 text-[11px] leading-4 text-muted-foreground">
                                    {t(
                                      'managed.quickstart.trialRun.acceptanceEvidence.manualDescription',
                                    )}
                                  </p>
                                  <div className="mt-2 space-y-1.5">
                                    {agentBlueprint.acceptanceTest.checks.map((check) => (
                                      <div
                                        key={check}
                                        className="flex items-start gap-2 text-xs text-foreground/90"
                                      >
                                        <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full border border-primary/60" />
                                        <span>{check}</span>
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              ) : null}
                              <div className="mt-3 flex flex-wrap gap-2">
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() => {
                                    setPreviewTab('transcript')
                                    setSelectedPreviewEvent(null)
                                  }}
                                >
                                  {t(
                                    'managed.quickstart.trialRun.acceptanceEvidence.reviewTranscript',
                                  )}
                                </Button>
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() => setPreviewTab('debug')}
                                >
                                  {t('managed.quickstart.trialRun.acceptanceEvidence.reviewDebug')}
                                </Button>
                              </div>
                            </div>
                          </div>
                        </div>
                      )}
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
                            onInput={(e) =>
                              setSessionMessageDraft(e.currentTarget.value, { userEdit: true })
                            }
                            onKeyDown={(e) => {
                              if (e.key === 'Enter' && !e.shiftKey) {
                                e.preventDefault()
                                handleSendSessionMessage()
                              }
                            }}
                            disabled={isSendingMsg || currentProjectReadOnly}
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
                              disabled={
                                isSendingMsg || currentProjectReadOnly || !sessionMsgInput.trim()
                              }
                              className={cn(
                                'inline-flex h-6 w-6 items-center justify-center rounded-md text-xs font-semibold text-primary-foreground shadow-sm transition-colors',
                                isSendingMsg || currentProjectReadOnly || !sessionMsgInput.trim()
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
                        disabled={!resourceIds[3] || isTestRunning || currentProjectReadOnly}
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
