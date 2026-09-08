'use client'

import { useCallback, useState, type Dispatch, type SetStateAction } from 'react'

import { QUICKSTART_STEP, type QuickstartStepId } from '@/lib/managed/quickstart-flow'
import type {
  QuickstartMcpAuthRequirement,
  QuickstartNetworkingType,
} from '@/lib/managed/quickstart-recommendation-contract'
import type { CredentialGroupId, EnvironmentId } from '@/types/entity-id'
import type { McpAuthRequirement } from '@/types/managed'

export type QuickstartEnvironmentSubStep = 'choose' | 'networking' | 'hosts' | 'selected' | null

export type QuickstartCredentialGroupSubStep = 'choose' | 'name' | 'selected' | null

type EnvironmentAnswers = { choiceLabel?: string; networkingLabel?: string }
type CredentialGroupAnswers = { choiceLabel?: string }

interface EnvironmentState {
  scopeKey: string
  subStep: QuickstartEnvironmentSubStep
  answers: EnvironmentAnswers
  networkingType: QuickstartNetworkingType
  hosts: string
  hostsEdited: boolean
  pendingId: EnvironmentId | null
}

interface CredentialGroupState {
  scopeKey: string
  subStep: QuickstartCredentialGroupSubStep
  answers: CredentialGroupAnswers
  name: string
  credentials: QuickstartMcpCredentialDraft[]
  credentialsEdited: boolean
  pendingId: CredentialGroupId | null
}

export interface QuickstartMcpCredentialDraft {
  name: string
  mcpServerUrl: string
  authRequirement: McpAuthRequirement
  tokenValue: string
}

interface RecommendedMcpServer {
  name: string
  url: string
  authRequirement: QuickstartMcpAuthRequirement
}

export interface QuickstartSecurityFlowController {
  environment: {
    subStep: QuickstartEnvironmentSubStep
    setSubStep: (step: QuickstartEnvironmentSubStep) => void
    answers: EnvironmentAnswers
    setAnswers: Dispatch<SetStateAction<EnvironmentAnswers>>
    networkingType: QuickstartNetworkingType
    setNetworkingType: (type: QuickstartNetworkingType) => void
    hosts: string
    setHosts: (hosts: string) => void
    pendingId: EnvironmentId | null
    setPendingId: (id: EnvironmentId | null) => void
  }
  credentialGroup: {
    subStep: QuickstartCredentialGroupSubStep
    setSubStep: (step: QuickstartCredentialGroupSubStep) => void
    answers: CredentialGroupAnswers
    setAnswers: Dispatch<SetStateAction<CredentialGroupAnswers>>
    name: string
    setName: (name: string) => void
    credentials: QuickstartMcpCredentialDraft[]
    setCredentials: (credentials: QuickstartMcpCredentialDraft[]) => void
    updateCredential: (index: number, update: Partial<QuickstartMcpCredentialDraft>) => void
    pendingId: CredentialGroupId | null
    setPendingId: (id: CredentialGroupId | null) => void
  }
  resetFromStep: (step: QuickstartStepId) => void
}

function createEnvironmentState(scopeKey: string): EnvironmentState {
  return {
    scopeKey,
    subStep: 'choose',
    answers: {},
    networkingType: 'limited',
    hosts: '',
    hostsEdited: false,
    pendingId: null,
  }
}

function createCredentialGroupState(scopeKey: string): CredentialGroupState {
  return {
    scopeKey,
    subStep: 'choose',
    answers: {},
    name: '',
    credentials: [],
    credentialsEdited: false,
    pendingId: null,
  }
}

function recommendedCredentialDrafts(
  servers: RecommendedMcpServer[],
): QuickstartMcpCredentialDraft[] {
  return servers.map((server) => ({
    name: server.name,
    mcpServerUrl: server.url,
    authRequirement: server.authRequirement,
    tokenValue: '',
  }))
}

function applyStateAction<T>(current: T, action: SetStateAction<T>): T {
  return typeof action === 'function' ? (action as (value: T) => T)(current) : action
}

export function useQuickstartSecurityFlow({
  scopeKey,
  suggestedAllowlist,
  recommendedMcpServers,
}: {
  scopeKey: string
  suggestedAllowlist: string
  recommendedMcpServers: RecommendedMcpServer[]
}): QuickstartSecurityFlowController {
  const [storedEnvironment, setStoredEnvironment] = useState(() => createEnvironmentState(scopeKey))
  const [storedCredentialGroup, setStoredCredentialGroup] = useState(() =>
    createCredentialGroupState(scopeKey),
  )

  const environment =
    storedEnvironment.scopeKey === scopeKey ? storedEnvironment : createEnvironmentState(scopeKey)
  const credentialGroup =
    storedCredentialGroup.scopeKey === scopeKey
      ? storedCredentialGroup
      : createCredentialGroupState(scopeKey)
  const visibleCredentials = credentialGroup.credentialsEdited
    ? credentialGroup.credentials
    : recommendedCredentialDrafts(recommendedMcpServers)

  const updateEnvironment = useCallback(
    (update: (current: EnvironmentState) => EnvironmentState) => {
      setStoredEnvironment((stored) =>
        update(stored.scopeKey === scopeKey ? stored : createEnvironmentState(scopeKey)),
      )
    },
    [scopeKey],
  )
  const updateCredentialGroup = useCallback(
    (update: (current: CredentialGroupState) => CredentialGroupState) => {
      setStoredCredentialGroup((stored) =>
        update(stored.scopeKey === scopeKey ? stored : createCredentialGroupState(scopeKey)),
      )
    },
    [scopeKey],
  )

  const resetFromStep = useCallback(
    (step: QuickstartStepId) => {
      if (step <= QUICKSTART_STEP.ENVIRONMENT) {
        setStoredEnvironment(createEnvironmentState(scopeKey))
      }
      if (step <= QUICKSTART_STEP.CREDENTIAL_GROUP) {
        setStoredCredentialGroup(createCredentialGroupState(scopeKey))
      }
    },
    [scopeKey],
  )

  return {
    environment: {
      subStep: environment.subStep,
      setSubStep: (subStep) => updateEnvironment((current) => ({ ...current, subStep })),
      answers: environment.answers,
      setAnswers: (answers) =>
        updateEnvironment((current) => ({
          ...current,
          answers: applyStateAction(current.answers, answers),
        })),
      networkingType: environment.networkingType,
      setNetworkingType: (networkingType) =>
        updateEnvironment((current) => ({ ...current, networkingType })),
      hosts: environment.hostsEdited ? environment.hosts : suggestedAllowlist,
      setHosts: (hosts) =>
        updateEnvironment((current) => ({ ...current, hosts, hostsEdited: true })),
      pendingId: environment.pendingId,
      setPendingId: (pendingId) => updateEnvironment((current) => ({ ...current, pendingId })),
    },
    credentialGroup: {
      subStep: credentialGroup.subStep,
      setSubStep: (subStep) => updateCredentialGroup((current) => ({ ...current, subStep })),
      answers: credentialGroup.answers,
      setAnswers: (answers) =>
        updateCredentialGroup((current) => ({
          ...current,
          answers: applyStateAction(current.answers, answers),
        })),
      name: credentialGroup.name,
      setName: (name) => updateCredentialGroup((current) => ({ ...current, name })),
      credentials: visibleCredentials,
      setCredentials: (credentials) =>
        updateCredentialGroup((current) => ({
          ...current,
          credentials,
          credentialsEdited: true,
        })),
      updateCredential: (index, update) =>
        updateCredentialGroup((current) => {
          const credentials = current.credentialsEdited
            ? current.credentials
            : recommendedCredentialDrafts(recommendedMcpServers)
          return {
            ...current,
            credentials: credentials.map((credential, credentialIndex) =>
              credentialIndex === index ? { ...credential, ...update } : credential,
            ),
            credentialsEdited: true,
          }
        }),
      pendingId: credentialGroup.pendingId,
      setPendingId: (pendingId) => updateCredentialGroup((current) => ({ ...current, pendingId })),
    },
    resetFromStep,
  }
}
