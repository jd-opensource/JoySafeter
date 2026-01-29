/**
 * VisualizationLayout Component
 * Main layout with tab-based navigation for Tasks, Execution, and Results
 */

import React, { useState } from 'react';

import { ExecutionTree, Task } from '@/types/dynamic/execution';

import { TaskResultPanel } from './TaskResultPanel';
import { TaskView } from './TaskView';
import { VisualizationContainer } from './VisualizationContainer';
import '@/styles/dynamic/visualization/VisualizationLayout.css';

type TabType = 'tasks' | 'execution' | 'results';

interface VisualizationLayoutProps {
  tasks: Task[];
  execution: ExecutionTree | null;
  selectedTaskId: string | undefined;
  onTaskSelect: (taskId: string) => void;
  onGenerateNew: () => void;
}

/**
 * VisualizationLayout component - tab-based layout for visualization
 */
export const VisualizationLayout: React.FC<VisualizationLayoutProps> = ({
  tasks,
  execution,
  selectedTaskId,
  onTaskSelect,
  onGenerateNew,
}) => {
  const [activeTab, setActiveTab] = useState<TabType>('tasks');
  const selectedTask = selectedTaskId ? tasks.find((t) => t.id === selectedTaskId) : null;

  return (
    <div className="visualization-layout">
      {/* Tab Navigation */}
      <div className="tab-navigation">
        <div className="tab-list">
          <button
            className={`tab-button ${activeTab === 'tasks' ? 'active' : ''}`}
            onClick={() => setActiveTab('tasks')}
          >
            <span className="tab-icon">📋</span>
            <span className="tab-label">Tasks</span>
            <span className="tab-badge">{tasks.length}</span>
          </button>

          <button
            className={`tab-button ${activeTab === 'execution' ? 'active' : ''}`}
            onClick={() => setActiveTab('execution')}
            disabled={!execution}
          >
            <span className="tab-icon">🔍</span>
            <span className="tab-label">Execution</span>
            {execution && <span className={`tab-status ${execution.root_agent.status}`} />}
          </button>

          <button
            className={`tab-button ${activeTab === 'results' ? 'active' : ''}`}
            onClick={() => setActiveTab('results')}
            disabled={!selectedTask}
          >
            <span className="tab-icon">📄</span>
            <span className="tab-label">Results</span>
            {selectedTask && <span className={`tab-status ${selectedTask.status}`} />}
          </button>
        </div>

        <div className="tab-actions">
          <button
            onClick={onGenerateNew}
            className="generate-btn-tab"
            title="Generate new task"
          >
            + New Task
          </button>
        </div>
      </div>

      {/* Tab Content */}
      <div className="tab-content">
        {/* Tasks Tab */}
        {activeTab === 'tasks' && (
          <div className="tab-pane active">
            <div className="tab-header">
              <h2>Tasks from Chat</h2>
              <p className="tab-description">
                {tasks.length} task{tasks.length !== 1 ? 's' : ''} available
              </p>
            </div>
            <div className="tab-body">
              <TaskView
                tasks={tasks}
                onTaskSelect={(taskId) => {
                  onTaskSelect(taskId);
                  setActiveTab('execution');
                }}
                selectedTaskId={selectedTaskId}
              />
            </div>
          </div>
        )}

        {/* Execution Tab */}
        {activeTab === 'execution' && (
          <div className="tab-pane active">
            <div className="tab-header">
              <h2>Execution Details</h2>
              {selectedTask && (
                <p className="tab-description">
                  {selectedTask.title} • {selectedTask.status}
                </p>
              )}
            </div>
            <div className="tab-body">
              {execution ? (
                <VisualizationContainer execution={execution} />
              ) : (
                <div className="empty-state">
                  <p>Select a task to view execution details</p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Results Tab */}
        {activeTab === 'results' && (
          <div className="tab-pane active">
            <div className="tab-header">
              <h2>Task Results</h2>
              {selectedTask && (
                <p className="tab-description">
                  {selectedTask.title} • {selectedTask.status}
                </p>
              )}
            </div>
            <div className="tab-body">
              <TaskResultPanel task={selectedTask || null} />
            </div>
          </div>
        )}
      </div>

      {/* Mini Preview Bar */}
      <div className="preview-bar">
        <div className="preview-item">
          <span className="preview-label">Selected Task:</span>
          <span className="preview-value">
            {selectedTask ? selectedTask.title : 'None'}
          </span>
        </div>
        <div className="preview-item">
          <span className="preview-label">Status:</span>
          <span className={`preview-status ${selectedTask?.status || 'pending'}`}>
            {selectedTask?.status || 'N/A'}
          </span>
        </div>
        <div className="preview-item">
          <span className="preview-label">Agents:</span>
          <span className="preview-value">{selectedTask?.agent_count || 0}</span>
        </div>
        <div className="preview-item">
          <span className="preview-label">Tools:</span>
          <span className="preview-value">{selectedTask?.tool_count || 0}</span>
        </div>
        <div className="preview-item">
          <span className="preview-label">Success:</span>
          <span className="preview-value">{selectedTask?.success_rate || 0}%</span>
        </div>
      </div>
    </div>
  );
};

VisualizationLayout.displayName = 'VisualizationLayout';
