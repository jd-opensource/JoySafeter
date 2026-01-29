/**
 * VisualizationLayout2 Component
 * Two-panel layout: Tasks (left) | Execution/Results (right with tabs)
 * Clearly shows hierarchy: Tasks are primary, Execution/Results are secondary
 */

import React, { useState } from 'react';

import { ExecutionTree, Task, Session } from '@/types/dynamic/execution';

import { TaskListPanel } from './TaskListPanel';
import { TaskResultPanel } from './TaskResultPanel';
import { VisualizationContainer } from './VisualizationContainer';
import '@/styles/dynamic/visualization/VisualizationLayout2.css';

type DetailTabType = 'execution' | 'results';

interface VisualizationLayout2Props {
  sessions: Session[];
  execution: ExecutionTree | null;
  selectedTaskId: string | undefined;
  onTaskSelect: (taskId: string) => void;
  onGenerateNew: () => void;
  onLoadSubtasks?: (agentId: string, taskId: string, stepId: string) => Promise<void>;
}

/**
 * VisualizationLayout2 component - two-panel layout with clear hierarchy
 */
export const VisualizationLayout2: React.FC<VisualizationLayout2Props> = ({
  sessions,
  execution,
  selectedTaskId,
  onTaskSelect,
  onGenerateNew,
  onLoadSubtasks,
}) => {
  const [detailTab, setDetailTab] = useState<DetailTabType>('execution');
  const [isTasksPanelCollapsed, setIsTasksPanelCollapsed] = useState(false);

  // Flatten tasks to find selected one
  const allTasks = sessions.flatMap(s => s.tasks);
  const selectedTask = selectedTaskId ? allTasks.find((t) => t.id === selectedTaskId) : null;
  const totalTasks = allTasks.length;

  return (
    <div className="visualization-layout2">
      {/* Sidebar Toggle Button - DeepSeek style */}
      <button
        onClick={() => setIsTasksPanelCollapsed(!isTasksPanelCollapsed)}
        className="sidebar-toggle"
        style={{
          left: isTasksPanelCollapsed ? '12px' : '248px',
        }}
        title={isTasksPanelCollapsed ? 'Open sidebar' : 'Close sidebar'}
      >
        {isTasksPanelCollapsed ? (
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
        ) : (
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
        )}
      </button>

      {/* Left Panel: Tasks (Primary) */}
      <div className={`left-panel ${isTasksPanelCollapsed ? 'collapsed' : ''}`}>
        <div style={{ display: isTasksPanelCollapsed ? 'none' : 'flex', flexDirection: 'column', height: '100%' }}>
          <div className="panel-content" style={{ marginTop: 0 }}>
            <TaskListPanel
              sessions={sessions}
              onTaskSelect={onTaskSelect}
              selectedTaskId={selectedTaskId}
            />
          </div>

          <div className="panel-footer">
            <span className="task-count">{sessions.length} sessions, {totalTasks} tasks</span>
          </div>
        </div>
      </div>

      {/* Remove old collapsed button */}
      {false && isTasksPanelCollapsed && (
        <div className="collapsed-button-container">
          <button
            onClick={() => setIsTasksPanelCollapsed(false)}
            className="collapse-btn collapsed"
            title="Expand tasks panel"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M9 18l6-6-6-6"/>
            </svg>
          </button>
        </div>
      )}

      {/* Right Panel: Execution/Results (Secondary) */}
      <div className="right-panel">
        {selectedTask ? (
          <>
            {/* Task Header */}
            <div className="detail-header">
              <div className="task-info">
                <h3>{selectedTask.title}</h3>
                <p className="task-meta">
                  <span className={`status-badge ${selectedTask.status}`}>
                    {selectedTask.status}
                  </span>
                  {/*<span className="meta-item">*/}
                  {/*  <strong>{selectedTask.agent_count}</strong> agents*/}
                  {/*</span>*/}
                  {/*<span className="meta-item">*/}
                  {/*  <strong>{selectedTask.tool_count}</strong> tools*/}
                  {/*</span>*/}
                  {/*<span className="meta-item">*/}
                  {/*  <strong>{selectedTask.success_rate}%</strong> success*/}
                  {/*</span>*/}
                </p>
              </div>
            </div>

            {/* Detail Tabs */}
            <div className="detail-tabs">
              <button
                className={`detail-tab ${detailTab === 'execution' ? 'active' : ''}`}
                onClick={() => setDetailTab('execution')}
              >
                <span className="tab-icon">🔍</span>
                <span className="tab-name">Execution</span>
              </button>
              <button
                className={`detail-tab ${detailTab === 'results' ? 'active' : ''}`}
                onClick={() => setDetailTab('results')}
              >
                <span className="tab-icon">📄</span>
                <span className="tab-name">Results</span>
              </button>
            </div>

            {/* Detail Content */}
            <div className="detail-content">
              {detailTab === 'execution' && execution && (
                <VisualizationContainer
                  execution={execution}
                  onLoadSubtasks={onLoadSubtasks}
                />
              )}
              {detailTab === 'results' && <TaskResultPanel task={selectedTask || null} />}
            </div>
          </>
        ) : (
          <div className="empty-state">
            <div className="empty-icon">👈</div>
            <p>Select a task to view details</p>
          </div>
        )}
      </div>
    </div>
  );
};

VisualizationLayout2.displayName = 'VisualizationLayout2';
