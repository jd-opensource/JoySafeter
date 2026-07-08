'use client'

import { useState, useCallback, useRef, useEffect } from 'react'
import { useTranslation } from '@/lib/i18n'
import { MANAGED_API_BASE } from '@/lib/api-client'
import { getCsrfToken } from '@/lib/auth/csrf'
import { getOperationErrorMessage } from '@/lib/managed/errors'
import { stripIdPrefix } from '@/lib/managed/id'
import { buildQuickstartAgentCreateBody } from '@/lib/managed/quickstart-create'
import { generateUUID } from '@/lib/utils/uuid'
import { useProjectStore } from '@/stores/managed/project-store'

export type StepId = 1 | 2 | 3 | 4 | 5 | 6
export type QuickstartEngine = 'claude' | 'codex' | 'native'

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

const ENGINE_CONFIG: Record<QuickstartEngine, { engineKind: string }> = {
  claude: { engineKind: 'claude' },
  codex: { engineKind: 'codex' },
  native: { engineKind: 'native' },
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

function getAuthHeaders(): Record<string, string> {
  const headers: Record<string, string> = {}
  const csrf = getCsrfToken()
  if (csrf) headers['X-CSRF-Token'] = csrf
  const { currentProjectId, currentOrgId } = useProjectStore.getState()
  if (currentOrgId) headers['X-Org-Id'] = currentOrgId
  if (currentProjectId) headers['X-Project-Id'] = currentProjectId
  return headers
}

function unwrapManagedResponse<T = Record<string, unknown>>(payload: unknown): T {
  if (
    payload &&
    typeof payload === 'object' &&
    'success' in payload &&
    'data' in payload
  ) {
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
    if (nested && typeof nested === 'object' && typeof (nested as { id?: unknown }).id === 'string') {
      return (nested as { id: string }).id
    }
  }

  return null
}

export function useQuickstartChat(
  agentSecretRef: string,
  generationSecret?: { secretRef: string; provider: QuickstartEngine },
) {
  const { t } = useTranslation()
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
  const [completedSteps, setCompletedSteps] = useState<Set<number>>(new Set())
  const [pendingConfirmation, setPendingConfirmation] = useState<{
    step: number
    curl: string
  } | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const [isCreating, setIsCreating] = useState(false)

  const resourceIdsRef = useRef(resourceIds)
  useEffect(() => {
    resourceIdsRef.current = resourceIds
  }, [resourceIds])

  useEffect(() => {
    messagesRef.current = messages
  }, [messages])

  const sendMessage = useCallback(
    async (
      text: string,
      options?: {
        stepOverride?: StepId
        hidden?: boolean
        providerOverride?: QuickstartEngine
        secretRefOverride?: string
      },
    ) => {
      if (isStreaming || !text.trim()) return
      const step = options?.stepOverride ?? currentStep
      const hidden = options?.hidden ?? false
      const provider = options?.providerOverride ?? generationSecret?.provider ?? 'claude'
      const requestSecretRef = options?.secretRefOverride ?? generationSecret?.secretRef ?? agentSecretRef

      const userMsg: ChatMessage = {
        id: generateUUID(),
        role: 'user',
        content: text.trim(),
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
      messagesRef.current = hidden ? [...messagesRef.current, assistantMsg] : [...newMessages, assistantMsg]
      setIsStreaming(true)

      const controller = new AbortController()
      abortRef.current = controller

      try {
        const historyForApi = newMessages.map((m) => ({
          role: m.role,
          content: m.content,
        }))

        const response = await fetch(`${MANAGED_API_BASE}/quickstart/chat`, {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
          body: JSON.stringify({
            messages: historyForApi,
            current_step: apiStepForUiStep(step),
            provider,
            secret_ref: requestSecretRef,
            agent_context: step === 4 || step === 5 ? configRef.current.agent : undefined,
          }),
          signal: controller.signal,
        })

        if (!response.ok) {
          throw new Error(`API error: ${response.status}`)
        }

        const reader = response.body!.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        let accumulatedText = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''

          for (const line of lines) {
            if (!line.startsWith('data:')) continue
            const data = line.slice(5).trim()
            if (!data || data === '[DONE]') continue

            try {
              const event: QuickstartEvent = JSON.parse(data)

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
                      setResourceIds((prev) => {
                        const next = { ...prev, [uiStep]: event.resource_id! }
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
        }
      } catch (e) {
        if ((e as Error).name !== 'AbortError') {
          setMessages((prev) => {
            const updated = [...prev]
            const last = updated[updated.length - 1]
            if (last && last.role === 'assistant') {
              updated[updated.length - 1] = {
                ...last,
                content: last.content || getOperationErrorMessage(t, e, 'managed.quickstart.errors.chatFailed'),
              }
            }
            return updated
          })
        }
      } finally {
        setIsStreaming(false)
        setMessages((prev) => {
          const updated = [...prev]
          const last = updated[updated.length - 1]
          if (last && last.role === 'assistant') {
            updated[updated.length - 1] = { ...last, isStreaming: false }
          }
          return updated
        })
        abortRef.current = null
      }
    },
    [messages, currentStep, generationSecret, agentSecretRef, isStreaming, t],
  )

  const createSession = useCallback(async () => {
    const agentId = resourceIdsRef.current[3]
    const envId = resourceIdsRef.current[4]
    const vaultId = resourceIdsRef.current[5]
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

    setIsCreating(true)
    try {
      const body: Record<string, unknown> = { agent: stripIdPrefix(agentId) }
      if (envId) body.environment_id = stripIdPrefix(envId)
      if (vaultId) body.vault_ids = [stripIdPrefix(vaultId)]

      const resp = await fetch(`${MANAGED_API_BASE}/sessions`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify(body),
      })

      if (!resp.ok) {
        const text = await resp.text()
        throw new Error(`API ${resp.status}: ${text}`)
      }

      const result = await resp.json()
      const sessionId = getCreatedResourceId(result)
      if (sessionId) {
        setResourceIds((prev) => {
          const next = { ...prev, [6]: sessionId }
          resourceIdsRef.current = next
          return next
        })
      }

      const sessionCurl = `curl -X POST ${MANAGED_API_BASE}/sessions \\
  -H "Content-Type: application/json" \\
  -H "x-api-key: $API_KEY" \\
  -d '${JSON.stringify(body, null, 2)}'`

      setCompletedSteps((prev) => new Set([...prev, 6]))
      setCurls((prev) => ({ ...prev, [6]: sessionCurl }))
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: generateUUID(),
          role: 'assistant',
          content: getOperationErrorMessage(t, err, 'managed.quickstart.errors.createSessionFailed'),
        },
      ])
    } finally {
      setIsCreating(false)
    }
  }, [t])

  const createEnvironment = useCallback(
    async (networkType: 'unrestricted' | 'limited', allowedHosts: string[]) => {
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

        const resp = await fetch(`${MANAGED_API_BASE}/environments`, {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
          body: JSON.stringify(envBody),
        })

        if (!resp.ok) {
          const text = await resp.text()
          throw new Error(`API ${resp.status}: ${text}`)
        }

        const result = await resp.json()
        const environmentId = getCreatedResourceId(result)
        if (!environmentId) throw new Error(t('managed.quickstart.errors.createEnvironmentFailed'))

        setResourceIds((prev) => {
          const next = { ...prev, [4]: environmentId }
          resourceIdsRef.current = next
          return next
        })

        const envCurl = `curl -X POST ${MANAGED_API_BASE}/environments \\
  -H "Content-Type: application/json" \\
  -H "x-api-key: $API_KEY" \\
  -d '${JSON.stringify(envBody, null, 2)}'`

        setCompletedSteps((prev) => new Set([...prev, 4]))
        setCurls((prev) => ({ ...prev, [4]: envCurl }))
        return true
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          {
            id: generateUUID(),
            role: 'assistant' as const,
            content: getOperationErrorMessage(t, err, 'managed.quickstart.errors.createEnvironmentFailed'),
          },
        ])
        return false
      } finally {
        setIsCreating(false)
      }
    },
    [t],
  )

  const createVault = useCallback(async (name: string) => {
    setIsCreating(true)
    try {
      const vaultBody = { name }
      const resp = await fetch(`${MANAGED_API_BASE}/vaults`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify(vaultBody),
      })

      if (!resp.ok) {
        const text = await resp.text()
        throw new Error(`API ${resp.status}: ${text}`)
      }

      const result = await resp.json()
      const vaultId = getCreatedResourceId(result)
      if (!vaultId) throw new Error(t('managed.quickstart.errors.createVaultFailed'))

      setResourceIds((prev) => {
        const next = { ...prev, [5]: vaultId }
        resourceIdsRef.current = next
        return next
      })

      const vaultCurl = `curl -X POST ${MANAGED_API_BASE}/vaults \\
  -H "Content-Type: application/json" \\
  -H "x-api-key: $API_KEY" \\
  -d '${JSON.stringify(vaultBody, null, 2)}'`

      setCompletedSteps((prev) => new Set([...prev, 5]))
      setCurls((prev) => ({ ...prev, [5]: vaultCurl }))
      return true
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: generateUUID(),
          role: 'assistant' as const,
          content: getOperationErrorMessage(t, err, 'managed.quickstart.errors.createVaultFailed'),
        },
      ])
      return false
    } finally {
      setIsCreating(false)
    }
  }, [t])

  const selectEngine = useCallback((engine: QuickstartEngine) => {
    setSelectedEngine(engine)
    setCompletedSteps((prev) => new Set([...prev, 1]))
    setCurrentStep(2)
  }, [])

  const selectAgentSecret = useCallback(() => {
    setCompletedSteps((prev) => new Set([...prev, 2]))
    setCurrentStep(3)
    const lastUserMessage = [...messagesRef.current].reverse().find((message) => message.role === 'user')
    if (lastUserMessage?.content && !configRef.current.agent && !isStreaming) {
      void sendMessage(lastUserMessage.content, {
        stepOverride: 3,
        hidden: true,
      })
    }
  }, [isStreaming, sendMessage])

  const advanceStep = useCallback(() => {
    const nextStep = Math.min(currentStep + 1, 6) as StepId
    setCurrentStep(nextStep)
  }, [currentStep])

  const confirmStep = useCallback(async () => {
    if (!pendingConfirmation || isCreating) return
    const { step, curl } = pendingConfirmation
    setIsCreating(true)

    try {
      let resp: Response

      const suffix = `-${Date.now().toString(36).slice(-4)}`

      const latestConfig = configRef.current

      if (step === 3) {
        const a = latestConfig.agent
        if (!a) throw new Error(t('managed.quickstart.errors.agentConfigMissing'))
        const engine = selectedEngine || 'claude'
        const engineConfig = ENGINE_CONFIG[engine]
        resp = await fetch(`${MANAGED_API_BASE}/agents`, {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
          body: JSON.stringify(
            buildQuickstartAgentCreateBody(a, {
              engineKind: engineConfig.engineKind,
              secretRef: agentSecretRef,
              suffix,
            }),
          ),
        })
      } else if (step === 4) {
        const e = latestConfig.environment
        if (!e) throw new Error(t('managed.quickstart.errors.environmentConfigMissing'))
        const networking = e.networking as Record<string, unknown> | undefined
        resp = await fetch(`${MANAGED_API_BASE}/environments`, {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
          body: JSON.stringify({
            name: (e.name || 'quickstart-env') + suffix,
            description: e.description || '',
            config: {
              type: 'cloud',
              networking: {
                type: networking?.type || 'limited',
                allowed_hosts: (networking?.allowed_hosts as string[]) || [],
              },
            },
          }),
        })
      } else if (step === 5) {
        const v = latestConfig.vault
        if (!v) throw new Error(t('managed.quickstart.errors.vaultConfigMissing'))
        resp = await fetch(`${MANAGED_API_BASE}/vaults`, {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
          body: JSON.stringify({
            name: (v.name || 'quickstart-vault') + suffix,
            description: v.description || '',
          }),
        })
      } else {
        throw new Error(t('managed.quickstart.errors.unexpectedStep', { step }))
      }

      if (!resp.ok) {
        const body = await resp.text()
        throw new Error(`API ${resp.status}: ${body}`)
      }

      const result = await resp.json()
      const createdResource = unwrapManagedResponse<Record<string, unknown>>(result)
      const createdAgent =
        step === 3
          ? (
              createdResource?.agent &&
              typeof createdResource.agent === 'object'
                ? createdResource.agent
                : createdResource
            ) as Record<string, unknown>
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
      const resourceId = getCreatedResourceId(result)
      if (resourceId) {
        setResourceIds((prev) => {
          const next = { ...prev, [step]: resourceId }
          resourceIdsRef.current = next
          return next
        })
      }

      setCompletedSteps((prev) => new Set([...prev, step]))
      setCurls((prev) => ({ ...prev, [step]: curl }))
      setPendingConfirmation(null)
    } catch (err) {
      console.error(t('managed.quickstart.errors.createResourceFailed'), err)
      setMessages((prev) => [
        ...prev,
        {
          id: generateUUID(),
          role: 'assistant',
          content: getOperationErrorMessage(t, err, 'managed.quickstart.errors.createResourceFailed'),
        },
      ])
    } finally {
      setIsCreating(false)
    }
  }, [pendingConfirmation, isCreating, agentSecretRef, selectedEngine, t])

  const keepRefining = useCallback(() => {
    setPendingConfirmation(null)
  }, [])

  const selectExistingEnvironment = useCallback((envId: string) => {
    setResourceIds((prev) => {
      const next = { ...prev, [4]: envId }
      resourceIdsRef.current = next
      return next
    })
    setCompletedSteps((prev) => new Set([...prev, 4]))
  }, [])

  const selectExistingVault = useCallback((vaultId: string) => {
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
    const agentDesc = (agent?.system_prompt as string) || (agent?.system as string) || ''
    const tools = (agent?.tools as unknown[]) || []

    const prompt = `Based on this agent configuration, generate ONE short test message (1-2 sentences) that a user would send to verify the agent works. Only output the message text, nothing else.

Agent: ${agentName}
${agentDesc ? `System prompt: ${agentDesc.slice(0, 300)}` : ''}
${tools.length > 0 ? `Tools: ${JSON.stringify(tools).slice(0, 200)}` : ''}`

    try {
      const response = await fetch(`${MANAGED_API_BASE}/quickstart/chat`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify({
          messages: [{ role: 'user', content: prompt }],
          current_step: 5,
          provider: generationSecret?.provider ?? 'claude',
          secret_ref: generationSecret?.secretRef ?? agentSecretRef,
          agent_context: agent,
        }),
      })

      if (!response.ok) {
        return t('managed.quickstart.trialRun.defaultPrompt', { agentName })
      }

      const reader = response.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let text = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        for (const line of lines) {
          if (!line.startsWith('data:')) continue
          const data = line.slice(5).trim()
          if (!data || data === '[DONE]') continue
          try {
            const event = JSON.parse(data)
            if (event.type === 'text_delta') text += event.text || ''
          } catch {
            /* ignore */
          }
        }
      }
      return (
        text.trim() ||
        t('managed.quickstart.trialRun.defaultPrompt', { agentName })
      )
    } catch {
      return t('managed.quickstart.trialRun.defaultPrompt', { agentName })
    }
  }, [agentSecretRef, generationSecret, t])

  return {
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
  }
}
