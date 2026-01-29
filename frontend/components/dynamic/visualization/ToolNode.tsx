/**
 * ToolNode Component
 * Displays a single tool invocation in the execution tree
 */

import React, { useMemo } from 'react';

import { formatDuration, formatTimestamp } from '@/lib/utils/dynamic/formatting';
import { useExecutionStore } from '@/stores/dynamic/executionStore';
import { ToolInvocation } from '@/types/dynamic/execution';
import '@/styles/dynamic/visualization/ToolNode.css';

interface ToolNodeProps {
  tool: ToolInvocation;
  isAgentTool?: boolean;
  childAgentCount?: number;
  isExpanded?: boolean;
  onToggleExpand?: (toolId: string) => void;
  childAgents?: any[]; // Child agents spawned by this tool
  renderAgentTree?: (agent: any, depth: number) => React.ReactNode;
  depth?: number;
}

/**
 * Get status color and icon
 */
function getStatusInfo(status: string): { color: string; icon: string } {
  switch (status) {
    case 'completed':
      return { color: '#10b981', icon: '✓' };
    case 'running':
      return { color: '#3b82f6', icon: '⟳' };
    case 'failed':
      return { color: '#ef4444', icon: '✕' };
    case 'pending':
      return { color: '#9ca3af', icon: '○' };
    default:
      return { color: '#6b7280', icon: '?' };
  }
}

/**
 * ToolNode component - displays individual tool in execution tree
 */
export const ToolNode: React.FC<ToolNodeProps> = ({ 
  tool, 
  isAgentTool = false, 
  childAgentCount = 0,
  isExpanded = false,
  onToggleExpand,
  // childAgents and renderAgentTree removed as they are handled by parent
}) => {
  const selectTool = useExecutionStore((state) => state.selectTool);
  const selectedToolId = useExecutionStore((state) => state.selectedToolId);
  const isSelected = selectedToolId === tool.id;

  const statusInfo = useMemo(() => getStatusInfo(tool.status), [tool.status]);

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    selectTool(tool.id);
  };

  const handleExpandClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (onToggleExpand) {
      onToggleExpand(tool.id);
    }
  };

  const isRunning = tool.status === 'running';
  // Show expand button for all agent_tool, even if subtasks not loaded yet
  const canExpand = isAgentTool;
  const hasChildAgents = isAgentTool && childAgentCount > 0;

  return (
    <div 
      className={`tool-node ${isAgentTool ? 'agent-tool' : 'regular-tool'} ${isRunning ? 'running' : ''} ${isSelected ? 'selected' : ''}`}
      onClick={handleClick}
    >
      <div 
        className="tool-node-content"
        style={{ cursor: canExpand ? 'pointer' : 'default' }}
      >
        {/* Expand button for agent_tool (always show for agent_tool) */}
        {canExpand && (
          <div 
            className={`tool-expand-btn ${isExpanded ? 'expanded' : ''}`}
            onClick={handleExpandClick}
            title="Load subtasks"
          >
            ▶
          </div>
        )}
        {!canExpand && <div className="tool-expand-placeholder" />}

        {/* Status indicator */}
        <div
          className="tool-status-indicator"
          style={{ backgroundColor: statusInfo.color }}
          title={tool.status}
        >
          {statusInfo.icon}
        </div>

        {/* Tool icon */}
        <div className="tool-node-icon">
          {isAgentTool ? '🤖' : '🔧'}
        </div>

        {/* Tool info */}
        <div className="tool-node-info">
          <div className="tool-node-name">{tool.tool_name}</div>
          <div className="tool-node-meta">
            <span className="tool-status-badge">{tool.status}</span>
            <span className="tool-time" style={{ marginRight: '8px', color: '#6b7280', fontSize: '11px' }}>
              {formatTimestamp(tool.start_time)}
            </span>
            <span className="tool-duration">{formatDuration(tool.duration_ms)}</span>
            {isAgentTool && childAgentCount > 0 && (
              <span className="spawned-agents-badge">
                Spawns {childAgentCount} Agent{childAgentCount !== 1 ? 's' : ''}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

ToolNode.displayName = 'ToolNode';
