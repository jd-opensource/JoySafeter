import {
  parseAgentId,
  parseSessionId,
  parseTaskId,
  parseTriggerId,
  type SessionId,
  type TaskId,
  type TriggerId,
} from '@/types/entity-id'

import type { AgentTrigger, TriggerFireResult, TriggerRun } from './triggers'

type RawAgentTrigger = Omit<
  AgentTrigger,
  | 'id'
  | 'agent_id'
  | 'pinned_session_id'
  | 'reusable_session_id'
  | 'last_task_id'
  | 'last_session_id'
> & {
  id: string
  agent_id: string
  pinned_session_id: string | null
  reusable_session_id: string | null
  last_task_id: string | null
  last_session_id: string | null
}

type RawTriggerRun = Omit<TriggerRun, 'id' | 'trigger_id' | 'chat_session_id'> & {
  id: string
  trigger_id: string | null
  chat_session_id: string | null
}

type RawTriggerFireResult = Omit<TriggerFireResult, 'task_id' | 'session_id'> & {
  task_id: string | null
  session_id: string | null
}

function parseNullableId<T>(value: string | null, parse: (raw: string) => T): T | null {
  return value === null ? null : parse(value)
}

export function parseAgentTriggerResponse(response: RawAgentTrigger): AgentTrigger {
  return {
    ...response,
    id: parseTriggerId(response.id),
    agent_id: parseAgentId(response.agent_id),
    pinned_session_id: parseNullableId<SessionId>(response.pinned_session_id, parseSessionId),
    reusable_session_id: parseNullableId<SessionId>(response.reusable_session_id, parseSessionId),
    last_task_id: parseNullableId<TaskId>(response.last_task_id, parseTaskId),
    last_session_id: parseNullableId<SessionId>(response.last_session_id, parseSessionId),
  }
}

export function parseAgentTriggerListResponse(response: RawAgentTrigger[]): AgentTrigger[] {
  return response.map(parseAgentTriggerResponse)
}

export function parseTriggerRunResponse(response: unknown): TriggerRun {
  const raw = response as RawTriggerRun
  return {
    ...raw,
    id: parseTaskId(raw.id),
    trigger_id: parseNullableId<TriggerId>(raw.trigger_id, parseTriggerId),
    chat_session_id: parseNullableId<SessionId>(raw.chat_session_id, parseSessionId),
  }
}

export function parseTriggerFireResultResponse(response: RawTriggerFireResult): TriggerFireResult {
  return {
    ...response,
    task_id: parseNullableId<TaskId>(response.task_id, parseTaskId),
    session_id: parseNullableId<SessionId>(response.session_id, parseSessionId),
  }
}
