/**
 * Task Service - API client for task execution tracking
 * Handles all HTTP requests related to task and execution step data
 */

import axios from 'axios';

import { getApiBaseUrl } from './apiConfig';

const API_BASE_URL = getApiBaseUrl();
const USE_MOCK_BACKEND = process.env.NEXT_PUBLIC_USE_MOCK_BACKEND === 'true';

export interface TaskResponse {
  id: string;
  session_id: string;
  user_input: string;
  status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED';
  created_at: string;
  updated_at: string;
  completed_at?: string;
  result_summary?: string;
  metadata?: Record<string, any>;
  parent_id?: string | null;
  level?: number;  // Task hierarchy level
}

export interface ExecutionStepResponse {
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

class TaskService {
  /**
   * Get task details by ID
   */
  async getTask(taskId: string): Promise<TaskResponse> {
    if (USE_MOCK_BACKEND) {
      throw new Error('Mock backend not supported in Next.js');
    }

    const response = await axios.get<TaskResponse>(`${API_BASE_URL}/api/tasks/${taskId}`);
    return response.data;
  }

  /**
   * Get execution steps for a task
   * @param taskId - Task ID
   * @param format - 'flat' or 'tree' format
   */
  async getExecutionSteps(
    taskId: string,
    format: 'flat' | 'tree' = 'tree'
  ): Promise<ExecutionStepResponse[]> {
    const response = await axios.get<ExecutionStepResponse[]>(
      `${API_BASE_URL}/api/tasks/${taskId}/steps?format=${format}`
    );
    return response.data;
  }

  /**
   * Get tasks for a session
   */
  async getSessionTasks(
    sessionId: string,
    limit: number = 50,
    offset: number = 0
  ): Promise<{ tasks: TaskResponse[]; total: number }> {
    const response = await axios.get<{ tasks: TaskResponse[]; total: number }>(
      `${API_BASE_URL}/api/tasks/sessions/${sessionId}/tasks?limit=${limit}&offset=${offset}`
    );
    return response.data;
  }

  /**
   * Get subtasks for a task
   * @param taskId - Parent task ID
   * @param createdByStepId - Optional step ID to filter subtasks created by a specific step
   */
  async getSubtasks(taskId: string, createdByStepId?: string): Promise<{ subtasks: TaskResponse[]; total: number }> {
    const params = createdByStepId ? `?created_by_step_id=${createdByStepId}` : '';
    const response = await axios.get<{ subtasks: TaskResponse[]; total: number }>(
      `${API_BASE_URL}/api/tasks/${taskId}/subtasks${params}`
    );
    return response.data;
  }

  /**
   * Create a new task
   */
  async createTask(
    sessionId: string,
    userInput: string,
    parentId?: string
  ): Promise<TaskResponse> {
    const response = await axios.post<TaskResponse>(`${API_BASE_URL}/tasks`, {
      session_id: sessionId,
      user_input: userInput,
      parent_id: parentId,
    });
    return response.data;
  }

  /**
   * Update task status
   */
  async updateTaskStatus(
    taskId: string,
    status: TaskResponse['status']
  ): Promise<TaskResponse> {
    const response = await axios.patch<TaskResponse>(`${API_BASE_URL}/tasks/${taskId}`, {
      status,
    });
    return response.data;
  }

  /**
   * Delete a task
   */
  async deleteTask(taskId: string): Promise<void> {
    await axios.delete(`${API_BASE_URL}/tasks/${taskId}`);
  }
}

export const taskService = new TaskService();
