import { apiPost } from '@/lib/api-client'
import { agentRunService } from '@/services/agentRunService'

export interface StartRunParams {
  releaseId: string
  prompt: string
  workspaceId: string
  threadId?: string
  taskId?: string
}

export interface RunResult {
  id: string
  current_execution_id: string
  status: string
}

export const executionAdapter = {
  async startRun(params: StartRunParams): Promise<RunResult> {
    return apiPost<RunResult>('runs', {
      release_id: params.releaseId,
      goal: params.prompt,
      workspace_id: params.workspaceId,
      trigger_source: 'api',
      thread_id: params.threadId,
      task_id: params.taskId,
    })
  },

  subscribeToExecution(executionId: string): WebSocket {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/executions`)
    ws.onopen = () => {
      ws.send(JSON.stringify({ type: 'subscribe', execution_id: executionId }))
    }
    return ws
  },

  async cancelRun(runId: string): Promise<void> {
    await agentRunService.cancel(runId)
  },

  async injectMessage(executionId: string, message: string): Promise<void> {
    await agentRunService.sendMessage(executionId, message)
  },

  async getExecutionId(runId: string): Promise<string> {
    const run = await agentRunService.get(runId)
    return run.current_execution_id!
  },
}
