/**
 * AgentNode Component
 * Displays a single agent node with status, name, and metadata
 */

import React, { useMemo } from 'react';

import { formatDuration, formatTimestamp } from '@/lib/utils/dynamic/formatting';
import { getLevelColor, getLevelIndentation, getLevelBadgeText } from '@/lib/utils/dynamic/levelUtils';
import { Agent, ExecutionStatus } from '@/types/dynamic/execution';
import '@/styles/dynamic/visualization/AgentNode.css';

interface AgentNodeProps {
  agent: Agent;
  isSelected?: boolean;
  isExpanded?: boolean;
  onToggleExpand?: (agentId: string) => void;
  onJumpToParent?: (agentId: string) => void;
  indent?: boolean;
}

/**
 * Get status color and icon
 */
function getStatusInfo(status: ExecutionStatus): { color: string; icon: string; label: string } {
  switch (status) {
    case 'completed':
      return { color: '#10b981', icon: '✓', label: 'Completed' };
    case 'running':
      return { color: '#3b82f6', icon: '⟳', label: 'Running' };
    case 'failed':
      return { color: '#ef4444', icon: '✕', label: 'Failed' };
    case 'pending':
      return { color: '#9ca3af', icon: '○', label: 'Pending' };
  }
}

/**
 * AgentNode component - displays individual agent information
 * 
 * Props:
 * - agent: Agent data to display
 * - isSelected: Whether this agent is currently selected
 * - isExpanded: Whether child agents are expanded
 * - onToggleExpand: Callback when expand/collapse button is clicked
 * - onJumpToParent: Callback when jump to parent button is clicked
 * 
 * Features:
 * - Level-based indentation and color coding
 * - Level badge display
 * - Expand/collapse buttons for child agents
 * - Jump to parent navigation
 * - Tool and sub-agent counts
 * - Status indicator with color and icon
 * - Hover tooltip with task description
 */
export const AgentNode: React.FC<AgentNodeProps> = React.memo(({ 
  agent, 
  isSelected = false,
  isExpanded = false,
  onToggleExpand,
  onJumpToParent,
  indent = true,
}) => {
  const statusInfo = useMemo(() => getStatusInfo(agent.status), [agent.status]);

  const toolCount = agent.tool_invocations.length;
  const subAgentCount = agent.sub_agents.length;
  const childAgentCount = agent.child_agents?.length || 0;
  const totalChildren = subAgentCount + childAgentCount;
  const levelColor = useMemo(() => getLevelColor(agent.level), [agent.level]);
  const levelIndent = useMemo(() => indent ? getLevelIndentation(agent.level) : 0, [agent.level, indent]);
  const levelBadge = useMemo(() => getLevelBadgeText(agent.level), [agent.level]);

  const isRunning = agent.status === 'running';
  const isRoot = agent.level === 1;

  return (
    <div 
      className={`agent-node ${isSelected ? 'selected' : ''} ${isExpanded ? 'expanded' : ''} ${isRunning ? 'running' : ''} ${isRoot ? 'root-node' : ''}`}
      style={{ marginLeft: `${levelIndent}px` }}
    >
      <div className="agent-node-header">
        {/* Status indicator */}
        <div
          className="status-indicator"
          style={{ backgroundColor: statusInfo.color }}
          title={statusInfo.label}
        >
          <span className="status-icon">{statusInfo.icon}</span>
        </div>

        {/* Agent name and level */}
        <div className="agent-info">
          <div className="agent-name" title={agent.task_description || agent.name}>
            {agent.name}
          </div>
          <div className="agent-meta">
            <span 
              className="agent-level-badge"
              style={{ backgroundColor: levelColor }}
            >
              {levelBadge}
            </span>
            {toolCount > 0 && <span className="tool-count">{toolCount} tools</span>}
            {subAgentCount > 0 && <span className="sub-agent-count">{subAgentCount} sub-agents</span>}
            {childAgentCount > 0 && (
              <span className="child-agent-count">
                🤖 {childAgentCount} spawned agent{childAgentCount !== 1 ? 's' : ''}
              </span>
            )}
          </div>
        </div>

        {/* Navigation buttons */}
        <div className="agent-nav-buttons">
          {totalChildren > 0 && onToggleExpand && (
            <button
              className={`nav-btn expand-btn ${isExpanded ? 'expanded' : ''}`}
              onClick={() => onToggleExpand(agent.id)}
              title={isExpanded ? 'Collapse' : 'Expand'}
            >
              ▼
            </button>
          )}
          {agent.parent_agent_id && onJumpToParent && (
            <button
              className="nav-btn parent-btn"
              onClick={() => onJumpToParent(agent.parent_agent_id!)}
              title="Jump to parent"
            >
              ↑
            </button>
          )}
        </div>

        {/* Time & Duration */}
        <div className="agent-time-info" style={{ display: 'flex', gap: '12px', marginLeft: 'auto', fontSize: '12px', color: '#6b7280' }}>
          <span className="agent-start-time" title={`Started at ${formatTimestamp(agent.start_time)}`}>
            {formatTimestamp(agent.start_time)}
          </span>
          <span className="agent-duration" title="Duration">
            ⏱ {formatDuration(agent.duration_ms)}
          </span>
        </div>
      </div>

      {/* Task description tooltip */}
      <div className="agent-tooltip">
        <div className="tooltip-title">Task</div>
        <div className="tooltip-text">{agent.task_description}</div>
        <div className="tooltip-title" style={{ marginTop: '12px' }}>
          Execution Time
        </div>
        <div className="tooltip-text">
          {formatTimestamp(agent.start_time)} - {formatTimestamp(agent.end_time)}
        </div>
        {agent.success_rate !== undefined && (
          <>
            <div className="tooltip-title" style={{ marginTop: '12px' }}>
              Success Rate
            </div>
            <div className="tooltip-text">{agent.success_rate}%</div>
          </>
        )}
        {agent.error_message && (
          <>
            <div className="tooltip-title" style={{ marginTop: '12px', color: '#ef4444', borderColor: 'rgba(239, 68, 68, 0.2)' }}>
              Error
            </div>
            <div className="tooltip-text" style={{ color: '#fca5a5' }}>
              {agent.error_message}
            </div>
          </>
        )}
      </div>
    </div>
  );
});

AgentNode.displayName = 'AgentNode';
