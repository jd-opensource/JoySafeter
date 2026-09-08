'use client'

import { useState, useCallback, useRef, useEffect, useMemo, useReducer } from 'react'

import { API_BASE, ApiError, apiStream, managedPost } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { getOperationErrorMessage } from '@/lib/managed/errors'
import { normalizeQuickstartAgentBlueprint } from '@/lib/managed/quickstart-agent-blueprint'
import {
  filterQuickstartSkillReferences,
  type QuickstartAvailableSkill,
} from '@/lib/managed/quickstart-capabilities'
import { buildQuickstartAgentCreateBody } from '@/lib/managed/quickstart-create'
import {
  INITIAL_QUICKSTART_PROGRESS,
  QUICKSTART_DESIGN_STEP,
  QUICKSTART_STEP,
  reduceQuickstartFlow,
  type QuickstartCreatedResourceStepId,
  type QuickstartOptionalStepId,
  type QuickstartResourceStepId,
  type QuickstartStepId,
} from '@/lib/managed/quickstart-flow'
import {
  inferQuickstartGenerationPhase,
  type QuickstartGenerationPhase,
} from '@/lib/managed/quickstart-generation-progress'
import { normalizeQuickstartAllowedHosts } from '@/lib/managed/quickstart-networking'
import {
  type QuickstartArtifact,
  type QuickstartPhase,
} from '@/lib/managed/quickstart-recommendation-contract'
import {
  isQuickstartCreatedResourceStep,
  parseQuickstartResourceId,
  quickstartResourceApiPath,
} from '@/lib/managed/quickstart-resource-contract'
import {
  managedRequestOptions,
  managedScopeKey,
  type ManagedRequestScope,
  useManagedRequestScope,
} from '@/lib/managed/request-scope'
import {
  buildManagedSessionCreateBody,
  createManagedSession,
  type ManagedSessionCreateBody,
  type ManagedSessionCreateInput,
} from '@/lib/managed/session-client'
import { generateUUID } from '@/lib/utils/uuid'
import { useProjectStore } from '@/stores/managed/project-store'
import {
  parseAgentId,
  type CredentialId,
  parseEnvironmentId,
  parseCredentialGroupId,
  type EnvironmentId,
  type CredentialGroupId,
  type SessionId,
  type SkillId,
} from '@/types/entity-id'

import { currentProjectAllowsWrite } from './use-current-project-read-only'

export type StepId = QuickstartStepId
export type QuickstartEngine = string

export interface QuickstartMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  isStreaming?: boolean
}

export interface QuickstartConfig {
  agent?: Record<string, unknown>
  environment?: Record<string, unknown>
  credentialGroup?: Record<string, unknown>
}

export interface QuickstartTemplateConfig {
  message: string
  agent: Record<string, unknown>
}

export type QuickstartGenerationStatus = 'idle' | 'generating' | 'complete' | 'cancelled' | 'error'

export interface QuickstartGenerationState {
  status: QuickstartGenerationStatus
  phase: QuickstartGenerationPhase
  elapsedSeconds: number
  hasPartialConfig: boolean
  errorMessage?: string
}

interface SendMessageOptions {
  stepOverride?: StepId
  hidden?: boolean
  engineKindOverride?: QuickstartEngine
  modelCredentialIdOverride?: CredentialId
}

interface CreateSessionOptions {
  environmentId?: EnvironmentId | null
  credentialGroupId?: CredentialGroupId | null
}

interface CreateTrialSessionOptions {
  environmentId?: EnvironmentId | null
}

interface CreatedSession {
  id: SessionId
  requestBody: ManagedSessionCreateBody
}

interface CreateCredentialGroupOptions {
  credentials?: Array<{
    name?: string
    mcpServerUrl: string
    tokenValue: string
    authRequirement: 'required' | 'optional' | 'none'
  }>
}

interface QuickstartControllerOptions {
  availableSkills?: QuickstartAvailableSkill[]
}

function getCurrentManagedScope() {
  const { currentOrgId, currentProjectId } = useProjectStore.getState()
  return managedScopeKey(currentOrgId, currentProjectId)
}

interface QuickstartEvent {
  type: 'text_delta' | 'config_update' | 'phase_complete' | 'error' | 'done'
  text?: string
  phase?: QuickstartPhase
  artifact?: QuickstartArtifact
  config?: Record<string, unknown>
  message?: string
}

function buildQuickstartCreateCurl(
  step: QuickstartResourceStepId,
  requestBody: Record<string, unknown>,
): string {
  const shellQuotedBody = JSON.stringify(requestBody, null, 2).replaceAll("'", "'\"'\"'")
  return `curl -X POST ${API_BASE}/${quickstartResourceApiPath(step)} \\
  -H "Content-Type: application/json" \\
  -H "x-api-key: $API_KEY" \\
  -d '${shellQuotedBody}'`
}

function unwrapManagedResponse<T = Record<string, unknown>>(payload: unknown): T {
  if (payload && typeof payload === 'object' && 'success' in payload && 'data' in payload) {
    return (payload as { data: T }).data
  }
  return payload as T
}

function getCreatedResourceId(payload: unknown): string | null {
  const data = unwrapManagedResponse<Record<string, unknown>>(payload)
  const id = data?.id
  if (typeof id === 'string') return id

  for (const key of ['agent', 'environment', 'credential_group', 'session']) {
    const nested = data?.[key]
    if (
      nested &&
      typeof nested === 'object' &&
      typeof (nested as { id?: unknown }).id === 'string'
    ) {
      return (nested as { id: string }).id
    }
  }

  return null
}

function toApiStatusError(error: unknown): Error {
  if (error instanceof ApiError) {
    return new Error(`API ${error.status}: ${error.detail || error.message}`)
  }
  return error instanceof Error ? error : new Error(String(error))
}

export function useQuickstartController(
  modelCredentialId: CredentialId | '',
  { availableSkills = [] }: QuickstartControllerOptions = {},
) {
  const { t } = useTranslation()
  const managedScope = useManagedRequestScope()
  const managedScopeKeyValue = managedScope.key
  const [messages, setMessages] = useState<QuickstartMessage[]>([])
  const messagesRef = useRef<QuickstartMessage[]>([])
  const [flowProgress, dispatchFlow] = useReducer(reduceQuickstartFlow, INITIAL_QUICKSTART_PROGRESS)
  const { currentStep, completedSteps, skippedSteps } = flowProgress
  const [selectedEngine, setSelectedEngine] = useState<QuickstartEngine | null>(null)
  const [config, setConfig] = useState<QuickstartConfig>({})
  const configRef = useRef(config)
  useEffect(() => {
    configRef.current = config
  }, [config])
  const [isStreaming, setIsStreaming] = useState(false)
  const [curls, setCurls] = useState<Record<number, string>>({})
  const [resourceIds, setResourceIds] = useState<Partial<Record<QuickstartResourceStepId, string>>>(
    {},
  )
  const [createdResourceIds, setCreatedResourceIds] = useState<Set<string>>(new Set())
  const [pendingConfirmation, setPendingConfirmation] = useState<{
    step: QuickstartCreatedResourceStepId
  } | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const streamInFlightRef = useRef(false)
  const userCancelledRef = useRef(false)
  const generationStartedAtRef = useRef<number | null>(null)
  const lastGenerationRequestRef = useRef<{
    text: string
    options?: SendMessageOptions
  } | null>(null)
  const [generationState, setGenerationState] = useState<QuickstartGenerationState>({
    status: 'idle',
    phase: 'understanding',
    elapsedSeconds: 0,
    hasPartialConfig: false,
  })
  const [isCreating, setIsCreating] = useState(false)
  const allowedSkillIds = useMemo(
    () => new Set(availableSkills.map((skill) => skill.id)),
    [availableSkills],
  )

  const resourceIdsRef = useRef(resourceIds)
  const managedScopeRef = useRef(managedScopeKeyValue)
  const managedRequestScopeRef = useRef<ManagedRequestScope>(managedScope)
  const lifecycleRunRef = useRef(0)
  const isCurrentManagedScope = useCallback(
    (scope: string) => managedScopeRef.current === scope && getCurrentManagedScope() === scope,
    [],
  )
  const isCurrentWritableManagedScope = useCallback(
    (scope: string) => isCurrentManagedScope(scope) && currentProjectAllowsWrite(),
    [isCurrentManagedScope],
  )
  const isCurrentLifecycleRun = useCallback(
    (scope: string, lifecycleRun: number) =>
      isCurrentManagedScope(scope) && lifecycleRunRef.current === lifecycleRun,
    [isCurrentManagedScope],
  )
  const isCurrentWritableLifecycleRun = useCallback(
    (scope: string, lifecycleRun: number) =>
      isCurrentLifecycleRun(scope, lifecycleRun) && currentProjectAllowsWrite(),
    [isCurrentLifecycleRun],
  )
  useEffect(() => {
    resourceIdsRef.current = resourceIds
  }, [resourceIds])

  useEffect(() => {
    messagesRef.current = messages
  }, [messages])

  useEffect(() => {
    if (generationState.status !== 'generating') return
    const timer = window.setInterval(() => {
      const startedAt = generationStartedAtRef.current
      if (!startedAt) return
      const elapsedSeconds = Math.max(0, Math.floor((Date.now() - startedAt) / 1000))
      setGenerationState((current) => ({
        ...current,
        elapsedSeconds,
        phase: inferQuickstartGenerationPhase({
          elapsedSeconds,
          agentConfig: configRef.current.agent,
        }),
      }))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [generationState.status])

  useEffect(
    () => () => {
      lifecycleRunRef.current += 1
      abortRef.current?.abort()
      abortRef.current = null
      streamInFlightRef.current = false
    },
    [],
  )

  useEffect(() => {
    if (managedScopeRef.current === managedScopeKeyValue) return
    lifecycleRunRef.current += 1
    managedScopeRef.current = managedScopeKeyValue
    managedRequestScopeRef.current = managedScope

    abortRef.current?.abort()
    abortRef.current = null
    streamInFlightRef.current = false
    userCancelledRef.current = false
    generationStartedAtRef.current = null
    lastGenerationRequestRef.current = null
    setIsStreaming(false)
    setGenerationState({
      status: 'idle',
      phase: 'understanding',
      elapsedSeconds: 0,
      hasPartialConfig: false,
    })
    setIsCreating(false)
    setMessages((prev) => {
      const updated = [...prev]
      const last = updated[updated.length - 1]
      if (last && last.role === 'assistant') {
        updated[updated.length - 1] = { ...last, isStreaming: false }
      }
      return updated
    })
    resourceIdsRef.current = {}
    setResourceIds({})
    setCreatedResourceIds(new Set())
    setCurls((prev) =>
      Object.fromEntries(
        Object.entries(prev).filter(([step]) => Number(step) < QUICKSTART_STEP.AGENT),
      ),
    )
    setPendingConfirmation(null)
    dispatchFlow({ type: 'scope_changed', hasEngine: selectedEngine !== null })
  }, [managedScope, managedScopeKeyValue, selectedEngine])

  const sendMessage = useCallback(
    async (text: string, options?: SendMessageOptions) => {
      const trimmedText = text.trim()
      if (streamInFlightRef.current || !trimmedText) return
      const step = options?.stepOverride ?? currentStep
      const hidden = options?.hidden ?? false
      const engineKind = options?.engineKindOverride ?? selectedEngine
      if (!engineKind) return
      const requestModelCredentialId = options?.modelCredentialIdOverride ?? modelCredentialId
      const requestScope = managedRequestScopeRef.current
      const scopeAtStart = requestScope.key
      if (!isCurrentWritableManagedScope(scopeAtStart)) return

      const userMsg: QuickstartMessage = {
        id: generateUUID(),
        role: 'user',
        content: trimmedText,
      }

      const assistantMsg: QuickstartMessage = {
        id: generateUUID(),
        role: 'assistant',
        content: '',
        isStreaming: true,
      }

      const newMessages = [...messages, userMsg]
      if (step <= 2) {
        setMessages(newMessages)
        messagesRef.current = newMessages
        return
      }
      if (step !== QUICKSTART_DESIGN_STEP) return

      const tracksAgentGeneration = step === QUICKSTART_DESIGN_STEP
      if (tracksAgentGeneration) {
        lastGenerationRequestRef.current = { text: trimmedText, options }
        userCancelledRef.current = false
        generationStartedAtRef.current = Date.now()
        setGenerationState({
          status: 'generating',
          phase: 'understanding',
          elapsedSeconds: 0,
          hasPartialConfig: Boolean(configRef.current.agent),
        })
      }

      setMessages((prev) => (hidden ? [...prev, assistantMsg] : [...prev, userMsg, assistantMsg]))
      messagesRef.current = hidden
        ? [...messagesRef.current, assistantMsg]
        : [...newMessages, assistantMsg]
      streamInFlightRef.current = true
      setIsStreaming(true)

      const controller = new AbortController()
      abortRef.current = controller
      let streamErrorMessage: string | null = null
      let receivedDone = false

      try {
        const historyForApi = newMessages.map((m) => ({
          role: m.role,
          content: m.content,
        }))

        const response = await apiStream(
          'quickstart/chat',
          {
            messages: historyForApi,
            phase: 'design',
            engine_kind: engineKind,
            model_credential_id: requestModelCredentialId,
            agent_context: configRef.current.agent,
            available_skills: availableSkills,
          },
          { ...managedRequestOptions(requestScope), signal: controller.signal },
        )

        if (tracksAgentGeneration) {
          setGenerationState((current) => ({ ...current, phase: 'responsibilities' }))
        }

        const reader = response.body!.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        let accumulatedText = ''

        const processLine = (line: string) => {
          if (!line.startsWith('data:')) return
          const data = line.slice(5).trim()
          if (!data || data === '[DONE]') return

          try {
            const event: QuickstartEvent = JSON.parse(data)
            if (!isCurrentWritableManagedScope(scopeAtStart)) return

            switch (event.type) {
              case 'text_delta':
                if (tracksAgentGeneration) {
                  setGenerationState((current) => ({ ...current, phase: 'responsibilities' }))
                }
                accumulatedText += event.text || ''
                setMessages((prev) => {
                  const updated = [...prev]
                  const last = updated[updated.length - 1]
                  if (last && last.role === 'assistant') {
                    updated[updated.length - 1] = {
                      ...last,
                      content: accumulatedText,
                    }
                  }
                  return updated
                })
                break

              case 'config_update':
                if (
                  event.phase === 'design' &&
                  event.artifact === 'agent_blueprint' &&
                  event.config
                ) {
                  setConfig((prev) => {
                    const nextAgent = { ...event.config }
                    if ('skills' in nextAgent) {
                      nextAgent.skills = filterQuickstartSkillReferences(
                        nextAgent.skills,
                        allowedSkillIds,
                      )
                    }
                    return { ...prev, agent: nextAgent }
                  })
                  if (tracksAgentGeneration) {
                    setGenerationState((current) => ({
                      ...current,
                      phase: inferQuickstartGenerationPhase({
                        elapsedSeconds: current.elapsedSeconds,
                        agentConfig: event.config,
                      }),
                      hasPartialConfig: true,
                    }))
                  }
                }
                break

              case 'phase_complete':
                if (event.phase === 'design' && event.artifact === 'agent_blueprint') {
                  setPendingConfirmation({
                    step: QUICKSTART_DESIGN_STEP,
                  })
                  if (tracksAgentGeneration) {
                    setGenerationState((current) => ({ ...current, phase: 'acceptance' }))
                  }
                }
                break

              case 'error':
                streamErrorMessage = event.message || t('managed.quickstart.errors.generic')
                accumulatedText += `\n\n⚠️ ${streamErrorMessage}`
                if (tracksAgentGeneration) {
                  setGenerationState((current) => ({
                    ...current,
                    status: 'error',
                    errorMessage: streamErrorMessage || undefined,
                  }))
                }
                setMessages((prev) => {
                  const updated = [...prev]
                  const last = updated[updated.length - 1]
                  if (last && last.role === 'assistant') {
                    updated[updated.length - 1] = { ...last, content: accumulatedText }
                  }
                  return updated
                })
                break

              case 'done':
                receivedDone = true
                break
            }
          } catch {
            // ignore parse errors for incomplete JSON
          }
        }

        while (true) {
          const { done, value } = await reader.read()
          if (done) {
            if (buffer.trim()) {
              processLine(buffer)
              buffer = ''
            }
            break
          }
          if (!isCurrentWritableManagedScope(scopeAtStart)) break

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''

          for (const line of lines) {
            processLine(line)
          }
        }
        if (
          tracksAgentGeneration &&
          !streamErrorMessage &&
          !receivedDone &&
          !controller.signal.aborted &&
          isCurrentWritableManagedScope(scopeAtStart)
        ) {
          streamErrorMessage = t('managed.quickstart.errors.chatFailed')
          setGenerationState((current) => ({
            ...current,
            status: 'error',
            errorMessage: streamErrorMessage || undefined,
          }))
          setMessages((prev) => {
            const updated = [...prev]
            const last = updated[updated.length - 1]
            if (last && last.role === 'assistant') {
              updated[updated.length - 1] = {
                ...last,
                content: `${last.content}\n\n⚠️ ${streamErrorMessage}`.trim(),
              }
            }
            return updated
          })
        }
      } catch (e) {
        if (tracksAgentGeneration) {
          if ((e as Error).name === 'AbortError' && userCancelledRef.current) {
            setGenerationState((current) => ({ ...current, status: 'cancelled' }))
          } else if ((e as Error).name !== 'AbortError') {
            setGenerationState((current) => ({
              ...current,
              status: 'error',
              errorMessage: getOperationErrorMessage(t, e, 'managed.quickstart.errors.chatFailed'),
            }))
          }
        }
        if ((e as Error).name !== 'AbortError' && abortRef.current === controller) {
          setMessages((prev) => {
            const updated = [...prev]
            const last = updated[updated.length - 1]
            if (last && last.role === 'assistant') {
              updated[updated.length - 1] = {
                ...last,
                content:
                  last.content ||
                  getOperationErrorMessage(t, e, 'managed.quickstart.errors.chatFailed'),
              }
            }
            return updated
          })
        }
      } finally {
        const isActiveStream = abortRef.current === controller
        if (isActiveStream) {
          streamInFlightRef.current = false
          abortRef.current = null
          setIsStreaming(false)
          if (tracksAgentGeneration) {
            generationStartedAtRef.current = null
            if (receivedDone && !streamErrorMessage) {
              setGenerationState((current) =>
                current.status === 'generating' ? { ...current, status: 'complete' } : current,
              )
            }
          }
          setMessages((prev) => {
            const updated = [...prev]
            const last = updated[updated.length - 1]
            if (last && last.role === 'assistant') {
              updated[updated.length - 1] = { ...last, isStreaming: false }
            }
            return updated
          })
        }
      }
    },
    [
      messages,
      currentStep,
      selectedEngine,
      modelCredentialId,
      availableSkills,
      allowedSkillIds,
      isCurrentWritableManagedScope,
      t,
    ],
  )

  const cancelGeneration = useCallback(() => {
    if (!abortRef.current || !streamInFlightRef.current) return
    userCancelledRef.current = true
    setGenerationState((current) => ({ ...current, status: 'cancelled' }))
    abortRef.current.abort()
  }, [])

  const retryGeneration = useCallback(async () => {
    if (streamInFlightRef.current) return
    const lastRequest = lastGenerationRequestRef.current
    if (!lastRequest) return
    await sendMessage(lastRequest.text, lastRequest.options)
  }, [sendMessage])

  const postSession = useCallback(
    async (options: CreateSessionOptions): Promise<CreatedSession | null> => {
      const agentId = resourceIdsRef.current[QUICKSTART_STEP.AGENT]
      const envId =
        'environmentId' in options
          ? options.environmentId || undefined
          : resourceIdsRef.current[QUICKSTART_STEP.ENVIRONMENT]
      const credentialGroupId =
        'credentialGroupId' in options
          ? options.credentialGroupId || undefined
          : resourceIdsRef.current[QUICKSTART_STEP.CREDENTIAL_GROUP]
      if (!agentId) {
        throw new Error(t('managed.quickstart.errors.agentMissingForSession'))
      }

      const requestScope = managedRequestScopeRef.current
      const scopeAtStart = requestScope.key
      if (!isCurrentWritableManagedScope(scopeAtStart)) return null
      const lifecycleRunAtStart = lifecycleRunRef.current
      const createInput: ManagedSessionCreateInput = {
        agentId: parseAgentId(agentId),
        ...(envId ? { environmentId: parseEnvironmentId(envId) } : {}),
        ...(credentialGroupId
          ? { credentialGroupIds: [parseCredentialGroupId(credentialGroupId)] }
          : {}),
      }
      const requestBody = buildManagedSessionCreateBody(createInput)

      const sessionId = await createManagedSession(createInput, requestScope).catch((error) => {
        if (error instanceof ApiError) throw toApiStatusError(error)
        throw new Error(t('managed.quickstart.errors.createSessionFailed'))
      })
      if (!isCurrentWritableLifecycleRun(scopeAtStart, lifecycleRunAtStart)) return null
      return {
        id: sessionId,
        requestBody,
      }
    },
    [isCurrentWritableLifecycleRun, isCurrentWritableManagedScope, t],
  )

  const createSession = useCallback(
    async (options: CreateSessionOptions = {}) => {
      const requestScope = managedRequestScopeRef.current
      const scopeAtStart = requestScope.key
      if (!isCurrentWritableManagedScope(scopeAtStart)) return
      const lifecycleRunAtStart = lifecycleRunRef.current
      setIsCreating(true)
      try {
        const createdSession = await postSession(options)
        if (!createdSession) return

        setResourceIds((prev) => {
          const next = { ...prev, [QUICKSTART_STEP.SESSION]: createdSession.id }
          resourceIdsRef.current = next
          return next
        })

        const sessionCurl = `curl -X POST ${API_BASE}/${quickstartResourceApiPath(QUICKSTART_STEP.SESSION)} \\
  -H "Content-Type: application/json" \\
  -H "x-api-key: $API_KEY" \\
  -d '${JSON.stringify(createdSession.requestBody, null, 2)}'`

        dispatchFlow({ type: 'complete', step: QUICKSTART_STEP.SESSION, advance: false })
        setCurls((prev) => ({ ...prev, [QUICKSTART_STEP.SESSION]: sessionCurl }))
      } catch (err) {
        if (!isCurrentLifecycleRun(scopeAtStart, lifecycleRunAtStart)) return
        setMessages((prev) => [
          ...prev,
          {
            id: generateUUID(),
            role: 'assistant',
            content: getOperationErrorMessage(
              t,
              err,
              'managed.quickstart.errors.createSessionFailed',
            ),
          },
        ])
      } finally {
        if (isCurrentLifecycleRun(scopeAtStart, lifecycleRunAtStart)) {
          setIsCreating(false)
        }
      }
    },
    [isCurrentLifecycleRun, isCurrentWritableManagedScope, postSession, t],
  )

  const createTrialSession = useCallback(
    async ({ environmentId = null }: CreateTrialSessionOptions = {}): Promise<SessionId | null> => {
      const createdSession = await postSession({
        environmentId,
        credentialGroupId: null,
      })
      return createdSession?.id ?? null
    },
    [postSession],
  )

  const createEnvironment = useCallback(
    async (networkType: 'unrestricted' | 'limited', allowedHosts: string[]) => {
      const requestScope = managedRequestScopeRef.current
      const scopeAtStart = requestScope.key
      if (!isCurrentWritableManagedScope(scopeAtStart)) return false
      const lifecycleRunAtStart = lifecycleRunRef.current
      setIsCreating(true)
      try {
        const suffix = `-${Date.now().toString(36).slice(-4)}`
        const normalizedAllowedHosts = normalizeQuickstartAllowedHosts(allowedHosts)
        const envBody = {
          name: `quickstart-env${suffix}`,
          description: '',
          config: {
            type: 'cloud',
            networking: {
              type: networkType,
              allowed_hosts: normalizedAllowedHosts,
            },
          },
        }

        const result = await managedPost(
          quickstartResourceApiPath(QUICKSTART_STEP.ENVIRONMENT),
          envBody,
          managedRequestOptions(requestScope),
        ).catch((error) => {
          throw toApiStatusError(error)
        })
        if (!isCurrentWritableLifecycleRun(scopeAtStart, lifecycleRunAtStart)) return false
        const rawEnvironmentId = getCreatedResourceId(result)
        if (!rawEnvironmentId)
          throw new Error(t('managed.quickstart.errors.createEnvironmentFailed'))
        const environmentId = parseQuickstartResourceId(
          QUICKSTART_STEP.ENVIRONMENT,
          rawEnvironmentId,
        )

        setResourceIds((prev) => {
          const next = { ...prev, [QUICKSTART_STEP.ENVIRONMENT]: environmentId }
          resourceIdsRef.current = next
          return next
        })
        setCreatedResourceIds((prev) => new Set([...prev, environmentId]))
        setConfig((current) => ({ ...current, environment: envBody }))

        const envCurl = `curl -X POST ${API_BASE}/${quickstartResourceApiPath(QUICKSTART_STEP.ENVIRONMENT)} \\
  -H "Content-Type: application/json" \\
  -H "x-api-key: $API_KEY" \\
  -d '${JSON.stringify(envBody, null, 2)}'`

        dispatchFlow({ type: 'complete', step: QUICKSTART_STEP.ENVIRONMENT, advance: false })
        setCurls((prev) => ({ ...prev, [QUICKSTART_STEP.ENVIRONMENT]: envCurl }))
        return true
      } catch (err) {
        if (!isCurrentLifecycleRun(scopeAtStart, lifecycleRunAtStart)) return false
        setMessages((prev) => [
          ...prev,
          {
            id: generateUUID(),
            role: 'assistant' as const,
            content: getOperationErrorMessage(
              t,
              err,
              'managed.quickstart.errors.createEnvironmentFailed',
            ),
          },
        ])
        return false
      } finally {
        if (isCurrentLifecycleRun(scopeAtStart, lifecycleRunAtStart)) {
          setIsCreating(false)
        }
      }
    },
    [isCurrentLifecycleRun, isCurrentWritableLifecycleRun, isCurrentWritableManagedScope, t],
  )

  const createCredentialGroup = useCallback(
    async (name: string, options: CreateCredentialGroupOptions = {}) => {
      const requestScope = managedRequestScopeRef.current
      const scopeAtStart = requestScope.key
      if (!isCurrentWritableManagedScope(scopeAtStart)) return false
      const lifecycleRunAtStart = lifecycleRunRef.current
      setIsCreating(true)
      try {
        const credentials = options.credentials ?? []
        if (
          credentials.some(
            (credential) =>
              credential.authRequirement === 'required' &&
              (!credential.mcpServerUrl.trim() || !credential.tokenValue.trim()),
          )
        ) {
          throw new Error(t('managed.quickstart.errors.incompleteMcpAuthorization'))
        }
        const initialMembers = credentials
          .filter((credential) => credential.authRequirement !== 'none')
          .filter((credential) => credential.tokenValue.trim())
          .map((credential) => ({
            name: credential.name?.trim() || credential.mcpServerUrl.trim(),
            mcp_server_url: credential.mcpServerUrl.trim(),
            data: { token_value: credential.tokenValue.trim() },
          }))
        const credentialGroupBody =
          initialMembers.length > 0 ? { name, initial_members: initialMembers } : { name }
        const maskedCredentialGroupBody =
          initialMembers.length > 0
            ? {
                ...credentialGroupBody,
                initial_members: initialMembers.map((member) => ({
                  ...member,
                  data: { token_value: '$MCP_TOKEN' },
                })),
              }
            : credentialGroupBody
        const result = await managedPost(
          quickstartResourceApiPath(QUICKSTART_STEP.CREDENTIAL_GROUP),
          credentialGroupBody,
          managedRequestOptions(requestScope),
        ).catch((error) => {
          throw toApiStatusError(error)
        })
        if (!isCurrentWritableLifecycleRun(scopeAtStart, lifecycleRunAtStart)) return false
        const rawCredentialGroupId = getCreatedResourceId(result)
        if (!rawCredentialGroupId) {
          throw new Error(t('managed.quickstart.errors.createCredentialGroupFailed'))
        }
        const credentialGroupId = parseQuickstartResourceId(
          QUICKSTART_STEP.CREDENTIAL_GROUP,
          rawCredentialGroupId,
        )

        setResourceIds((prev) => {
          const next = { ...prev, [QUICKSTART_STEP.CREDENTIAL_GROUP]: credentialGroupId }
          resourceIdsRef.current = next
          return next
        })
        setCreatedResourceIds((prev) => new Set([...prev, credentialGroupId]))

        const credentialGroupCurl = `curl -X POST ${API_BASE}/${quickstartResourceApiPath(QUICKSTART_STEP.CREDENTIAL_GROUP)} \
  -H "Content-Type: application/json" \
  -H "x-api-key: $API_KEY" \
  -d '${JSON.stringify(maskedCredentialGroupBody, null, 2)}'`

        dispatchFlow({ type: 'complete', step: QUICKSTART_STEP.CREDENTIAL_GROUP, advance: false })
        setCurls((prev) => ({ ...prev, [QUICKSTART_STEP.CREDENTIAL_GROUP]: credentialGroupCurl }))
        return true
      } catch (err) {
        if (!isCurrentLifecycleRun(scopeAtStart, lifecycleRunAtStart)) return false
        setMessages((prev) => [
          ...prev,
          {
            id: generateUUID(),
            role: 'assistant' as const,
            content: getOperationErrorMessage(
              t,
              err,
              'managed.quickstart.errors.createCredentialGroupFailed',
            ),
          },
        ])
        return false
      } finally {
        if (isCurrentLifecycleRun(scopeAtStart, lifecycleRunAtStart)) {
          setIsCreating(false)
        }
      }
    },
    [isCurrentLifecycleRun, isCurrentWritableLifecycleRun, isCurrentWritableManagedScope, t],
  )

  const selectEngine = useCallback((engine: QuickstartEngine) => {
    setSelectedEngine(engine)
    dispatchFlow({ type: 'engine_selected' })
  }, [])

  const selectModelCredential = useCallback(
    (credentialId?: CredentialId) => {
      dispatchFlow({ type: 'model_connection_selected' })
      const lastUserMessage = [...messagesRef.current]
        .reverse()
        .find((message) => message.role === 'user')
      if (lastUserMessage?.content && !configRef.current.agent && !isStreaming) {
        void sendMessage(lastUserMessage.content, {
          stepOverride: QUICKSTART_STEP.AGENT,
          hidden: true,
          modelCredentialIdOverride: credentialId,
        })
      }
    },
    [isStreaming, sendMessage],
  )

  const applyTemplate = useCallback(
    (template: QuickstartTemplateConfig) => {
      if (streamInFlightRef.current) return
      const userMsg: QuickstartMessage = {
        id: generateUUID(),
        role: 'user',
        content: template.message,
      }
      const assistantMsg: QuickstartMessage = {
        id: generateUUID(),
        role: 'assistant',
        content: t('managed.quickstart.templateAppliedMessage', {
          defaultValue:
            'Structured template applied. Review the configuration on the right, then create this agent.',
        }),
      }
      setMessages((prev) => {
        const next = [...prev, userMsg, assistantMsg]
        messagesRef.current = next
        return next
      })
      setConfig((prev) => ({ ...prev, agent: template.agent }))
      setPendingConfirmation({ step: QUICKSTART_STEP.AGENT })
    },
    [t],
  )

  const advanceStep = useCallback(() => {
    dispatchFlow({ type: 'advance' })
  }, [])

  const skipStep = useCallback((step: QuickstartOptionalStepId) => {
    setResourceIds((current) => {
      const next = { ...current }
      delete next[step]
      resourceIdsRef.current = next
      return next
    })
    dispatchFlow({ type: 'skip', step })
  }, [])

  const setAgentSkills = useCallback(
    (skillIds: SkillId[]) => {
      const selectedIds = new Set(skillIds)
      const skills = availableSkills
        .filter((skill) => selectedIds.has(skill.id))
        .map((skill) => ({ type: 'custom', skill_id: skill.id, version: 'latest' }))
      setConfig((current) => ({
        ...current,
        agent: current.agent ? { ...current.agent, skills } : current.agent,
      }))
    },
    [availableSkills],
  )

  const confirmStep = useCallback(async () => {
    if (!pendingConfirmation || isCreating) return
    const { step } = pendingConfirmation
    const requestScope = managedRequestScopeRef.current
    const scopeAtStart = requestScope.key
    if (!isCurrentWritableManagedScope(scopeAtStart)) return
    const lifecycleRunAtStart = lifecycleRunRef.current
    setIsCreating(true)

    try {
      let result: unknown
      let resourceCurl: string

      const suffix = `-${Date.now().toString(36).slice(-4)}`

      const latestConfig = configRef.current

      if (step === QUICKSTART_STEP.AGENT) {
        const a = latestConfig.agent
        if (!a) throw new Error(t('managed.quickstart.errors.agentConfigMissing'))
        const engine = selectedEngine
        if (!engine) throw new Error(t('managed.quickstart.errors.engineMissing'))
        if (!modelCredentialId) throw new Error(t('managed.quickstart.errors.credentialMissing'))
        const requestBody = buildQuickstartAgentCreateBody(a, {
          engineKind: engine,
          modelCredentialId,
          suffix,
          allowedSkillIds,
        })
        result = await managedPost(
          quickstartResourceApiPath(QUICKSTART_STEP.AGENT),
          requestBody,
          managedRequestOptions(requestScope),
        ).catch((error) => {
          throw toApiStatusError(error)
        })
        resourceCurl = buildQuickstartCreateCurl(QUICKSTART_STEP.AGENT, requestBody)
      } else if (step === QUICKSTART_STEP.ENVIRONMENT) {
        const e = latestConfig.environment
        if (!e) throw new Error(t('managed.quickstart.errors.environmentConfigMissing'))
        const networking = e.networking as Record<string, unknown> | undefined
        const requestBody = {
          name: (e.name || 'quickstart-env') + suffix,
          description: e.description || '',
          config: {
            type: 'cloud',
            networking: {
              type: networking?.type || 'limited',
              allowed_hosts: normalizeQuickstartAllowedHosts(
                (networking?.allowed_hosts as string[]) || [],
              ),
            },
          },
        }
        result = await managedPost(
          quickstartResourceApiPath(QUICKSTART_STEP.ENVIRONMENT),
          requestBody,
          managedRequestOptions(requestScope),
        ).catch((error) => {
          throw toApiStatusError(error)
        })
        resourceCurl = buildQuickstartCreateCurl(QUICKSTART_STEP.ENVIRONMENT, requestBody)
      } else if (step === QUICKSTART_STEP.CREDENTIAL_GROUP) {
        const credentialGroupConfig = latestConfig.credentialGroup
        if (!credentialGroupConfig)
          throw new Error(t('managed.quickstart.errors.credentialGroupConfigMissing'))
        const requestBody = {
          name: (credentialGroupConfig.name || 'quickstart-credential-group') + suffix,
          description: credentialGroupConfig.description || '',
        }
        result = await managedPost(
          quickstartResourceApiPath(QUICKSTART_STEP.CREDENTIAL_GROUP),
          requestBody,
          managedRequestOptions(requestScope),
        ).catch((error) => {
          throw toApiStatusError(error)
        })
        resourceCurl = buildQuickstartCreateCurl(QUICKSTART_STEP.CREDENTIAL_GROUP, requestBody)
      } else {
        throw new Error(t('managed.quickstart.errors.unexpectedStep', { step }))
      }
      if (!isCurrentWritableLifecycleRun(scopeAtStart, lifecycleRunAtStart)) return
      const createdResource = unwrapManagedResponse<Record<string, unknown>>(result)
      const createdAgent =
        step === QUICKSTART_STEP.AGENT
          ? ((createdResource?.agent && typeof createdResource.agent === 'object'
              ? createdResource.agent
              : createdResource) as Record<string, unknown>)
          : null
      if (createdAgent?.model) {
        setConfig((prev) => ({
          ...prev,
          agent: {
            ...(prev.agent || {}),
            model: createdAgent.model,
          },
        }))
      }
      const rawResourceId = getCreatedResourceId(result)
      if (!rawResourceId) throw new Error(t('managed.quickstart.errors.createResourceFailed'))
      const resourceId = parseQuickstartResourceId(step, rawResourceId)

      setResourceIds((prev) => {
        const next = { ...prev, [step]: resourceId }
        resourceIdsRef.current = next
        return next
      })
      if (isQuickstartCreatedResourceStep(step)) {
        setCreatedResourceIds((prev) => new Set([...prev, resourceId]))
      }

      dispatchFlow({ type: 'complete', step })
      setCurls((prev) => ({ ...prev, [step]: resourceCurl }))
      setPendingConfirmation(null)
    } catch (err) {
      if (!isCurrentLifecycleRun(scopeAtStart, lifecycleRunAtStart)) return
      console.error(t('managed.quickstart.errors.createResourceFailed'), err)
      setMessages((prev) => [
        ...prev,
        {
          id: generateUUID(),
          role: 'assistant',
          content: getOperationErrorMessage(
            t,
            err,
            'managed.quickstart.errors.createResourceFailed',
          ),
        },
      ])
    } finally {
      if (isCurrentLifecycleRun(scopeAtStart, lifecycleRunAtStart)) {
        setIsCreating(false)
      }
    }
  }, [
    pendingConfirmation,
    isCreating,
    modelCredentialId,
    allowedSkillIds,
    selectedEngine,
    isCurrentLifecycleRun,
    isCurrentWritableLifecycleRun,
    isCurrentWritableManagedScope,
    t,
  ])

  const keepRefining = useCallback(() => {
    const step = pendingConfirmation?.step
    setPendingConfirmation(null)
    if (!step) return
    const message: QuickstartMessage = {
      id: generateUUID(),
      role: 'assistant',
      content: t(`managed.quickstart.refinePrompt.step${step}`),
    }
    setMessages((prev) => {
      const next = [...prev, message]
      messagesRef.current = next
      return next
    })
  }, [pendingConfirmation, t])

  const selectExistingEnvironment = useCallback((envId: EnvironmentId) => {
    setResourceIds((prev) => {
      const next = { ...prev, [QUICKSTART_STEP.ENVIRONMENT]: envId }
      resourceIdsRef.current = next
      return next
    })
    dispatchFlow({ type: 'complete', step: QUICKSTART_STEP.ENVIRONMENT, advance: false })
  }, [])

  const selectExistingCredentialGroup = useCallback((credentialGroupId: CredentialGroupId) => {
    setResourceIds((prev) => {
      const next = { ...prev, [QUICKSTART_STEP.CREDENTIAL_GROUP]: credentialGroupId }
      resourceIdsRef.current = next
      return next
    })
    dispatchFlow({ type: 'complete', step: QUICKSTART_STEP.CREDENTIAL_GROUP, advance: false })
  }, [])

  const goToStep = useCallback((step: StepId) => {
    dispatchFlow({ type: 'go_to', step })
  }, [])

  const reopenStep = useCallback((step: StepId) => {
    dispatchFlow({ type: 'reopen', step })
    setPendingConfirmation(null)
    setCurls((prev) => {
      const next = { ...prev }
      for (const completedStep of Object.keys(next)) {
        if (Number(completedStep) >= step) delete next[Number(completedStep)]
      }
      return next
    })
    setResourceIds((prev) => {
      const next = { ...prev }
      for (const resourceStep of Object.keys(next)) {
        if (Number(resourceStep) >= Math.max(step, QUICKSTART_STEP.AGENT)) {
          delete next[Number(resourceStep) as QuickstartResourceStepId]
        }
      }
      resourceIdsRef.current = next
      return next
    })
    setConfig((prev) => ({
      ...(step > QUICKSTART_STEP.AGENT && prev.agent ? { agent: prev.agent } : {}),
      ...(step > QUICKSTART_STEP.ENVIRONMENT && prev.environment
        ? { environment: prev.environment }
        : {}),
      ...(step > QUICKSTART_STEP.CREDENTIAL_GROUP && prev.credentialGroup
        ? { credentialGroup: prev.credentialGroup }
        : {}),
    }))
    if (step === QUICKSTART_STEP.ENGINE) setSelectedEngine(null)
  }, [])

  const generateTestMessage = useCallback(async (): Promise<string> => {
    const agent = configRef.current.agent as Record<string, unknown> | undefined
    const agentName = (agent?.name as string) || 'agent'
    const acceptanceMessage = normalizeQuickstartAgentBlueprint(agent).acceptanceTest.message
    if (acceptanceMessage) return acceptanceMessage
    return t('managed.quickstart.trialRun.defaultPrompt', { agentName })
  }, [t])

  return {
    messages,
    currentStep,
    selectedEngine,
    config,
    isStreaming,
    generationState,
    curls,
    resourceIds,
    createdResourceIds,
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
  }
}
