/**
 * AgentDetailPanel Component
 * Displays detailed information about a selected agent
 */

import React, { useState } from 'react';

import { formatDuration, formatTimestamp } from '@/lib/utils/dynamic/formatting';
import { Agent } from '@/types/dynamic/execution';
import '@/styles/dynamic/visualization/AgentDetailPanel.css';

interface AgentDetailPanelProps {
  agent: Agent | null;
}

/**
 * AgentDetailPanel component - shows detailed agent information
 */
export const AgentDetailPanel: React.FC<AgentDetailPanelProps> = ({ agent }) => {
  const [expandedToolIds, setExpandedToolIds] = useState<Set<string>>(new Set());

  const toggleToolExpanded = (toolId: string) => {
    const newExpanded = new Set(expandedToolIds);
    if (newExpanded.has(toolId)) {
      newExpanded.delete(toolId);
    } else {
      newExpanded.add(toolId);
    }
    setExpandedToolIds(newExpanded);
  };

  if (!agent) {
    return (
      <div className="agent-detail-panel empty">
        <div className="empty-state">
          <div className="empty-icon">👆</div>
          <p>Select an agent to view details</p>
        </div>
      </div>
    );
  }

  const toolCount = agent.tool_invocations?.length || 0;
  const childAgentCount = agent.child_agents?.length || 0;

  return (
    <div className="agent-detail-panel">
      {/* Header */}
      <div className="detail-panel-header">
        <div className="agent-title">
          <h3>{agent.name}</h3>
          <span className={`status-badge ${agent.status}`}>{agent.status}</span>
        </div>
        <div className="agent-meta-info">
          <div className="meta-row">
            <span className="meta-label">Duration:</span>
            <span className="meta-value">{formatDuration(agent.duration_ms)}</span>
          </div>
          <div className="meta-row">
            <span className="meta-label">Start Time:</span>
            <span className="meta-value">{formatTimestamp(agent.start_time)}</span>
          </div>
          <div className="meta-row">
            <span className="meta-label">End Time:</span>
            <span className="meta-value">{formatTimestamp(agent.end_time)}</span>
          </div>
          {agent.success_rate !== undefined && (
            <div className="meta-row">
              <span className="meta-label">Success Rate:</span>
              <span className="meta-value">{agent.success_rate}%</span>
            </div>
          )}
        </div>
      </div>

      {/* Task Description */}
      <div className="detail-section">
        <h4 className="section-title">📝 Task Description</h4>
        <div className="section-content">
          <p className="task-description">{agent.task_description}</p>
        </div>
      </div>

      {/* Agent Output */}
      {agent.output && Object.keys(agent.output).length > 0 && (
        <div className="detail-section">
          <h4 className="section-title">📤 Agent Output</h4>
          <div className="section-content">
            <div className="tool-json">
              <pre>{JSON.stringify(agent.output, null, 2)}</pre>
            </div>
          </div>
        </div>
      )}

      {/* Tools */}
      {toolCount > 0 && (
        <div className="detail-section">
          <h4 className="section-title">🔧 Tools ({toolCount})</h4>
          <div className="tools-list">
            {agent.tool_invocations.map((tool) => {
              const isExpanded = expandedToolIds.has(tool.id);

              return (
                <div key={tool.id} className={`tool-item ${tool.status}`}>
                  <div
                    className="tool-header clickable"
                    onClick={() => toggleToolExpanded(tool.id)}
                  >
                    <div className="tool-name">
                      <span className="tool-icon">{tool.is_agent_tool ? '🤖' : '🔧'}</span>
                      <span className="tool-title">{tool.tool_name}</span>
                      <span className="expand-indicator">
                        {isExpanded ? '▼' : '▶'}
                      </span>
                    </div>
                    <div className="tool-meta">
                      <span className={`tool-status ${tool.status}`}>{tool.status}</span>
                      <span className="tool-duration">{formatDuration(tool.duration_ms)}</span>
                    </div>
                  </div>

                  <div className="tool-description">
                    {tool.tool_description}
                  </div>

                  {/* Expanded Details */}
                  {isExpanded && (
                    <div className="tool-details">
                      {/* Timing Information */}
                      <div className="tool-timing">
                        <div className="timing-row">
                          <span className="timing-label">⏰ Start:</span>
                          <span className="timing-value">{formatTimestamp(tool.start_time)}</span>
                        </div>
                        <div className="timing-row">
                          <span className="timing-label">⏱️ End:</span>
                          <span className="timing-value">{formatTimestamp(tool.end_time)}</span>
                        </div>
                        <div className="timing-row">
                          <span className="timing-label">⏳ Duration:</span>
                          <span className="timing-value">{formatDuration(tool.duration_ms)}</span>
                        </div>
                      </div>

                      {/* Input Parameters */}
                      {tool.parameters && Object.keys(tool.parameters).length > 0 && (
                        <div className="tool-section">
                          <h5 className="tool-section-title">📥 Input Parameters</h5>
                          <div className="tool-json">
                            <pre>{JSON.stringify(tool.parameters, null, 2)}</pre>
                          </div>
                        </div>
                      )}

                      {/* Output Result */}
                      {tool.result && Object.keys(tool.result).length > 0 && (
                        <div className="tool-section">
                          <h5 className="tool-section-title">
                            {tool.status === 'completed' ? '✅ Output Result' :
                             tool.status === 'failed' ? '❌ Error Result' :
                             '⏳ Partial Result'}
                          </h5>
                          <div className="tool-json">
                            <pre>{JSON.stringify(tool.result, null, 2)}</pre>
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {tool.is_agent_tool && (
                    <div className="agent-tool-badge">
                      🤖 Spawns child agent(s)
                    </div>
                  )}

                  {tool.error_message && (
                    <div className="tool-error">
                      ❌ {tool.error_message}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Child Agents */}
      {childAgentCount > 0 && (
        <div className="detail-section">
          <h4 className="section-title">🤖 Spawned Agents ({childAgentCount})</h4>
          <div className="child-agents-list">
            {agent.child_agents?.map((child) => (
              <div key={child.id} className="child-agent-item">
                <span className="child-agent-name">{child.name}</span>
                <span className={`child-agent-status ${child.status}`}>{child.status}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Error Message */}
      {agent.error_message && (
        <div className="detail-section error-section">
          <h4 className="section-title">⚠️ Error</h4>
          <div className="error-message">
            {agent.error_message}
          </div>
        </div>
      )}
    </div>
  );
};

AgentDetailPanel.displayName = 'AgentDetailPanel';
