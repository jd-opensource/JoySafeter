/**
 * TaskListPanel Component
 * Displays a flat list of tasks for the current session
 */

import React from 'react';

import { formatDuration } from '@/lib/utils/dynamic/formatting';
import { Session } from '@/types/dynamic/execution';
import '@/styles/dynamic/visualization/TaskListPanel.css';

interface TaskListPanelProps {
  sessions: Session[];
  onTaskSelect: (taskId: string) => void;
  selectedTaskId?: string;
}

/**
 * TaskListPanel component - displays flat list of tasks
 */
export const TaskListPanel: React.FC<TaskListPanelProps> = ({
  sessions,
  onTaskSelect,
  selectedTaskId,
}) => {
  const getStatusColor = (status: string): string => {
    switch (status) {
      case 'completed':
        return '#10b981';
      case 'running':
        return '#3b82f6';
      case 'failed':
        return '#ef4444';
      case 'pending':
        return '#9ca3af';
      default:
        return '#6b7280';
    }
  };

  const getStatusLabel = (status: string): string => {
    switch (status) {
      case 'completed':
        return 'Completed';
      case 'running':
        return 'Running';
      case 'failed':
        return 'Failed';
      case 'pending':
        return 'Pending';
      default:
        return 'Unknown';
    }
  };

  // Flatten all tasks from all sessions and filter only root tasks (parent_id is null)
  const allTasks = sessions.flatMap(s => s.tasks);
  const rootTasks = allTasks.filter(task => !task.parent_id);

  if (rootTasks.length === 0) {
    return (
      <div className="task-list-panel">
        <div className="task-list-empty">
          <p>No tasks available</p>
        </div>
      </div>
    );
  }

  return (
    <div className="task-list-panel">
      <div className="task-list-direct">
        {rootTasks.map((task) => (
          <div
            key={task.id}
            className={`task-list-item ${selectedTaskId === task.id ? 'selected' : ''}`}
            onClick={() => onTaskSelect(task.id)}
          >
            {/* Task Title */}
            <div className="task-list-title">{task.title}</div>

            {/* Task Status */}
            <div
              className="task-list-status"
              style={{ backgroundColor: getStatusColor(task.status) }}
            >
              {getStatusLabel(task.status)}
            </div>

            {/* Task Metrics */}
            {/*<div className="task-list-metrics">*/}
            {/*  <span className="metric-badge">{task.agent_count} agents</span>*/}
            {/*  <span className="metric-badge">{task.tool_count} tools</span>*/}
            {/*  <span className="metric-badge">{task.success_rate}%</span>*/}
            {/*</div>*/}

            {/* Task Duration */}
            <div className="task-list-duration">
              {formatDuration(task.duration_ms)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

TaskListPanel.displayName = 'TaskListPanel';
