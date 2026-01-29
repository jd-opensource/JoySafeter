/**
 * ExecutionStatusIndicator Component
 * Shows real-time execution status with animated progress
 */

import React, { useEffect, useState } from 'react';

import { formatTimestamp } from '@/lib/utils/dynamic/formatting';
import { ExecutionTree } from '@/types/dynamic/execution';
import '@/styles/dynamic/visualization/ExecutionStatusIndicator.css';

interface ExecutionStatusIndicatorProps {
  execution: ExecutionTree;
}

/**
 * ExecutionStatusIndicator component - displays animated execution status
 */
export const ExecutionStatusIndicator: React.FC<ExecutionStatusIndicatorProps> = ({
  execution,
}) => {
  const [progress, setProgress] = useState(0);
  const [isRunning, setIsRunning] = useState(execution.root_agent.status === 'running');

  // Animate progress while execution is running
  useEffect(() => {
    if (!isRunning) {
      setProgress(100);
      return;
    }

    const interval = setInterval(() => {
      setProgress((prev) => {
        if (prev >= 95) return prev; // Cap at 95% until complete
        return prev + Math.random() * 15;
      });
    }, 500);

    return () => clearInterval(interval);
  }, [isRunning]);

  // Update running status
  useEffect(() => {
    setIsRunning(execution.root_agent.status === 'running');
  }, [execution.root_agent.status]);

  const getStatusColor = (): string => {
    switch (execution.root_agent.status) {
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

  const getStatusLabel = (): string => {
    switch (execution.root_agent.status) {
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

  return (
    <div className="execution-status-indicator">
      <div className="status-header">
        <div className="status-title">
          <span className={`status-badge ${execution.root_agent.status}`}>
            {getStatusLabel()}
          </span>
          <span className="status-time">
            {formatTimestamp(execution.execution_start_time)}
          </span>
        </div>
        <div className="status-stats">
          <span className="stat">
            <strong>{execution.total_agents_count}</strong> Agents
          </span>
          <span className="stat">
            <strong>{execution.total_tools_count}</strong> Tools
          </span>
          <span className="stat">
            <strong>{execution.success_rate}%</strong> Success
          </span>
        </div>
      </div>

      {/* Progress bar for running executions */}
      {isRunning && (
        <div className="progress-container">
          <div className="progress-bar">
            <div
              className="progress-fill"
              style={{
                width: `${progress}%`,
                backgroundColor: getStatusColor(),
              }}
            >
              <span className="progress-text">{Math.round(progress)}%</span>
            </div>
          </div>
          <div className="progress-label">Execution in progress...</div>
        </div>
      )}

      {/* Completed status */}
      {execution.root_agent.status === 'completed' && (
        <div className="completion-message">
          <span className="completion-icon">✓</span>
          <span>Execution completed successfully</span>
        </div>
      )}

      {/* Failed status */}
      {execution.root_agent.status === 'failed' && (
        <div className="failure-message">
          <span className="failure-icon">✕</span>
          <span>{execution.root_agent.error_message || 'Execution failed'}</span>
        </div>
      )}
    </div>
  );
};

ExecutionStatusIndicator.displayName = 'ExecutionStatusIndicator';
