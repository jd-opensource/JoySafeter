/**
 * Execution service for API calls and data fetching
 * Handles communication with backend for execution data
 */

import axios from 'axios';

import { ExecutionTree, Agent, ToolInvocation, ExecutionStatus } from '@/types/dynamic/execution';

import { getApiBaseUrl } from './apiConfig';
import { taskService } from './taskService';

const API_BASE_URL = getApiBaseUrl();

// Backend ExecutionStep response type
interface ExecutionStepResponse {
  id: string;
  task_id: string;
  parent_step_id?: string;
  step_type: 'TOOL' | 'AGENT' | 'CHAIN' | 'THOUGHT';
  name: string;
  input_data: Record<string, any>;
  output_data?: Record<string, any>;
  status: 'RUNNING' | 'COMPLETED' | 'FAILED';
  start_time: string;
  end_time?: string;
  error_message?: string;
  agent_trace?: Record<string, any>;
  children?: ExecutionStepResponse[];
}

/**
 * Load subtasks for an agent_tool and convert them to Agent objects
 * Only loads subtasks created by the specific agent_tool step
 * @param taskId - Parent task ID
 * @param stepId - The step ID that created these subtasks
 */
export async function loadSubtasksForAgent(taskId: string, stepId: string): Promise<Agent[]> {
  try {
    console.log(`[loadSubtasksForAgent] Fetching subtasks for task ${taskId}, step ${stepId}`);
    const { subtasks } = await taskService.getSubtasks(taskId, stepId);
    console.log(`[loadSubtasksForAgent] Found ${subtasks.length} subtasks for step ${stepId}:`, subtasks);

    // Convert each subtask to an Agent by fetching its execution tree
    const subAgents: Agent[] = [];
    for (const subtask of subtasks) {
      try {
        console.log(`[loadSubtasksForAgent] Loading execution for subtask ${subtask.id}, status: ${subtask.status}`);
        const execution = await getExecution(subtask.id);

        // IMPORTANT: Clear loaded_subtasks to ensure lazy loading
        // Grandchildren should only be loaded when user clicks on the child's agent_tool
        const agent = {
          ...execution.root_agent,
          loaded_subtasks: undefined, // Clear any pre-loaded subtasks
        };

        console.log(`[loadSubtasksForAgent] Subtask ${subtask.id} agent:`, {
          id: agent.id,
          name: agent.name,
          level: agent.level,
          status: agent.status,
          toolCount: agent.tool_invocations.length,
          tool_invocations: agent.tool_invocations.map(t => ({
            id: t.id,
            tool_name: t.tool_name,
            status: t.status,
          })),
        });

        subAgents.push(agent);
      } catch (error) {
        console.error(`Failed to load subtask ${subtask.id}:`, error);
      }
    }

    console.log(`[loadSubtasksForAgent] Returning ${subAgents.length} sub-agents`);
    return subAgents;
  } catch (error) {
    console.error(`Failed to load subtasks for task ${taskId}:`, error);
    return [];
  }
}

/**
 * Get a single execution by task ID
 */
export async function getExecution(taskId: string): Promise<ExecutionTree> {
  try {
    const response = await axios.get(`${API_BASE_URL}/api/tasks/${taskId}/with-steps`);
    const data = response.data;
    console.log(`[getExecution] Task ${taskId}:`, {
      status: data.status,
      stepsCount: data.steps?.length || 0,
    });

    // Task = Agent, convert all steps to tool invocations
    // Steps are flat (no parent-child relationship), all belong to this task/agent
    const toolInvocations: ToolInvocation[] = [];

    if (data.steps && data.steps.length > 0) {
      for (const step of data.steps) {
        const startTime = new Date(step.start_time).getTime();
        const endTime = step.end_time ? new Date(step.end_time).getTime() : Date.now();

        toolInvocations.push({
          id: step.id,
          tool_name: step.name,
          tool_description: step.name,
          parameters: step.input_data || {},
          result: step.output_data || {},
          status: step.status.toLowerCase() as ExecutionStatus,
          start_time: startTime,
          end_time: endTime,
          duration_ms: endTime - startTime,
          error_message: step.error_message,
          is_agent_tool: step.name === 'agent_tool',
          task_id: taskId,  // Add task_id for debugging
        });
      }
      console.log(`[getExecution] Task ${taskId} converted ${toolInvocations.length} tool invocations`);
    } else {
      console.log(`[getExecution] Task ${taskId} has no steps`);
    }

    // Create root agent from task data
    const startTime = new Date(data.created_at).getTime();
    const endTime = data.completed_at ? new Date(data.completed_at).getTime() : Date.now();

    // Get agent name: prefer metadata.agent_name, fallback to user_input
    const agentName = (data.metadata && data.metadata.agent_name)
      ? data.metadata.agent_name
      : (data.user_input || 'Agent');

    const rootAgent: Agent = {
      id: taskId,
      name: agentName,  // Use agent_name from metadata if available, otherwise user_input
      task_description: data.user_input || 'Task execution',
      status: data.status.toLowerCase() as ExecutionStatus,
      level: data.level ?? 1,  // Use level from database (default 1)
      start_time: startTime,
      end_time: endTime,
      duration_ms: endTime - startTime,
      tool_invocations: toolInvocations,
      sub_agents: [],
      success_rate: data.status === 'COMPLETED' ? 100 : 0,
      output: data.result_summary ? { result: data.result_summary } : undefined,
      task_id: taskId,
      has_subtasks: toolInvocations.some(tool => tool.tool_name === 'agent_tool'),
      metadata: data.metadata || undefined,  // Include task metadata (contains tools list)
    };

    // Calculate statistics
    const stats = calculateTreeStats(rootAgent);

    return {
      id: taskId,
      root_agent: rootAgent,
      total_duration_ms: rootAgent.duration_ms,
      total_agents_count: stats.agentCount,
      total_tools_count: stats.toolCount,
      success_rate: stats.successRate,
      execution_start_time: rootAgent.start_time,
      execution_end_time: rootAgent.end_time,
      created_at: rootAgent.start_time,
      result_summary: data.result_summary, // Add result_summary from task
    };
  } catch (error) {
    console.error(`[getExecution] Failed to fetch execution for task ${taskId}:`, error);
    throw error;
  }
}

/**
 * Calculate tree statistics
 */
function calculateTreeStats(agent: Agent): { agentCount: number; toolCount: number; successRate: number } {
  let agentCount = 1;
  let toolCount = agent.tool_invocations.length;
  let totalSuccess = agent.success_rate || 0;
  let totalAgents = 1;

  for (const subAgent of agent.sub_agents) {
    const subStats = calculateTreeStats(subAgent);
    agentCount += subStats.agentCount;
    toolCount += subStats.toolCount;
    totalSuccess += subStats.successRate * subStats.agentCount;
    totalAgents += subStats.agentCount;
  }

  return {
    agentCount,
    toolCount,
    successRate: totalAgents > 0 ? totalSuccess / totalAgents : 0,
  };
}

/**
 * List executions for a session
 */
export async function listExecutions(
  sessionId: string,
  limit: number = 10,
  offset: number = 0
): Promise<{ executions: ExecutionTree[]; total: number }> {
  try {
    const response = await axios.get(
      `${API_BASE_URL}/api/tasks/sessions/${sessionId}/tasks?limit=${limit}&offset=${offset}`
    );
    const { tasks, total } = response.data;

    // Fetch execution tree for each task
    const executions = await Promise.all(
      tasks.map((task: any) => getExecution(task.id))
    );

    return {
      executions,
      total,
    };
  } catch (error) {
    console.error('Failed to list executions:', error);
    throw error;
  }
}

/**
 * Create a new execution (not implemented - executions are created by backend)
 */
export async function createExecution(): Promise<ExecutionTree> {
  throw new Error('Creating executions directly is not supported. Executions are created automatically when tasks are executed.');
}

/**
 * Delete an execution (deletes the task)
 */
export async function deleteExecution(taskId: string): Promise<void> {
  try {
    await axios.delete(`${API_BASE_URL}/tasks/${taskId}`);
  } catch (error) {
    console.error('Failed to delete execution:', error);
    throw error;
  }
}

/**
 * Get execution statistics for a session
 */
export async function getExecutionStats(sessionId: string): Promise<{
  totalExecutions: number;
  totalAgents: number;
  totalTools: number;
  averageSuccessRate: number;
}> {
  try {
    const { executions } = await listExecutions(sessionId, 100, 0);

    if (executions.length === 0) {
      return {
        totalExecutions: 0,
        totalAgents: 0,
        totalTools: 0,
        averageSuccessRate: 0,
      };
    }

    const totalAgents = executions.reduce((sum, exec) => sum + exec.total_agents_count, 0);
    const totalTools = executions.reduce((sum, exec) => sum + exec.total_tools_count, 0);
    const averageSuccessRate =
      executions.reduce((sum, exec) => sum + exec.success_rate, 0) / executions.length;

    return {
      totalExecutions: executions.length,
      totalAgents,
      totalTools,
      averageSuccessRate: Math.round(averageSuccessRate),
    };
  } catch (error) {
    console.error('Failed to get execution stats:', error);
    throw error;
  }
}

/**
 * Search executions by query (not implemented yet)
 */
export async function searchExecutions(_sessionId: string, _query: string): Promise<ExecutionTree[]> {
  // TODO: Implement search on backend
  console.warn('Search executions not implemented yet');
  return [];
}

