'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import yaml from 'js-yaml'
import { CheckCircle2, Loader2, Play, Sparkles, Square } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useEffect, useMemo, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { useCompatibleCredentials } from '@/hooks/managed/use-compatible-credentials'
import {
  currentProjectAllowsWrite,
  useCurrentProjectReadOnly,
} from '@/hooks/managed/use-current-project-read-only'
import { useLlmCatalog } from '@/hooks/managed/use-llm-catalog'
import { useManagedCredentialGroupOptions } from '@/hooks/managed/use-managed-credential-group-options'
import { useManagedEnvironmentOptions } from '@/hooks/managed/use-managed-environment-options'
import { useManagedSkillOptions } from '@/hooks/managed/use-managed-skill-options'
import {
  useQuickstartController,
  type QuickstartEngine,
  type StepId,
} from '@/hooks/managed/use-quickstart-controller'
import { useQuickstartProveFlow } from '@/hooks/managed/use-quickstart-prove-flow'
import {
  useQuickstartEngineDefaults,
  useQuickstartSecurityDefaults,
} from '@/hooks/managed/use-quickstart-recommendation'
import { useQuickstartSecurityFlow } from '@/hooks/managed/use-quickstart-security-flow'
import { ApiError } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { managedAgentQueryKey } from '@/lib/managed/agent-client'
import {
  fetchManagedCredentialGroupMembers,
  managedCredentialGroupMembersQueryKey,
  managedCredentialGroupOptionsQueryKey,
} from '@/lib/managed/credential-group-client'
import { shortEntityId } from '@/lib/managed/entity-id-display'
import { managedEnvironmentOptionsQueryKey } from '@/lib/managed/environment-client'
import { toastOperationError } from '@/lib/managed/errors'
import { getEnabledEngines } from '@/lib/managed/llm-catalog'
import { normalizeMcpServerConfigs } from '@/lib/managed/mcp-config'
import { summarizeMcpCredentialCoverage } from '@/lib/managed/mcp-credential-coverage'
import { recordCreatedModelConnection } from '@/lib/managed/model-connection-cache'
import { normalizeQuickstartAgentBlueprint } from '@/lib/managed/quickstart-agent-blueprint'
import {
  quickstartAuthorizedMcpServerUrls,
  toQuickstartAvailableSkills,
} from '@/lib/managed/quickstart-capabilities'
import { QUICKSTART_STEP } from '@/lib/managed/quickstart-flow'
import { quickstartInputPlaceholderKey } from '@/lib/managed/quickstart-input-state'
import { deriveQuickstartLaunchAssurance } from '@/lib/managed/quickstart-launch-assurance'
import {
  recommendQuickstartModelConnection,
  type QuickstartModelRecommendationReason,
} from '@/lib/managed/quickstart-model-recommendation'
import { quickstartResourceEndpoint } from '@/lib/managed/quickstart-resource-contract'
import {
  fetchLatestQuickstartTrialTask,
  quickstartTrialTaskQueryKey,
} from '@/lib/managed/quickstart-task-client'
import {
  hasManagedRequestScope,
  managedScopeKey,
  type ManagedRequestScope,
  useManagedRequestScope,
} from '@/lib/managed/request-scope'
import {
  fetchManagedSession,
  managedSessionQueryKey,
  sendManagedSessionUserMessage,
  stopManagedSession,
} from '@/lib/managed/session-client'
import { useSessionStream } from '@/lib/managed/sse'
import { cn } from '@/lib/utils'
import { useProjectStore } from '@/stores/managed/project-store'
import {
  parseCredentialId,
  parseEnvironmentId,
  parseSessionId,
  tryParseAgentId,
  tryParseCredentialGroupId,
  tryParseEnvironmentId,
  type CredentialId,
  type SessionId,
} from '@/types/entity-id'
import type {
  Agent,
  CredentialDetail,
  CredentialGroup,
  Environment,
  Session,
} from '@/types/managed'

import { QuickstartAgentBlueprintReview } from './components/quickstart-agent-blueprint'
import {
  QuickstartCompletionDescription,
  QuickstartCompletionTitle,
  type QuickstartCompletionStep,
} from './components/quickstart-completion-copy'
import {
  QuickstartApiCard,
  QuickstartNumberedChoiceList,
  QuickstartStepDoneBadge,
} from './components/quickstart-flow-primitives'
import { QuickstartGenerationStatus } from './components/quickstart-generation-status'
import { QuickstartLlmStep } from './components/quickstart-llm-step'
import { QuickstartModeToggle, type QuickstartFlowMode } from './components/quickstart-mode-toggle'
import { QuickstartOutcomeRail } from './components/quickstart-outcome-rail'
import {
  QuickstartProveLaunchFooter,
  QuickstartProvePhase,
} from './components/quickstart-prove-phase'
import { QuickstartProvePreview } from './components/quickstart-prove-preview'
import {
  QuickstartReviewNavigation,
  type QuickstartReviewTab,
} from './components/quickstart-review-navigation'
import { QuickstartSecurePhase } from './components/quickstart-secure-phase'
import {
  QUICKSTART_TEMPLATE_IDS,
  QuickstartUnderstandLanding,
} from './components/quickstart-understand-landing'

const MODEL_RECOMMENDATION_REASON_KEYS: Record<QuickstartModelRecommendationReason, string> = {
  onlyCompatible: 'managed.quickstart.modelRecommendation.reason.onlyCompatible',
  preferredProtocolDefault:
    'managed.quickstart.modelRecommendation.reason.preferredProtocolDefault',
  protocolDefault: 'managed.quickstart.modelRecommendation.reason.protocolDefault',
  preferredProtocol: 'managed.quickstart.modelRecommendation.reason.preferredProtocol',
  recentCompatible: 'managed.quickstart.modelRecommendation.reason.recentCompatible',
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

function getCurrentManagedScope() {
  const { currentOrgId, currentProjectId } = useProjectStore.getState()
  return managedScopeKey(currentOrgId, currentProjectId)
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
      <QuickstartApiCard endpoint={endpoint} curl={curl} />
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
  const [rightTab, setRightTab] = useState<QuickstartReviewTab>('blueprint')
  const [flowMode, setFlowMode] = useState<QuickstartFlowMode>('fast')
  const [modelCredentialId, setModelCredentialId] = useState<CredentialId | ''>('')
  const [modelCredentialSelectionCleared, setModelCredentialSelectionCleared] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const configScrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const [inputValue, setInputValue] = useState('')
  const [pendingEngineRecommendation, setPendingEngineRecommendation] = useState<{
    intent: string
  } | null>(null)
  const [templateSearch, setTemplateSearch] = useState('')
  const [selectedEnvId, setSelectedEnvId] = useState<string>('')
  const [localSessionId, setLocalSessionId] = useState<SessionId | null>(null)
  const [isTestRunning, setIsTestRunning] = useState(false)
  const [isStoppingSession, setIsStoppingSession] = useState(false)
  const managedScopeRef = useRef(managedScope.key)
  const managedRequestScopeRef = useRef<ManagedRequestScope>(managedScope)
  const pageActionRunRef = useRef(0)

  useEffect(() => {
    if (managedScopeRef.current === managedScope.key) return
    managedScopeRef.current = managedScope.key
    managedRequestScopeRef.current = managedScope
    pageActionRunRef.current += 1
    setSelectedEnvId('')
    setModelCredentialId('')
    setModelCredentialSelectionCleared(false)
    setPendingEngineRecommendation(null)
    setLocalSessionId(null)
    setIsTestRunning(false)
    setIsStoppingSession(false)
    sessionMsgDraftVersionRef.current += 1
    sessionMsgInputRef.current = ''
    setSessionMsgInput('')
    setIsSendingMsg(false)
  }, [managedScope])

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

  const { data: environments } = useManagedEnvironmentOptions({ refetchOnMount: 'always' })

  const { data: credentialGroups } = useManagedCredentialGroupOptions({
    refetchOnMount: 'always',
  })

  const { data: skillRecords } = useManagedSkillOptions({ refetchOnMount: 'always' })
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
    selectModelCredential,
    advanceStep,
    skipStep,
    setAgentSkills,
    confirmStep,
    keepRefining,
    createSession,
    createTrialSession,
    createEnvironment,
    selectExistingEnvironment,
    createCredentialGroup,
    selectExistingCredentialGroup,
    goToStep,
    reopenStep,
    generateTestMessage,
  } = useQuickstartController(modelCredentialId, { availableSkills })

  const compatibleCredentialsQuery = useCompatibleCredentials({
    engineId: selectedEngine ?? '',
    enabled: Boolean(selectedEngine),
  })
  const compatibleCredentials = compatibleCredentialsQuery.data
  const engineDefaults = useQuickstartEngineDefaults({
    intent: pendingEngineRecommendation?.intent ?? '',
    enabled: !selectedEngine && pendingEngineRecommendation !== null,
  })
  const pendingEngineOptions = useMemo(
    () =>
      engineDefaults.options.flatMap((option) => {
        const engine = catalogEngines.find((candidate) => candidate.id === option.engineId)
        return engine ? [{ ...option, engine }] : []
      }),
    [catalogEngines, engineDefaults.options],
  )

  const selectedCredential = useMemo(() => {
    return compatibleCredentials?.find((credential) => credential.id === modelCredentialId)
  }, [compatibleCredentials, modelCredentialId])

  const selectedCredentialCompatible = Boolean(selectedCredential)
  const hasQuickstartIntent = useMemo(
    () => messages.some((message) => message.role === 'user') || Boolean(config.agent),
    [config.agent, messages],
  )
  const selectedEngineCapability = useMemo(
    () => enabledEngines.find((engine) => engine.id === selectedEngine) ?? null,
    [enabledEngines, selectedEngine],
  )
  const modelRecommendation = useMemo(
    () => recommendQuickstartModelConnection(compatibleCredentials ?? [], selectedEngineCapability),
    [compatibleCredentials, selectedEngineCapability],
  )
  const securityIntent = useMemo(
    () =>
      messages
        .filter((message) => message.role === 'user')
        .map((message) => message.content)
        .join('\n'),
    [messages],
  )
  const securityRecommendation = useQuickstartSecurityDefaults({
    intent: securityIntent,
    agentConfig: config.agent,
    enabled: currentStep >= QUICKSTART_STEP.ENVIRONMENT,
  })
  const suggestedAllowlist = securityRecommendation.defaults.recommendedHosts.join(', ')
  const securityFlow = useQuickstartSecurityFlow({
    scopeKey: managedScope.key,
    suggestedAllowlist,
    recommendedMcpServers: securityRecommendation.defaults.recommendedMcpServers,
  })
  const { answers: envAnswers, pendingId: pendingEnvId } = securityFlow.environment
  const { pendingId: pendingCredentialGroupId } = securityFlow.credentialGroup

  useEffect(() => {
    if (!selectedEngine || !compatibleCredentialsQuery.isSuccess || !compatibleCredentials) return
    const compatibleIds = new Set<CredentialId>(
      compatibleCredentials.map((credential) => credential.id),
    )
    if (modelCredentialId) {
      if (compatibleIds.has(modelCredentialId)) return
      setModelCredentialId('')
      setModelCredentialSelectionCleared(true)
      return
    }
    if (modelCredentialSelectionCleared) return
    if (modelRecommendation) {
      const recommendedId = modelRecommendation.credential.id
      setModelCredentialId(recommendedId)
      if (hasQuickstartIntent && modelRecommendation.autoContinue) {
        selectModelCredential(recommendedId)
      }
    }
  }, [
    compatibleCredentials,
    compatibleCredentialsQuery.isSuccess,
    hasQuickstartIntent,
    modelRecommendation,
    modelCredentialId,
    modelCredentialSelectionCleared,
    selectModelCredential,
    selectedEngine,
  ])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const isLanding = messages.length === 0 && !isStreaming
  const quickstartAgentId = tryParseAgentId(resourceIds[QUICKSTART_STEP.AGENT])
  const quickstartEnvironmentId = tryParseEnvironmentId(resourceIds[QUICKSTART_STEP.ENVIRONMENT])
  const quickstartCredentialGroupId = tryParseCredentialGroupId(
    resourceIds[QUICKSTART_STEP.CREDENTIAL_GROUP],
  )
  const rawSessionId = resourceIds[QUICKSTART_STEP.SESSION] || localSessionId
  const sessionId = rawSessionId ? parseSessionId(rawSessionId) : null
  const isSessionActive = !!sessionId

  // Real MCP authorization: a credential group only authorizes an agent's MCP
  // server when it actually holds a member credential for that server URL.
  const { data: quickstartCredentialGroupMembers } = useQuery({
    queryKey: managedCredentialGroupMembersQueryKey(
      managedScope.key,
      quickstartCredentialGroupId,
      false,
    ),
    queryFn: () =>
      fetchManagedCredentialGroupMembers(quickstartCredentialGroupId!, false, managedScope),
    enabled: Boolean(quickstartCredentialGroupId) && hasManagedRequestScope(managedScope),
  })
  const authorizedMcpServerUrls = useMemo(
    () => quickstartAuthorizedMcpServerUrls(quickstartCredentialGroupMembers ?? []),
    [quickstartCredentialGroupMembers],
  )
  const agentMcpServers = useMemo(
    () => (quickstartAgentId ? normalizeMcpServerConfigs(config.agent?.mcp_servers) : []),
    [config.agent, quickstartAgentId],
  )
  const agentMcpServerUrls = useMemo(() => {
    return agentMcpServers.flatMap((server) => (server.type === 'local_stdio' ? [] : [server.url]))
  }, [agentMcpServers])
  const mcpCredentialCoverage = useMemo(
    () => summarizeMcpCredentialCoverage(agentMcpServers, quickstartCredentialGroupMembers ?? []),
    [agentMcpServers, quickstartCredentialGroupMembers],
  )
  const externalToolsAuthorized = !mcpCredentialCoverage.blocking
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

  const { data: trialTask, refetch: refetchTrialTasks } = useQuery({
    queryKey: quickstartTrialTaskQueryKey(managedScope.key, sessionId),
    queryFn: () => {
      if (!sessionId) {
        return Promise.resolve(null)
      }
      return fetchLatestQuickstartTrialTask(sessionId, managedScope)
    },
    enabled: isSessionActive && hasTrialUserMessage && hasManagedRequestScope(managedScope),
    refetchOnMount: 'always',
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'pending' || status === 'scheduling' || status === 'running' ? 3000 : false
    },
  })

  const { data: activeSession } = useQuery({
    queryKey: managedSessionQueryKey(managedScope.key, sessionId!),
    queryFn: () => fetchManagedSession(sessionId!, managedScope),
    enabled: isSessionActive && hasManagedRequestScope(managedScope),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'running' ? 3000 : false
    },
  })

  const proveFlow = useQuickstartProveFlow({
    scopeKey: managedScope.key,
    isSessionActive,
    sessionStatus: activeSession?.status,
    events: sessionEvents,
    task: trialTask ?? null,
    environmentId: quickstartEnvironmentId,
    externalToolsAuthorized,
    agentConfig: config.agent,
    agentMcpServerUrls,
    availableSkills,
  })
  const { status: trialRunStatus, isSessionRunning } = proveFlow.trial

  useEffect(() => {
    if (isSessionActive) setRightTab('preview')
  }, [isSessionActive])

  // Restore the user's last Fast Track / Expert preference.
  useEffect(() => {
    const saved = window.localStorage.getItem('quickstart-flow-mode')
    if (saved === 'expert' || saved === 'fast') setFlowMode(saved)
  }, [])
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

  const handleStopSession = async () => {
    if (!sessionId || isStoppingSession || !currentPageProjectAllowsWrite()) return
    const requestScope = managedRequestScopeRef.current
    const currentSession = queryClient.getQueryData<Session>(
      managedSessionQueryKey(requestScope.key, sessionId),
    )
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
    const targetSessionId = sessionId
    setIsStoppingSession(true)
    try {
      await stopManagedSession(targetSessionId, requestScope)
      if (!isCurrentPageAction(runId, scope)) return
      queryClient.invalidateQueries({ queryKey: managedSessionQueryKey(scope, targetSessionId) })
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
    const currentSession = queryClient.getQueryData<Session>(
      managedSessionQueryKey(requestScope.key, sessionId),
    )
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
      await sendManagedSessionUserMessage(targetSessionId, text, requestScope)
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
    return environments || []
  }, [environments])
  const quickstartEnvironment = useMemo(() => {
    const persisted = activeEnvironments.find(
      (environment) => environment.id === quickstartEnvironmentId,
    )
    if (persisted) return persisted
    const createdConfig = config.environment
    if (
      !quickstartEnvironmentId ||
      !createdResourceIds.has(quickstartEnvironmentId) ||
      !createdConfig
    ) {
      return null
    }
    return {
      id: quickstartEnvironmentId,
      name: String(createdConfig.name || 'quickstart-environment'),
      description: String(createdConfig.description || ''),
      config:
        createdConfig.config && typeof createdConfig.config === 'object'
          ? (createdConfig.config as Environment['config'])
          : undefined,
      created_at: '',
      updated_at: '',
    }
  }, [activeEnvironments, config.environment, createdResourceIds, quickstartEnvironmentId])
  const quickstartLaunchAssurance = useMemo(
    () =>
      deriveQuickstartLaunchAssurance({
        hasRuntime: Boolean(selectedEngine),
        hasModelConnection: Boolean(selectedCredential),
        environment: quickstartEnvironment,
        recommendedHosts: securityRecommendation.defaults.recommendedHosts,
        mcpServers: agentMcpServers,
        credentialGroupMembers: quickstartCredentialGroupMembers ?? [],
      }),
    [
      agentMcpServers,
      quickstartCredentialGroupMembers,
      quickstartEnvironment,
      securityRecommendation.defaults.recommendedHosts,
      selectedCredential,
      selectedEngine,
    ],
  )

  const activeCredentialGroups = useMemo(() => {
    return credentialGroups || []
  }, [credentialGroups])

  const readCurrentActiveEnvironments = () => {
    const currentEnvironmentData = queryClient.getQueryData<Environment[]>(
      managedEnvironmentOptionsQueryKey(managedScope.key),
    )
    return currentEnvironmentData || activeEnvironments
  }

  const readCurrentActiveCredentialGroups = () => {
    const currentCredentialGroupsData = queryClient.getQueryData<CredentialGroup[]>(
      managedCredentialGroupOptionsQueryKey(managedScope.key),
    )
    return currentCredentialGroupsData || activeCredentialGroups
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

  const confirmSelectedCredentialGroup = () => {
    if (!currentPageProjectAllowsWrite()) return
    if (!pendingCredentialGroupId) {
      advanceStep()
      return
    }
    const currentCredentialGroup = readCurrentActiveCredentialGroups().find(
      (credentialGroup) => credentialGroup.id === pendingCredentialGroupId,
    )
    if (!currentCredentialGroup) return
    selectExistingCredentialGroup(currentCredentialGroup.id)
    advanceStep()
  }

  const currentSessionAgentIsActive = () => {
    if (!currentProjectAllowsWrite()) return false
    const agentId = tryParseAgentId(resourceIds[QUICKSTART_STEP.AGENT])
    if (!agentId) return false
    const currentAgent = queryClient.getQueryData<Agent>(
      managedAgentQueryKey(managedScope.key, agentId),
    )
    if (currentAgent) return currentAgent.id === agentId && !currentAgent.archived_at
    return createdResourceIds.has(agentId)
  }

  const resolveSessionEnvironmentId = () => {
    const envId = tryParseEnvironmentId(resourceIds[QUICKSTART_STEP.ENVIRONMENT])
    if (!envId) return null
    const currentEnvironmentData = queryClient.getQueryData<Environment[]>(
      managedEnvironmentOptionsQueryKey(managedScope.key),
    )
    const currentEnvRecord = currentEnvironmentData?.find((env) => env.id === envId)
    if (currentEnvRecord?.archived_at) return null
    if (readCurrentActiveEnvironments().some((env) => env.id === envId)) return envId
    return createdResourceIds.has(envId) ? envId : null
  }

  const resolveSessionCredentialGroupId = () => {
    const credentialGroupId = tryParseCredentialGroupId(
      resourceIds[QUICKSTART_STEP.CREDENTIAL_GROUP],
    )
    if (!credentialGroupId) return null
    const currentCredentialGroupsData = queryClient.getQueryData<CredentialGroup[]>(
      managedCredentialGroupOptionsQueryKey(managedScope.key),
    )
    const currentCredentialGroupRecord = currentCredentialGroupsData?.find(
      (credentialGroup) => credentialGroup.id === credentialGroupId,
    )
    if (currentCredentialGroupRecord?.archived_at) return null
    if (
      readCurrentActiveCredentialGroups().some(
        (credentialGroup) => credentialGroup.id === credentialGroupId,
      )
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

  // Auto-switch to preview and generate test message when session is created
  useEffect(() => {
    const sid = resourceIds[QUICKSTART_STEP.SESSION] || localSessionId
    const scopeAtStart = managedScopeRef.current
    const draftVersionAtStart = sessionMsgDraftVersionRef.current
    if (sid) {
      setRightTab('preview')
      generateTestMessage().then((msg) => {
        if (
          managedScopeRef.current === scopeAtStart &&
          sid === (resourceIds[QUICKSTART_STEP.SESSION] || localSessionId) &&
          msg &&
          sessionMsgDraftVersionRef.current === draftVersionAtStart &&
          !sessionMsgInputRef.current.trim()
        ) {
          setSessionMessageDraft(msg)
        }
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resourceIds[QUICKSTART_STEP.SESSION], localSessionId])

  // Sync environment created in quickstart to the preview panel dropdown
  useEffect(() => {
    const quickstartEnvId = tryParseEnvironmentId(resourceIds[QUICKSTART_STEP.ENVIRONMENT])
    if (!quickstartEnvId) return

    setSelectedEnvId(quickstartEnvId)
    if (!createdResourceIds.has(quickstartEnvId)) return
    queryClient.setQueryData<Environment[] | undefined>(
      managedEnvironmentOptionsQueryKey(managedScope.key),
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
  }, [resourceIds[QUICKSTART_STEP.ENVIRONMENT], createdResourceIds])

  const handleEnvSkip = () => {
    skipStep(QUICKSTART_STEP.ENVIRONMENT)
  }

  const handleCredentialGroupSkip = () => {
    skipStep(QUICKSTART_STEP.CREDENTIAL_GROUP)
  }

  const handleSecurityPlanEdit = (step: StepId) => {
    if (!currentPageProjectAllowsWrite()) return
    reopenStep(step)
    setRightTab('blueprint')
    setLocalSessionId(null)
    setIsTestRunning(false)
    if (step <= QUICKSTART_STEP.MODEL_CONNECTION) {
      setModelCredentialId('')
      setModelCredentialSelectionCleared(true)
    }
    if (step <= QUICKSTART_STEP.ENVIRONMENT) {
      setSelectedEnvId('')
    }
    securityFlow.resetFromStep(step)
  }

  const handleTestRun = async () => {
    if (!resourceIds[QUICKSTART_STEP.AGENT] || !currentPageProjectAllowsWrite()) return
    const { runId, scope } = nextPageAction()
    setIsTestRunning(true)
    try {
      const requestScope = managedRequestScopeRef.current
      const currentEnvironmentData = queryClient.getQueryData<Environment[]>(
        managedEnvironmentOptionsQueryKey(requestScope.key),
      )
      const currentActiveEnvironments = readCurrentActiveEnvironments()
      const currentSelectedEnv = currentActiveEnvironments.find((env) => env.id === selectedEnvId)
      const currentSelectedEnvRecord = currentEnvironmentData?.find(
        (env) => env.id === selectedEnvId,
      )
      const selectedEnvIsCurrentQuickstartResource =
        selectedEnvId === resourceIds[QUICKSTART_STEP.ENVIRONMENT] &&
        createdResourceIds.has(selectedEnvId) &&
        !currentSelectedEnvRecord?.archived_at
      const selectedEnvCanBeSubmitted =
        !!currentSelectedEnv || selectedEnvIsCurrentQuickstartResource
      const environmentId =
        selectedEnvId && selectedEnvCanBeSubmitted
          ? currentSelectedEnv?.id || parseEnvironmentId(selectedEnvId)
          : null
      const sessionId = await createTrialSession({ environmentId })
      if (!sessionId || !isCurrentPageAction(runId, scope)) return
      setLocalSessionId(sessionId)
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
    if (!templateSearch.trim()) return QUICKSTART_TEMPLATE_IDS
    const q = templateSearch.toLowerCase()
    return QUICKSTART_TEMPLATE_IDS.filter(
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
      setPendingEngineRecommendation({ intent: `${templateId} ${name} ${description}` })
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
    if (currentStep === QUICKSTART_STEP.ENVIRONMENT && config.environment) {
      return config.environment
    }
    if (currentStep === QUICKSTART_STEP.CREDENTIAL_GROUP && config.credentialGroup) {
      return config.credentialGroup
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
        currentStep === QUICKSTART_STEP.ENVIRONMENT
          ? t('managed.quickstart.resourceKindEnvironment')
          : currentStep === QUICKSTART_STEP.CREDENTIAL_GROUP
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

  const confirmRecommendedEngine = (engineId: QuickstartEngine) => {
    const text = (pendingEngineRecommendation?.intent || inputValue).trim()
    if (!text || isStreaming || isSessionRunning || !currentPageProjectAllowsWrite()) return
    const selectedOption = pendingEngineOptions.find((option) => option.engineId === engineId)
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
      setPendingEngineRecommendation({ intent: text })
      return
    }
    setPendingEngineRecommendation(null)
    setInputValue('')
    void sendMessage(text)
  }

  const handleQuickstartEngineSelect = (engine: QuickstartEngine) => {
    selectEngine(engine)
  }

  const handleModelCredentialSelect = (credentialId: CredentialId | '') => {
    if (!currentPageProjectAllowsWrite()) return
    const parsedCredentialId = credentialId ? parseCredentialId(credentialId) : ''
    setModelCredentialId(parsedCredentialId)
    setModelCredentialSelectionCleared(false)
    selectModelCredential(parsedCredentialId || undefined)
  }

  const handleInlineModelCredentialCreated = (created: CredentialDetail) => {
    if (!selectedEngine) return
    recordCreatedModelConnection(queryClient, managedScope.key, selectedEngine, created)
    setModelCredentialId(created.id)
    setModelCredentialSelectionCleared(false)
    selectModelCredential(created.id)
  }

  const recommendedPendingEngine = pendingEngineOptions.find((option) => option.recommended)
  const pendingEngineCapability = pendingEngineRecommendation
    ? catalogEngines.find((engine) => engine.id === recommendedPendingEngine?.engineId)
    : null
  const isMainInputBlockedBySetup =
    currentStep !== QUICKSTART_STEP.ENGINE &&
    (!selectedEngine ||
      currentStep === QUICKSTART_STEP.MODEL_CONNECTION ||
      !modelCredentialId ||
      (currentStep >= QUICKSTART_STEP.AGENT &&
        (!modelCredentialId || !selectedCredentialCompatible)))
  const isMainInputDisabled = currentProjectReadOnly || isStreaming || isMainInputBlockedBySetup
  const isMainSendDisabled =
    isMainInputDisabled ||
    isSessionRunning ||
    !inputValue.trim() ||
    engineDefaults.status === 'loading'
  const mainInputPlaceholderKey = quickstartInputPlaceholderKey({
    selectedEngine: selectedEngine ?? '',
    modelCredentialId,
    currentStep,
    selectedCredentialCompatible,
    isSessionRunning,
    isStreaming,
    readyKey: isLanding ? 'managed.quickstart.describeAgent' : 'managed.quickstart.reply',
  })

  const handleFlowModeChange = (nextMode: QuickstartFlowMode) => {
    setFlowMode(nextMode)
    window.localStorage.setItem('quickstart-flow-mode', nextMode)
    // Switching mode is an explicit user action, so it's safe to retarget the
    // review panel: Expert opens the config/curl editor, Fast the blueprint.
    if (!isSessionActive) {
      setRightTab(nextMode === 'expert' ? 'advanced' : 'blueprint')
    }
  }

  return (
    <div className="w-full">
      <div className="flex items-center justify-between gap-3 px-1 pt-1">
        <h1 className="text-lg font-semibold text-foreground">{t('managed.quickstart.title')}</h1>
        {!isLanding ? (
          <QuickstartModeToggle mode={flowMode} onChange={handleFlowModeChange} />
        ) : null}
      </div>

      <QuickstartOutcomeRail
        currentStep={currentStep}
        completedSteps={completedSteps}
        skippedSteps={skippedSteps}
        trialStatus={trialRunStatus}
      />

      {!isLanding && (isSessionActive || Boolean(resourceIds[QUICKSTART_STEP.AGENT])) && (
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
              disabled={
                !resourceIds[QUICKSTART_STEP.AGENT] || isTestRunning || currentProjectReadOnly
              }
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
        <QuickstartUnderstandLanding
          inputRef={inputRef}
          inputValue={inputValue}
          onInputChange={handleInputChange}
          onSend={handleSend}
          inputDisabled={isMainInputDisabled}
          sendDisabled={isMainSendDisabled}
          inputPlaceholderKey={mainInputPlaceholderKey}
          showEngineRecommendation={Boolean(pendingEngineRecommendation && !selectedEngine)}
          recommendationStatus={engineDefaults.status}
          onRetryRecommendation={engineDefaults.retry}
          engineOptions={pendingEngineOptions}
          recommendedEngineName={pendingEngineCapability?.display_name}
          onConfirmEngine={(engineId) => confirmRecommendedEngine(engineId as QuickstartEngine)}
          templateSearch={templateSearch}
          onTemplateSearchChange={setTemplateSearch}
          filteredTemplateIds={filteredTemplates}
          templatesDisabled={currentProjectReadOnly}
          onTemplateClick={handleTemplateClick}
        />
      ) : (
        <div className="rounded-2xl border border-border bg-card p-2 shadow-sm">
          <div className="grid min-h-[calc(100vh-168px)] gap-0 lg:grid-cols-[420px_minmax(0,1fr)]">
            {/* Left panel: chat */}
            <section className="relative border-r border-border bg-background px-5 pb-16 pt-5">
              <div className="h-[calc(100vh-250px)] space-y-4 overflow-y-auto pr-1">
                {messages.map((msg) => (
                  <ChatBubble key={msg.id} message={msg} />
                ))}

                {currentStep === QUICKSTART_STEP.ENGINE &&
                  !completedSteps.has(QUICKSTART_STEP.ENGINE) &&
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
                    <QuickstartNumberedChoiceList
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

                {currentStep === QUICKSTART_STEP.MODEL_CONNECTION &&
                  !completedSteps.has(QUICKSTART_STEP.MODEL_CONNECTION) &&
                  selectedEngine && (
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
                            <span className="font-medium">
                              {modelRecommendation.credential.name}
                            </span>
                            <span className="text-xs leading-5 text-muted-foreground">
                              {t(MODEL_RECOMMENDATION_REASON_KEYS[modelRecommendation.reason])}
                            </span>
                          </div>
                        </div>
                      ) : null}
                      <QuickstartLlmStep
                        key={selectedEngine}
                        engineId={selectedEngine}
                        value={modelCredentialId}
                        disabled={currentProjectReadOnly}
                        onSelect={handleModelCredentialSelect}
                        onCreated={handleInlineModelCredentialCreated}
                      />
                      {modelCredentialId ? (
                        <Button
                          type="button"
                          className="h-10 rounded-xl px-5 text-sm font-semibold"
                          onClick={() => handleModelCredentialSelect(modelCredentialId)}
                          disabled={currentProjectReadOnly}
                        >
                          {t('managed.quickstart.useSelectedModelConnection')}
                        </Button>
                      ) : null}
                    </div>
                  )}

                {/* Step 2 model connection: show completed badge before the next step actions */}
                {currentStep > QUICKSTART_STEP.MODEL_CONNECTION &&
                  completedSteps.has(QUICKSTART_STEP.MODEL_CONNECTION) &&
                  selectedCredential && (
                    <QuickstartStepDoneBadge
                      label={`${t('managed.quickstart.stepComplete.modelCredentialSelected')}: ${selectedCredential.name}`}
                    />
                  )}
                {pendingConfirmation && pendingConfirmation.step === currentStep && (
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
                      ) : currentStep === QUICKSTART_STEP.AGENT ? (
                        t('managed.quickstart.createThisAgent')
                      ) : currentStep === QUICKSTART_STEP.ENVIRONMENT ? (
                        t('managed.quickstart.createThisEnvironment')
                      ) : currentStep === QUICKSTART_STEP.CREDENTIAL_GROUP ? (
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
                )}

                {currentStep > QUICKSTART_STEP.AGENT &&
                completedSteps.has(QUICKSTART_STEP.AGENT) ? (
                  <QuickstartStepDoneBadge
                    label={`${t('managed.quickstart.stepComplete.agentCreated')}${config.agent?.name ? `: ${config.agent.name}` : ''}`}
                    curl={curls[QUICKSTART_STEP.AGENT]}
                    endpoint={quickstartResourceEndpoint(QUICKSTART_STEP.AGENT)}
                  />
                ) : null}
                <QuickstartSecurePhase
                  currentStep={currentStep}
                  completedSteps={completedSteps}
                  pendingConfirmation={Boolean(pendingConfirmation)}
                  isCreating={isCreating}
                  readOnly={currentProjectReadOnly}
                  curls={curls}
                  controller={securityFlow}
                  recommendation={securityRecommendation}
                  resources={{
                    environments: activeEnvironments,
                    credentialGroups: activeCredentialGroups,
                    resolveEnvironment: (environmentId) =>
                      readCurrentActiveEnvironments().find(
                        (environment) => environment.id === environmentId,
                      ) || null,
                    resolveCredentialGroup: (credentialGroupId) =>
                      readCurrentActiveCredentialGroups().find(
                        (credentialGroup) => credentialGroup.id === credentialGroupId,
                      ) || null,
                  }}
                  actions={{
                    confirmEnvironment: confirmSelectedEnvironment,
                    confirmCredentialGroup: confirmSelectedCredentialGroup,
                    createEnvironment,
                    createCredentialGroup,
                    skipEnvironment: handleEnvSkip,
                    skipCredentialGroup: handleCredentialGroupSkip,
                    advance: advanceStep,
                  }}
                />
                <QuickstartProvePhase
                  currentStep={currentStep}
                  completed={completedSteps.has(QUICKSTART_STEP.SESSION)}
                  curl={curls[QUICKSTART_STEP.SESSION]}
                  controller={proveFlow}
                  plan={{
                    engineId: selectedEngine,
                    engineName: selectedEngineCapability?.display_name || selectedEngine || '',
                    hasModelConnection: Boolean(selectedCredential),
                    modelCredentialName: selectedCredential?.name || '',
                    agentId: quickstartAgentId,
                    environmentId: quickstartEnvironmentId,
                    credentialGroupId: quickstartCredentialGroupId,
                  }}
                  assurance={quickstartLaunchAssurance}
                  readOnly={currentProjectReadOnly}
                  onEdit={handleSecurityPlanEdit}
                />
                {currentStep === QUICKSTART_STEP.AGENT &&
                completedSteps.has(QUICKSTART_STEP.AGENT) &&
                curls[QUICKSTART_STEP.AGENT] ? (
                  <StepCompleteCard
                    step={QUICKSTART_STEP.AGENT}
                    curl={curls[QUICKSTART_STEP.AGENT]}
                    endpoint={quickstartResourceEndpoint(QUICKSTART_STEP.AGENT)}
                    onNext={advanceStep}
                    nextLabel={t('managed.quickstart.nextConfigureEnv')}
                  />
                ) : null}

                <div ref={messagesEndRef} />
              </div>

              {currentStep === QUICKSTART_STEP.SESSION &&
              !completedSteps.has(QUICKSTART_STEP.SESSION) ? (
                <QuickstartProveLaunchFooter
                  needsHardening={quickstartLaunchAssurance.needsHardening}
                  blocked={quickstartLaunchAssurance.externalTools === 'not_authorized'}
                  disabled={
                    isCreating ||
                    currentProjectReadOnly ||
                    !resourceIds[QUICKSTART_STEP.AGENT] ||
                    quickstartLaunchAssurance.externalTools === 'not_authorized'
                  }
                  isCreating={isCreating}
                  onStart={handleCreateSession}
                />
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
              <QuickstartReviewNavigation
                mode={flowMode}
                activeTab={rightTab}
                onChange={setRightTab}
              />

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
                      disabled={
                        currentProjectReadOnly ||
                        Boolean(resourceIds[QUICKSTART_STEP.AGENT]) ||
                        isCreating
                      }
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

              {rightTab === 'preview' ? (
                <QuickstartProvePreview
                  controller={proveFlow}
                  session={{
                    active: isSessionActive,
                    selectedEnvironmentName,
                    selectedEnvironmentId: selectedEnvId,
                    environments: activeEnvironments,
                    acceptanceTest: agentBlueprint.acceptanceTest,
                    message: sessionMsgInput,
                    isSendingMessage: isSendingMsg,
                    isTestRunning,
                    canTest: Boolean(resourceIds[QUICKSTART_STEP.AGENT]),
                    readOnly: currentProjectReadOnly,
                  }}
                  actions={{
                    selectEnvironment: setSelectedEnvId,
                    viewSession: () => router.push(`/managed/sessions/${rawSessionId}`),
                    goBack: () => goToStep(QUICKSTART_STEP.ENGINE),
                    continue: advanceStep,
                    retryTrialStatus: () => void refetchTrialTasks(),
                    changeMessage: (message) => setSessionMessageDraft(message, { userEdit: true }),
                    sendMessage: handleSendSessionMessage,
                    startTest: handleTestRun,
                  }}
                />
              ) : null}
            </section>
          </div>
        </div>
      )}
    </div>
  )
}
