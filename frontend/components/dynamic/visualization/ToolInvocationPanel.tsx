/**
 * ToolInvocationPanel Component
 * Displays tool invocations with input/output details
 */

import React, { useState, useMemo } from 'react';

import { formatDuration, formatJSON, formatTimestamp } from '@/lib/utils/dynamic/formatting';
import { Agent } from '@/types/dynamic/execution';
import '@/styles/dynamic/visualization/ToolInvocationPanel.css';

interface ToolInvocationPanelProps {
  agent: Agent | null;
}

/**
 * ToolInvocationPanel component - displays tool invocations for selected agent
 * 
 * Props:
 * - agent: Selected agent to display tools for
 * 
 * Tool Types:
 * - Regular Tool (🔧): Executes specific operations (port scan, service detection, etc.)
 * - Agent Tool (🤖): Decomposes the current task into subtasks and spawns child agents
 *   - Each subtask becomes a child_agent at level+1
 *   - Each child_agent has its own task_description (subtask)
 *   - Each child_agent independently selects tools based on its subtask
 * 
 * Features:
 * - Lists all tool invocations for the agent
 * - Distinguishes agent_tool (🤖) from regular tools (🔧)
 * - Shows tool status, duration, and details
 * - Expandable tool details with input/output
 * - Error display for failed tools
 * - Shows count of child agents spawned by each agent_tool
 * 
 * Example Flow:
 * Level 1 Agent (task: "Scan network")
 * ├─ Tool 1: Get network info (regular)
 * ├─ Tool 2: Verify connectivity (regular)
 * └─ Tool 3: agent_tool (decompose task into subtasks)
 *    ├─ Subtask 1: "Scan host A" → Level 2 Agent A
 *    ├─ Subtask 2: "Scan host B" → Level 2 Agent B
 *    └─ Subtask 3: "Scan host C" → Level 2 Agent C
 * 
 * Performance: Memoized to prevent unnecessary re-renders
 */
export const ToolInvocationPanel: React.FC<ToolInvocationPanelProps> = React.memo(({ agent }) => {
  const [expandedToolId, setExpandedToolId] = useState<string | null>(null);

  // Calculate child agents spawned by each tool
  const childAgentsByTool = useMemo(() => {
    if (!agent) return new Map();
    const map = new Map<string, number>();
    if (agent.child_agents) {
      for (const childAgent of agent.child_agents) {
        if (childAgent.parent_agent_id) {
          const count = map.get(childAgent.parent_agent_id) || 0;
          map.set(childAgent.parent_agent_id, count + 1);
        }
      }
    }
    return map;
  }, [agent]);

  if (!agent) {
    return (
      <div className="tool-panel">
        <div className="tool-panel-empty">
          <div className="empty-icon">🔧</div>
          <div className="empty-text">Select an agent to view tool invocations</div>
        </div>
      </div>
    );
  }

  const tools = agent.tool_invocations;

  if (tools.length === 0) {
    return (
      <div className="tool-panel">
        <div className="tool-panel-header">
          <h3>{agent.name}</h3>
          <span className="tool-count">0 tools</span>
        </div>
        <div className="tool-panel-empty">
          <div className="empty-text">No tool invocations</div>
        </div>
      </div>
    );
  }

  return (
    <div className="tool-panel">
      <div className="tool-panel-header">
        <h3>{agent.name}</h3>
        <span className="tool-count">{tools.length} tools</span>
      </div>

      <div className="tool-list">
        {tools.map((tool) => {
          const childCount = childAgentsByTool.get(tool.id) || 0;
          return (
            <div key={tool.id} className={`tool-item ${tool.is_agent_tool ? 'agent-tool' : ''}`}>
              <div
                className="tool-header"
                onClick={() =>
                  setExpandedToolId(expandedToolId === tool.id ? null : tool.id)
                }
              >
                <div className="tool-header-left">
                  <button
                    className={`expand-btn ${expandedToolId === tool.id ? 'expanded' : ''}`}
                    aria-label="Expand"
                  >
                    ▶
                  </button>
                  <div className="tool-icon">
                    {tool.is_agent_tool ? '🤖' : '🔧'}
                  </div>
                  <div className="tool-info">
                    <div className="tool-name">{tool.tool_name}</div>
                    <div className="tool-description">{tool.tool_description}</div>
                    {tool.is_agent_tool && (
                      <div className="agent-tool-badge">
                        Spawns {childCount} Agent{childCount !== 1 ? 's' : ''}
                      </div>
                    )}
                  </div>
                </div>

                <div className="tool-header-right">
                  <span className={`tool-status ${tool.status}`}>{tool.status}</span>
                  <span className="tool-duration">{formatDuration(tool.duration_ms)}</span>
                </div>
              </div>

              {expandedToolId === tool.id && (
                <div className="tool-details">
                  <div className="detail-section">
                    <div className="detail-title">Parameters</div>
                    <pre className="detail-content">
                      {formatJSON(tool.parameters)}
                    </pre>
                  </div>

                  <div className="detail-section">
                    <div className="detail-title">Result</div>
                    <pre className="detail-content">
                      {formatJSON(tool.result)}
                    </pre>
                  </div>

                  {tool.error_message && (
                    <div className="detail-section error">
                      <div className="detail-title">Error</div>
                      <div className="detail-content error-text">
                        {tool.error_message}
                      </div>
                    </div>
                  )}

                  <div className="detail-section">
                    <div className="detail-title">Timing</div>
                    <div className="timing-info">
                      <div>Start: {formatTimestamp(tool.start_time)}</div>
                      <div>End: {formatTimestamp(tool.end_time)}</div>
                      <div>Duration: {formatDuration(tool.duration_ms)}</div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          );
        })}
        
        {/* Footer */}
        <div className="tool-panel-footer">
          <div className="footer-text">End of tool list</div>
        </div>
      </div>
    </div>
  );
});

ToolInvocationPanel.displayName = 'ToolInvocationPanel';
