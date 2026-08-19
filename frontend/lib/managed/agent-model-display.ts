import type { ModelConnectionSummary } from '@/types/managed'

export interface AgentModelSource {
  model_credential_id?: string | null
  model_connection?: ModelConnectionSummary | null
}

export type AgentModelDisplayKind = 'connection' | 'connection_unavailable' | 'unbound'

export interface AgentModelDisplayState {
  kind: AgentModelDisplayKind
  modelLabel?: string
  connection?: ModelConnectionSummary
  connectionId?: string | null
}

function nonBlank(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  return trimmed.length > 0 ? trimmed : null
}

export function getAgentModelDisplayState(
  agent: AgentModelSource | null | undefined,
): AgentModelDisplayState {
  const modelConnection = agent?.model_connection ?? null
  const connectionId = agent?.model_credential_id ?? modelConnection?.id ?? null

  if (modelConnection) {
    return {
      kind: 'connection',
      modelLabel:
        nonBlank(modelConnection.name) ?? nonBlank(modelConnection.model) ?? connectionId ?? undefined,
      connection: modelConnection,
      connectionId,
    }
  }

  if (!connectionId) return { kind: 'unbound' }

  return { kind: 'connection_unavailable', connectionId }
}

export function getAgentModelSearchTokens(agent: AgentModelSource | null | undefined): string[] {
  const state = getAgentModelDisplayState(agent)
  return [
    state.modelLabel,
    state.connection?.name,
    state.connection?.provider,
    state.connection?.protocol,
    state.connection?.model,
    state.connectionId,
    state.kind,
  ].filter((value): value is string => Boolean(value))
}
