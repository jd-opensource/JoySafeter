'use client'

import { useState, useCallback, useRef, useEffect } from 'react'

import { API_BASE, ApiError, apiStream, managedPost } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { apiResourceId } from '@/lib/managed/api-paths'
import { getOperationErrorMessage } from '@/lib/managed/errors'
import { buildQuickstartAgentCreateBody } from '@/lib/managed/quickstart-create'
import {
  managedRequestOptions,
  managedScopeKey,
  type ManagedRequestScope,
  useManagedRequestScope,
} from '@/lib/managed/request-scope'
import { generateUUID } from '@/lib/utils/uuid'
import { useProjectStore } from '@/stores/managed/project-store'
import {
  parseAgentId,
  parseEnvironmentId,
  parseSessionId,
  parseVaultId,
  type EnvironmentId,
  type VaultId,
} from '@/types/entity-id'

import { currentProjectAllowsWrite } from './use-current-project-read-only'

export type StepId = 1 | 2 | 3 | 4 | 5 | 6
export type QuickstartEngine = string

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  isStreaming?: boolean
}

export interface QuickstartConfig {
  agent?: Record<string, unknown>
  environment?: Record<string, unknown>
  vault?: Record<string, unknown>
}

export interface QuickstartTemplateConfig {
  message: string
  agent: Record<string, unknown>
}

interface CreateSessionOptions {
  environmentId?: EnvironmentId | null
  vaultId?: VaultId | null
}

function getCurrentManagedScope() {
  const { currentOrgId, currentProjectId } = useProjectStore.getState()
  return managedScopeKey(currentOrgId, currentProjectId)
}

function apiStepForUiStep(step: StepId): number {
  if (step <= 2) return step
  return step - 1
}

function uiStepForApiStep(step: number): StepId {
  return Math.min(step + 1, 6) as StepId
}

interface QuickstartEvent {
  type: 'text_delta' | 'config_update' | 'step_complete' | 'error' | 'done'
  text?: string
  step?: number
  config?: Record<string, unknown>
  resource_id?: string
  curl?: string
  message?: string
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

  for (const key of ['agent', 'environment', 'vault', 'session']) {
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

function parseQuickstartResourceId(step: StepId, value: string): string {
  if (step === 3) return parseAgentId(value)
  if (step === 4) return parseEnvironmentId(value)
  if (step === 5) return parseVaultId(value)
  if (step === 6) return parseSessionId(value)
  return value
}

function toApiStatusError(error: unknown): Error {
  if (error instanceof ApiError) {
    return new Error(`API ${error.status}: ${error.detail || error.message}`)
  }
  return error instanceof Error ? error : new Error(String(error))
}

export function useQuickstartChat(agentSecretRef: string) {
  const { t } = useTranslation()
  const managedScope = useManagedRequestScope()
  const managedScopeKeyValue = managedScope.key
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const messagesRef = useRef<ChatMessage[]>([])
  const [currentStep, setCurrentStep] = useState<StepId>(1)
  const [selectedEngine, setSelectedEngine] = useState<QuickstartEngine | null>(null)
  const [config, setConfig] = useState<QuickstartConfig>({})
  const configRef = useRef(config)
  useEffect(() => {
    configRef.current = config
  }, [config])
  const [isStreaming, setIsStreaming] = useState(false)
  const [curls, setCurls] = useState<Record<number, string>>({})
  // resourceIds: { 3: agentId, 4: envId, 5: vaultId, 6: sessionId }
  const [resourceIds, setResourceIds] = useState<Record<number, string>>({})
  const [createdResourceIds, setCreatedResourceIds] = useState<Set<string>>(new Set())
  const [completedSteps, setCompletedSteps] = useState<Set<number>>(new Set())
  const [pendingConfirmation, setPendingConfirmation] = useState<{
    step: number
    curl: string
  } | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const streamInFlightRef = useRef(false)
  const [isCreating, setIsCreating] = useState(false)

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
    setIsStreaming(false)
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
      Object.fromEntries(Object.entries(prev).filter(([step]) => Number(step) < 3)),
    )
    setCompletedSteps((prev) => new Set(Array.from(prev).filter((step) => step < 3)))
    setPendingConfirmation(null)
    setCurrentStep((prev) => (prev > 3 ? 3 : prev))
  }, [managedScopeKeyValue])

  const sendMessage = useCallback(
    async (
      text: string,
      options?: {
        stepOverride?: StepId
        hidden?: boolean
        engineKindOverride?: QuickstartEngine
        secretRefOverride?: string
      },
    ) => {
      const trimmedText = text.trim()
      if (streamInFlightRef.current || !trimmedText) return
      const step = options?.stepOverride ?? currentStep
      const hidden = options?.hidden ?? false
      const engineKind = options?.engineKindOverride ?? selectedEngine
      if (!engineKind) return
      const requestSecretRef = options?.secretRefOverride ?? agentSecretRef
      const requestScope = managedRequestScopeRef.current
      const scopeAtStart = requestScope.key
      if (!isCurrentWritableManagedScope(scopeAtStart)) return

      const userMsg: ChatMessage = {
        id: generateUUID(),
        role: 'user',
        content: trimmedText,
      }

      const assistantMsg: ChatMessage = {
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

      setMessages((prev) => (hidden ? [...prev, assistantMsg] : [...prev, userMsg, assistantMsg]))
      messagesRef.current = hidden
        ? [...messagesRef.current, assistantMsg]
        : [...newMessages, assistantMsg]
      streamInFlightRef.current = true
      setIsStreaming(true)

      const controller = new AbortController()
      abortRef.current = controller

      try {
        const historyForApi = newMessages.map((m) => ({
          role: m.role,
          content: m.content,
        }))

        const response = await apiStream(
          'quickstart/chat',
          {
            messages: historyForApi,
            current_step: apiStepForUiStep(step),
            engine_kind: engineKind,
            secret_ref: requestSecretRef,
            agent_context: step === 4 || step === 5 ? configRef.current.agent : undefined,
          },
          { ...managedRequestOptions(requestScope), signal: controller.signal },
        )

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
                if (event.step && event.config) {
                  setConfig((prev) => {
                    if (event.step === 2) return { ...prev, agent: event.config }
                    if (event.step === 3) return { ...prev, environment: event.config }
                    if (event.step === 4) return { ...prev, vault: event.config }
                    return prev
                  })
                }
                break

              case 'step_complete':
                if (event.step) {
                  const uiStep = uiStepForApiStep(event.step)
                  setPendingConfirmation({
                    step: uiStep,
                    curl: event.curl || '',
                  })
                  if (event.resource_id) {
                    const resourceId = parseQuickstartResourceId(uiStep, event.resource_id)
                    setResourceIds((prev) => {
                      const next = { ...prev, [uiStep]: resourceId }
                      resourceIdsRef.current = next
                      return next
                    })
                  }
                }
                break

              case 'error':
                accumulatedText += `\n\n⚠️ ${event.message || t('managed.quickstart.errors.generic')}`
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
      } catch (e) {
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
    [messages, currentStep, selectedEngine, agentSecretRef, isCurrentWritableManagedScope, t],
  )

  const createSession = useCallback(
    async (options: CreateSessionOptions = {}) => {
      const agentId = resourceIdsRef.current[3]
      const envId =
        'environmentId' in options ? options.environmentId || undefined : resourceIdsRef.current[4]
      const vaultId =
        'vaultId' in options ? options.vaultId || undefined : resourceIdsRef.current[5]
      if (!agentId) {
        setMessages((prev) => [
          ...prev,
          {
            id: generateUUID(),
            role: 'assistant',
            content: t('managed.quickstart.errors.agentMissingForSession'),
          },
        ])
        return
      }

      const requestScope = managedRequestScopeRef.current
      const scopeAtStart = requestScope.key
      if (!isCurrentWritableManagedScope(scopeAtStart)) return
      const lifecycleRunAtStart = lifecycleRunRef.current
      setIsCreating(true)
      try {
        const body: Record<string, unknown> = { agent: apiResourceId(parseAgentId(agentId)) }
        if (envId) body.environment_id = apiResourceId(parseEnvironmentId(envId))
        if (vaultId) body.vault_ids = [apiResourceId(parseVaultId(vaultId))]

        const result = await managedPost(
          'sessions',
          body,
          managedRequestOptions(requestScope),
        ).catch((error) => {
          throw toApiStatusError(error)
        })
        if (!isCurrentWritableLifecycleRun(scopeAtStart, lifecycleRunAtStart)) return
        const rawSessionId = getCreatedResourceId(result)
        if (!rawSessionId) throw new Error(t('managed.quickstart.errors.createSessionFailed'))
        const sessionId = parseSessionId(rawSessionId)

        setResourceIds((prev) => {
          const next = { ...prev, [6]: sessionId }
          resourceIdsRef.current = next
          return next
        })

        const sessionCurl = `curl -X POST ${API_BASE}/sessions \\
  -H "Content-Type: application/json" \\
  -H "x-api-key: $API_KEY" \\
  -d '${JSON.stringify(body, null, 2)}'`

        setCompletedSteps((prev) => new Set([...prev, 6]))
        setCurls((prev) => ({ ...prev, [6]: sessionCurl }))
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
    [isCurrentLifecycleRun, isCurrentWritableLifecycleRun, isCurrentWritableManagedScope, t],
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
        const envBody = {
          name: `quickstart-env${suffix}`,
          description: '',
          config: {
            type: 'cloud',
            networking: {
              type: networkType,
              allowed_hosts: allowedHosts,
            },
          },
        }

        const result = await managedPost(
          'environments',
          envBody,
          managedRequestOptions(requestScope),
        ).catch((error) => {
          throw toApiStatusError(error)
        })
        if (!isCurrentWritableLifecycleRun(scopeAtStart, lifecycleRunAtStart)) return false
        const rawEnvironmentId = getCreatedResourceId(result)
        if (!rawEnvironmentId)
          throw new Error(t('managed.quickstart.errors.createEnvironmentFailed'))
        const environmentId = parseEnvironmentId(rawEnvironmentId)

        setResourceIds((prev) => {
          const next = { ...prev, [4]: environmentId }
          resourceIdsRef.current = next
          return next
        })
        setCreatedResourceIds((prev) => new Set([...prev, environmentId]))

        const envCurl = `curl -X POST ${API_BASE}/environments \\
  -H "Content-Type: application/json" \\
  -H "x-api-key: $API_KEY" \\
  -d '${JSON.stringify(envBody, null, 2)}'`

        setCompletedSteps((prev) => new Set([...prev, 4]))
        setCurls((prev) => ({ ...prev, [4]: envCurl }))
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

  const createVault = useCallback(
    async (name: string) => {
      const requestScope = managedRequestScopeRef.current
      const scopeAtStart = requestScope.key
      if (!isCurrentWritableManagedScope(scopeAtStart)) return false
      const lifecycleRunAtStart = lifecycleRunRef.current
      setIsCreating(true)
      try {
        const vaultBody = { name }
        const result = await managedPost(
          'vaults',
          vaultBody,
          managedRequestOptions(requestScope),
        ).catch((error) => {
          throw toApiStatusError(error)
        })
        if (!isCurrentWritableLifecycleRun(scopeAtStart, lifecycleRunAtStart)) return false
        const rawVaultId = getCreatedResourceId(result)
        if (!rawVaultId) throw new Error(t('managed.quickstart.errors.createVaultFailed'))
        const vaultId = parseVaultId(rawVaultId)

        setResourceIds((prev) => {
          const next = { ...prev, [5]: vaultId }
          resourceIdsRef.current = next
          return next
        })
        setCreatedResourceIds((prev) => new Set([...prev, vaultId]))

        const vaultCurl = `curl -X POST ${API_BASE}/vaults \\
  -H "Content-Type: application/json" \\
  -H "x-api-key: $API_KEY" \\
  -d '${JSON.stringify(vaultBody, null, 2)}'`

        setCompletedSteps((prev) => new Set([...prev, 5]))
        setCurls((prev) => ({ ...prev, [5]: vaultCurl }))
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
              'managed.quickstart.errors.createVaultFailed',
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
    setCompletedSteps((prev) => new Set([...prev, 1]))
    setCurrentStep(2)
  }, [])

  const selectAgentSecret = useCallback(() => {
    setCompletedSteps((prev) => new Set([...prev, 2]))
    setCurrentStep(3)
    const lastUserMessage = [...messagesRef.current]
      .reverse()
      .find((message) => message.role === 'user')
    if (lastUserMessage?.content && !configRef.current.agent && !isStreaming) {
      void sendMessage(lastUserMessage.content, {
        stepOverride: 3,
        hidden: true,
      })
    }
  }, [isStreaming, sendMessage])

  const applyTemplate = useCallback(
    (template: QuickstartTemplateConfig) => {
      if (streamInFlightRef.current) return
      const userMsg: ChatMessage = {
        id: generateUUID(),
        role: 'user',
        content: template.message,
      }
      const assistantMsg: ChatMessage = {
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
      setPendingConfirmation({ step: 3, curl: '' })
      setCurrentStep(3)
    },
    [t],
  )

  const advanceStep = useCallback(() => {
    const nextStep = Math.min(currentStep + 1, 6) as StepId
    setCurrentStep(nextStep)
  }, [currentStep])

  const confirmStep = useCallback(async () => {
    if (!pendingConfirmation || isCreating) return
    const { step, curl } = pendingConfirmation
    const requestScope = managedRequestScopeRef.current
    const scopeAtStart = requestScope.key
    if (!isCurrentWritableManagedScope(scopeAtStart)) return
    const lifecycleRunAtStart = lifecycleRunRef.current
    setIsCreating(true)

    try {
      let result: unknown

      const suffix = `-${Date.now().toString(36).slice(-4)}`

      const latestConfig = configRef.current

      if (step === 3) {
        const a = latestConfig.agent
        if (!a) throw new Error(t('managed.quickstart.errors.agentConfigMissing'))
        const engine = selectedEngine
        if (!engine) throw new Error(t('managed.quickstart.errors.engineMissing'))
        result = await managedPost(
          'agents',
          buildQuickstartAgentCreateBody(a, {
            engineKind: engine,
            secretRef: agentSecretRef,
            suffix,
          }),
          managedRequestOptions(requestScope),
        ).catch((error) => {
          throw toApiStatusError(error)
        })
      } else if (step === 4) {
        const e = latestConfig.environment
        if (!e) throw new Error(t('managed.quickstart.errors.environmentConfigMissing'))
        const networking = e.networking as Record<string, unknown> | undefined
        result = await managedPost(
          'environments',
          {
            name: (e.name || 'quickstart-env') + suffix,
            description: e.description || '',
            config: {
              type: 'cloud',
              networking: {
                type: networking?.type || 'limited',
                allowed_hosts: (networking?.allowed_hosts as string[]) || [],
              },
            },
          },
          managedRequestOptions(requestScope),
        ).catch((error) => {
          throw toApiStatusError(error)
        })
      } else if (step === 5) {
        const v = latestConfig.vault
        if (!v) throw new Error(t('managed.quickstart.errors.vaultConfigMissing'))
        result = await managedPost(
          'vaults',
          {
            name: (v.name || 'quickstart-vault') + suffix,
            description: v.description || '',
          },
          managedRequestOptions(requestScope),
        ).catch((error) => {
          throw toApiStatusError(error)
        })
      } else {
        throw new Error(t('managed.quickstart.errors.unexpectedStep', { step }))
      }
      if (!isCurrentWritableLifecycleRun(scopeAtStart, lifecycleRunAtStart)) return
      const createdResource = unwrapManagedResponse<Record<string, unknown>>(result)
      const createdAgent =
        step === 3
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
      if (step === 3 || step === 4 || step === 5) {
        setCreatedResourceIds((prev) => new Set([...prev, resourceId]))
      }

      setCompletedSteps((prev) => new Set([...prev, step]))
      setCurls((prev) => ({ ...prev, [step]: curl }))
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
    agentSecretRef,
    selectedEngine,
    isCurrentLifecycleRun,
    isCurrentWritableLifecycleRun,
    isCurrentWritableManagedScope,
    t,
  ])

  const keepRefining = useCallback(() => {
    setPendingConfirmation(null)
  }, [])

  const selectExistingEnvironment = useCallback((envId: EnvironmentId) => {
    setResourceIds((prev) => {
      const next = { ...prev, [4]: envId }
      resourceIdsRef.current = next
      return next
    })
    setCompletedSteps((prev) => new Set([...prev, 4]))
  }, [])

  const selectExistingVault = useCallback((vaultId: VaultId) => {
    setResourceIds((prev) => {
      const next = { ...prev, [5]: vaultId }
      resourceIdsRef.current = next
      return next
    })
    setCompletedSteps((prev) => new Set([...prev, 5]))
  }, [])

  const goToStep = useCallback((step: StepId) => {
    setCurrentStep(step)
  }, [])

  const sendAutoIntro = useCallback(
    async (step: StepId) => {
      if (step === 3) {
        await sendMessage('Create an agent configuration for my use case.', {
          stepOverride: 3,
          hidden: true,
        })
      } else if (step === 4) {
        const agentName =
          (configRef.current.agent as Record<string, unknown> | undefined)?.name || 'the agent'
        await sendMessage(
          `I just configured an agent called "${agentName}". What environment configuration does it need?`,
          { stepOverride: 4, hidden: true },
        )
      } else if (step === 5) {
        await sendMessage(
          'What vault configuration does my agent need for MCP server credentials?',
          { stepOverride: 5, hidden: true },
        )
      }
    },
    [sendMessage],
  )

  const generateTestMessage = useCallback(async (): Promise<string> => {
    const agent = configRef.current.agent as Record<string, unknown> | undefined
    const agentName = (agent?.name as string) || 'agent'
    const agentDesc = (agent?.system as string) || ''
    const tools = (agent?.tools as unknown[]) || []

    const prompt = `Based on this agent configuration, generate ONE short test message (1-2 sentences) that a user would send to verify the agent works. Only output the message text, nothing else.

Agent: ${agentName}
${agentDesc ? `System prompt: ${agentDesc.slice(0, 300)}` : ''}
${tools.length > 0 ? `Tools: ${JSON.stringify(tools).slice(0, 200)}` : ''}`

    const requestScope = managedRequestScopeRef.current
    const scopeAtStart = requestScope.key
    if (!selectedEngine || !isCurrentWritableManagedScope(scopeAtStart)) {
      return t('managed.quickstart.trialRun.defaultPrompt', { agentName })
    }

    try {
      const response = await apiStream(
        'quickstart/chat',
        {
          messages: [{ role: 'user', content: prompt }],
          current_step: 5,
          engine_kind: selectedEngine,
          secret_ref: agentSecretRef,
          agent_context: agent,
        },
        managedRequestOptions(requestScope),
      )

      const reader = response.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let text = ''

      const processLine = (line: string) => {
        if (!line.startsWith('data:')) return
        const data = line.slice(5).trim()
        if (!data || data === '[DONE]') return
        try {
          const event = JSON.parse(data)
          if (event.type === 'text_delta') text += event.text || ''
        } catch {
          /* ignore */
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
        if (!isCurrentWritableManagedScope(scopeAtStart)) {
          return t('managed.quickstart.trialRun.defaultPrompt', { agentName })
        }
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        for (const line of lines) {
          processLine(line)
        }
      }
      return text.trim() || t('managed.quickstart.trialRun.defaultPrompt', { agentName })
    } catch {
      return t('managed.quickstart.trialRun.defaultPrompt', { agentName })
    }
  }, [agentSecretRef, selectedEngine, isCurrentWritableManagedScope, t])

  return {
    messages,
    currentStep,
    selectedEngine,
    config,
    isStreaming,
    curls,
    resourceIds,
    createdResourceIds,
    completedSteps,
    pendingConfirmation,
    isCreating,
    sendMessage,
    applyTemplate,
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
  }
}
