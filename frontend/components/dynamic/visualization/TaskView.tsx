/**
 * TaskView Component
 * Displays tasks as the primary visualization dimension
 * Each task shows its execution tree, timeline, and tool invocations
 */

import React, { useState } from 'react';

import { formatDuration } from '@/lib/utils/dynamic/formatting';
import { Task } from '@/types/dynamic/execution';
import '@/styles/dynamic/visualization/TaskView.css';

interface TaskViewProps {
  tasks: Task[];
  onTaskSelect: (taskId: string) => void;
  selectedTaskId?: string;
}

/**
 * TaskView component - displays tasks with execution details
 */
export const TaskView: React.FC<TaskViewProps> = ({
  tasks,
  onTaskSelect,
  selectedTaskId,
}) => {
  const [expandedTaskId, setExpandedTaskId] = useState<string | null>(
    selectedTaskId || (tasks.length > 0 ? tasks[0].id : null)
  );

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

  const handleTaskClick = (taskId: string) => {
    setExpandedTaskId(expandedTaskId === taskId ? null : taskId);
    onTaskSelect(taskId);
  };

  if (tasks.length === 0) {
    return (
      <div className="task-view">
        <div className="task-empty">
          <p>No tasks available</p>
        </div>
      </div>
    );
  }

  return (
    <div className="task-view">
      <div className="task-list">
        {tasks.map((task, index) => (
          <div
            key={task.id}
            className={`task-card ${expandedTaskId === task.id ? 'expanded' : ''}`}
            onClick={() => handleTaskClick(task.id)}
          >
            {/* Task Header */}
            <div className="task-header">
              <div className="task-number">Task {index + 1}</div>
              <div className="task-title">{task.title}</div>
              <div
                className="task-status"
                style={{ backgroundColor: getStatusColor(task.status) }}
              >
                {getStatusLabel(task.status)}
              </div>
            </div>

            {/* Task Description */}
            <div className="task-description">{task.description}</div>

            {/* Task Metrics */}
            <div className="task-metrics">
              <div className="metric">
                <span className="metric-label">Duration:</span>
                <span className="metric-value">{formatDuration(task.duration_ms)}</span>
              </div>
              <div className="metric">
                <span className="metric-label">Agents:</span>
                <span className="metric-value">{task.agent_count}</span>
              </div>
              <div className="metric">
                <span className="metric-label">Tools:</span>
                <span className="metric-value">{task.tool_count}</span>
              </div>
              <div className="metric">
                <span className="metric-label">Success:</span>
                <span className="metric-value">{task.success_rate}%</span>
              </div>
            </div>

            {/* Progress Bar */}
            <div className="task-progress">
              <div className="progress-bar">
                <div
                  className="progress-fill"
                  style={{
                    width: `${task.success_rate}%`,
                    backgroundColor: getStatusColor(task.status),
                  }}
                />
              </div>
            </div>

            {/* Error Message */}
            {task.error_message && (
              <div className="task-error">
                <span className="error-icon">⚠️</span>
                <span className="error-text">{task.error_message}</span>
              </div>
            )}

            {/* Expanded Details */}
            {expandedTaskId === task.id && (
              <div className="task-details">
                <div className="detail-section">
                  <h4>Task Information</h4>
                  <div className="detail-content">
                    <div className="detail-row">
                      <span className="detail-label">ID:</span>
                      <span className="detail-value">{task.id}</span>
                    </div>
                    <div className="detail-row">
                      <span className="detail-label">Execution ID:</span>
                      <span className="detail-value">{task.execution_id}</span>
                    </div>
                    <div className="detail-row">
                      <span className="detail-label">Root Agent:</span>
                      <span className="detail-value">{task.root_agent_id}</span>
                    </div>
                    <div className="detail-row">
                      <span className="detail-label">Start Time:</span>
                      <span className="detail-value">
                        {new Date(task.start_time).toLocaleString()}
                      </span>
                    </div>
                    <div className="detail-row">
                      <span className="detail-label">End Time:</span>
                      <span className="detail-value">
                        {new Date(task.end_time).toLocaleString()}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
};

TaskView.displayName = 'TaskView';
