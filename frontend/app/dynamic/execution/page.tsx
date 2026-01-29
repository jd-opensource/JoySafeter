'use client';

/**
 * ExecutionVisualizationPage
 * Main page for agent execution visualization
 * Migrated from frontend_dynamic/web to Next.js App Router
 */

import { useRouter, useSearchParams } from 'next/navigation';
import React, { useEffect, useState, useCallback, useRef } from 'react';

import { VisualizationLayout2 } from '@/components/dynamic/visualization/VisualizationLayout2';
import { getExecution, loadSubtasksForAgent } from '@/lib/api/dynamic/executionService';
import { taskService } from '@/lib/api/dynamic/taskService';
import { useExecutionStore } from '@/stores/dynamic/executionStore';
import { useUserStore } from '@/stores/dynamic/userStore';
import { ExecutionTree, Session, Task, ExecutionStatus, Agent } from '@/types/dynamic/execution';
import '@/styles/dynamic/visualization/ExecutionVisualizationPage.css';

export default function ExecutionVisualizationPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [executions, setExecutions] = useState<ExecutionTree[]>([]);
  const [execution, setExecution] = useState<ExecutionTree | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const { userId, setUserId } = useUserStore();
  const updateExecution = useExecutionStore((state) => state.updateExecution);

  // Get initial params from URL
  const initialUserId = searchParams.get('userId') || undefined;
  const initialSessionId = searchParams.get('sessionId') || undefined;
  const initialTaskId = searchParams.get('taskId') || undefined;

  // Set userId from URL parameter if provided
  useEffect(() => {
    if (initialUserId) {
      setUserId(initialUserId);
    }
  }, [initialUserId, setUserId]);

  // Load data on mount (only once)
  useEffect(() => {
    const loadData = async () => {
      try {
        setLoading(true);

        {
          // Load real data from API
          // For now, use the session ID from URL or default
          const sessionId = initialSessionId || 'default_session';

          try {
            const { tasks } = await taskService.getSessionTasks(sessionId, 50, 0);

            // Convert TaskResponse to Task format
            const convertedTasks: Task[] = tasks.map(t => ({
              id: t.id,
              session_id: t.session_id,
              title: t.user_input.slice(0, 50),
              description: t.user_input,
              status: t.status.toLowerCase() as ExecutionStatus,
              start_time: new Date(t.created_at).getTime(),
              end_time: t.completed_at ? new Date(t.completed_at).getTime() : Date.now(),
              duration_ms: t.completed_at
                ? new Date(t.completed_at).getTime() - new Date(t.created_at).getTime()
                : Date.now() - new Date(t.created_at).getTime(),
              execution_id: t.id,
              root_agent_id: `agent_${t.id}`,
              agent_count: 0,
              tool_count: 0,
              success_rate: t.status === 'COMPLETED' ? 100 : 0,
              result_summary: t.result_summary,
              parent_id: t.parent_id || null, // Add parent_id field
            }));

            // Create a session from tasks
            // Use first task's title as session title, or show full session ID
            const sessionTitle = convertedTasks[0]?.title
              ? `${convertedTasks[0].title.slice(0, 30)}${convertedTasks[0].title.length > 30 ? '...' : ''}`
              : sessionId;

            const realSession: Session = {
              id: sessionId,
              title: sessionTitle,
              created_at: convertedTasks[0]?.start_time || Date.now(),
              tasks: convertedTasks,
            };

            setSessions([realSession]);

            // Fetch real execution trees for each task
            const realExecutions: ExecutionTree[] = [];
            for (const task of convertedTasks) {
              try {
                const execution = await getExecution(task.id);
                realExecutions.push(execution);
              } catch (error) {
                console.error(`Failed to fetch execution for task ${task.id}:`, error);
                // Create a placeholder execution tree on error to maintain array alignment
                realExecutions.push({
                  id: task.id,
                  root_agent: {
                    id: `agent_${task.id}`,
                    name: 'Root Agent',
                    task_description: task.description,
                    status: task.status,
                    level: 0,
                    start_time: task.start_time,
                    end_time: task.end_time,
                    duration_ms: task.duration_ms,
                    tool_invocations: [],
                    sub_agents: [],
                    success_rate: task.success_rate,
                  },
                  total_duration_ms: task.duration_ms,
                  total_agents_count: 0,
                  total_tools_count: 0,
                  success_rate: task.success_rate,
                  execution_start_time: task.start_time,
                  execution_end_time: task.end_time,
                  created_at: task.start_time,
                });
              }
            }
            setExecutions(realExecutions);
          } catch (error) {
            console.error('Failed to load real data:', error);
            // Show error state instead of falling back to mock
            setSessions([]);
            setExecutions([]);
          }
        }
      } catch (error) {
        console.error('Failed to load execution data:', error);
      } finally {
        setLoading(false);
      }
    };

    loadData();
  }, [initialSessionId]);

  // Handle initial selection and URL changes
  useEffect(() => {
    if (loading || sessions.length === 0) return;

    if (initialTaskId) {
      // Select task from URL
      const task = sessions.flatMap(s => s.tasks).find(t => t.id === initialTaskId);
      if (task) {
        const exec = executions.find(e => e.id === task.id);
        if (exec) {
            setSelectedTaskId(task.id);
            setExecution(exec);
            updateExecution(exec);
        }
      }
    } else if (executions.length > 0) {
      // Select first task by default
      const firstTask = sessions.flatMap(s => s.tasks)[0];
      if (firstTask) {
        const exec = executions.find(e => e.id === firstTask.id);
        if (exec) {
          setSelectedTaskId(firstTask.id);
          setExecution(exec);
          updateExecution(exec);
      }
    }
  }
    }, [loading, sessions, executions, initialTaskId, updateExecution]);

  // Check if a task should be auto-refreshed (created within 1 hour and status is running)
  const shouldAutoRefresh = useCallback((agent: Agent): boolean => {
    const oneHourAgo = Date.now() - 60 * 60 * 1000; // 1 hour in milliseconds
    const isRecent = agent.start_time > oneHourAgo;
    const isRunning = agent.status === 'running';
    return isRecent && isRunning;
  }, []);

  // Refresh the current selected task execution
  const refreshCurrentTask = useCallback(async () => {
    if (!selectedTaskId) return;

    try {
      const currentExec = executions.find(e => e.id === selectedTaskId);
      const updatedExecution = await getExecution(selectedTaskId);

      // Preserve tool.loaded_subtasks from current execution
      if (currentExec) {
        const preserveToolSubtasks = (oldAgent: Agent, newAgent: Agent): Agent => {
          // Preserve loaded_subtasks for each tool
          const preservedTools = newAgent.tool_invocations.map(newTool => {
            const oldTool = oldAgent.tool_invocations.find(t => t.id === newTool.id);
            if (oldTool?.loaded_subtasks) {
              return {
                ...newTool,
                loaded_subtasks: oldTool.loaded_subtasks,
              };
            }
            return newTool;
          });

          return {
            ...newAgent,
            tool_invocations: preservedTools,
            sub_agents: newAgent.sub_agents.map((subAgent, index) => {
              const oldSubAgent = oldAgent.sub_agents[index];
              if (oldSubAgent) {
                return preserveToolSubtasks(oldSubAgent, subAgent);
              }
              return subAgent;
            }),
          };
        };

        const mergedRootAgent = preserveToolSubtasks(currentExec.root_agent, updatedExecution.root_agent);
        const mergedExecution: ExecutionTree = {
          ...updatedExecution,
          root_agent: mergedRootAgent,
        };

        // Update executions array
        const updatedExecutions = executions.map(e =>
          e.id === selectedTaskId ? mergedExecution : e
        );
        setExecutions(updatedExecutions);

        // Update current execution
        setExecution(mergedExecution);
        updateExecution(mergedExecution);

        // Update sessions task status
        const updatedSessions = sessions.map(session => ({
          ...session,
          tasks: session.tasks.map(task => {
            if (task.id === selectedTaskId) {
              return {
                ...task,
                status: mergedExecution.root_agent.status,
                end_time: mergedExecution.root_agent.end_time,
                duration_ms: mergedExecution.root_agent.duration_ms,
              };
            }
            return task;
          }),
        }));
        setSessions(updatedSessions);
      }
    } catch (error) {
      console.error(`Failed to refresh task ${selectedTaskId}:`, error);
    }
  }, [selectedTaskId, executions, sessions, updateExecution]);

  // Auto-refresh for running tasks created within 1 hour
  const intervalRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    // Clear existing interval
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }

    // Check if current execution should be auto-refreshed
    if (execution && shouldAutoRefresh(execution.root_agent)) {
      // Set up 3-second interval
      intervalRef.current = setInterval(() => {
        refreshCurrentTask();
      }, 5000);

      console.log('[AutoRefresh] Started 3s refresh interval for task:', selectedTaskId);
    }

    // Cleanup on unmount
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        console.log('[AutoRefresh] Cleared refresh interval');
      }
};
  }, [execution, selectedTaskId, shouldAutoRefresh, refreshCurrentTask]);

  // Handle task selection
  const handleTaskSelect = useCallback((taskId: string) => {
    setSelectedTaskId(taskId);
    const exec = executions.find(e => e.id === taskId);
    if (exec) {
      setExecution(exec);
      updateExecution(exec);

      // Update URL
      const params = new URLSearchParams(searchParams.toString());
      params.set('taskId', taskId);
      if (initialSessionId) {
        params.set('sessionId', initialSessionId);
      }
      router.push(`/dynamic/execution?${params.toString()}`, { scroll: false });
    }
  }, [executions, updateExecution, searchParams, initialSessionId, router]);

  // Handle loading subtasks for an agent_tool
  const handleLoadSubtasks = useCallback(async (_agentId: string, taskId: string, stepId: string) => {
    try {
      console.log(`[ExecutionVisualizationPage] Loading subtasks for step ${stepId}, task ${taskId}`);
      const subAgents = await loadSubtasksForAgent(taskId, stepId);

      // Update execution tree with loaded subtasks on the specific tool
      const currentExec = executions.find(e => e.id === taskId);
      if (currentExec) {
        // Find the tool and update its loaded_subtasks
        const findAndUpdateTool = (agent: Agent): Agent => {
          // Update tool_invocations to add loaded_subtasks to the specific tool
          const updatedTools = agent.tool_invocations.map(tool => {
            if (tool.id === stepId) {
              return {
                ...tool,
                loaded_subtasks: subAgents,
              };
            }
            return tool;
          });

          return {
            ...agent,
            tool_invocations: updatedTools,
            sub_agents: agent.sub_agents.map(findAndUpdateTool),
          };
        };

        const updatedRootAgent = findAndUpdateTool(currentExec.root_agent);
        const updatedExecution: ExecutionTree = {
          ...currentExec,
          root_agent: updatedRootAgent,
        };

        // Update executions array
        const updatedExecutions = executions.map(e =>
          e.id === taskId ? updatedExecution : e
        );
        setExecutions(updatedExecutions);

        // Update current execution if it's selected
        if (selectedTaskId === taskId) {
          setExecution(updatedExecution);
          updateExecution(updatedExecution);
        }

        console.log(`[ExecutionVisualizationPage] Loaded ${subAgents.length} subtasks for step ${stepId}`);
      }
    } catch (error) {
      console.error(`Failed to load subtasks for step ${stepId}:`, error);
    }
  }, [executions, selectedTaskId, updateExecution]);

  // Handle generating new task
  const handleGenerateNew = useCallback(() => {
    router.push('/dynamic/chat');
  }, [router]);

  if (loading) {
    return (
      <div className="execution-visualization-page loading">
        <div className="loading-spinner">Loading execution data...</div>
      </div>
    );
  }

  if (sessions.length === 0) {
    return (
      <div className="execution-visualization-page empty">
        <div className="empty-state">
          <h2>No Execution Data</h2>
          <p>No tasks found for this session. Start a new conversation to generate execution data.</p>
          <button onClick={handleGenerateNew} className="generate-button">
            Go to Chat
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="execution-visualization-page">
      <VisualizationLayout2
        sessions={sessions}
        execution={execution}
        selectedTaskId={selectedTaskId || undefined}
        onTaskSelect={handleTaskSelect}
        onGenerateNew={handleGenerateNew}
        onLoadSubtasks={handleLoadSubtasks}
      />
    </div>
  );
}
