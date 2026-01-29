/**
 * TreeView Component
 * Displays agent execution hierarchy with integrated timeline
 */

import React, { useCallback } from 'react';

import { useTranslation } from '@/lib/i18n';
import { useExecutionStore } from '@/stores/dynamic/executionStore';
import { Agent, ExecutionTree } from '@/types/dynamic/execution';

import { AgentNode } from './AgentNode';
import { ToolNode } from './ToolNode';

import '@/styles/dynamic/visualization/TreeView.css';

interface TreeViewProps {
  execution: ExecutionTree;
  onLoadSubtasks?: (agentId: string, taskId: string, stepId: string) => Promise<void>;
}

/**
 * TreeView component - renders hierarchical agent tree
 */
export const TreeView: React.FC<TreeViewProps> = ({ execution, onLoadSubtasks }) => {
  const { t } = useTranslation()
  const selectedAgentId = useExecutionStore((state) => state.selectedAgentId);
  const expandedNodeIds = useExecutionStore((state) => state.expandedNodeIds);
  const expandedToolIds = useExecutionStore((state) => state.expandedToolIds);
  const selectAgent = useExecutionStore((state) => state.selectAgent);
  const toggleNodeExpanded = useExecutionStore((state) => state.toggleNodeExpanded);
  const setExpandedNodes = useExecutionStore((state) => state.setExpandedNodes);
  const toggleToolExpanded = useExecutionStore((state) => state.toggleToolExpanded);
  const setExpandedTools = useExecutionStore((state) => state.setExpandedTools);

  // Initialize expansion state only on first load (when execution ID changes)
  // Preserve expansion state during polling updates
  const executionIdRef = React.useRef<string | null>(null);
  const hasInitialized = React.useRef(false);

  React.useEffect(() => {
    if (execution?.root_agent?.id) {
      // Only reset expansion state when execution ID actually changes (new task)
      // Don't reset during polling updates (same execution ID)
      const isNewExecution = executionIdRef.current !== execution.id;

      if (isNewExecution) {
        executionIdRef.current = execution.id;
        hasInitialized.current = false;
      }

      // Initialize only once per execution
      if (!hasInitialized.current) {
        setExpandedNodes(new Set([execution.root_agent.id]));
        setExpandedTools(new Set());
        hasInitialized.current = true;
      }
    }
  }, [execution?.id, execution?.root_agent?.id, setExpandedNodes, setExpandedTools]); // Dependency on execution ID to avoid loops if object ref changes

  const handleNodeClick = useCallback(
    (agentId: string) => {
      selectAgent(agentId);
    },
    [selectAgent]
  );

  const handleToggleExpand = useCallback(
    (agentId: string, e: React.MouseEvent) => {
      e.stopPropagation();
      toggleNodeExpanded(agentId);
    },
    [toggleNodeExpanded]
  );

  const isNodeExpanded = useCallback(
    (agentId: string) => expandedNodeIds.has(agentId),
    [expandedNodeIds]
  );

  const handleToggleToolExpand = useCallback(
    async (toolId: string, agent: Agent, isAgentTool: boolean) => {
      console.log(`[TreeView] handleToggleToolExpand called:`, {
        toolId,
        agentId: agent.id,
        taskId: agent.task_id,
        isAgentTool,
        hasOnLoadSubtasks: !!onLoadSubtasks,
      });

      // Toggle expansion state using store action
      const wasExpanded = expandedToolIds.has(toolId);
      toggleToolExpanded(toolId);

      if (!wasExpanded && isAgentTool && agent.task_id && onLoadSubtasks) {
        console.log(`[TreeView] 🚀 Triggering subtask load for step ${toolId}, task ${agent.task_id}`);
        onLoadSubtasks(agent.id, agent.task_id, toolId).catch(error => {
          console.error('[TreeView] Failed to load subtasks:', error);
        });
      }
    },
    [expandedToolIds, toggleToolExpanded, onLoadSubtasks]
  );

  const isToolExpanded = useCallback(
    (toolId: string) => expandedToolIds.has(toolId),
    [expandedToolIds]
  );

  const renderAgentTree = useCallback(
    (agent: Agent, depth: number = 0): React.ReactNode => {
      const isExpanded = isNodeExpanded(agent.id);
      const isSelected = selectedAgentId === agent.id;

      const hasTools = agent.tool_invocations && agent.tool_invocations.length > 0;
      const isRunningOrPending = agent.status === 'running' || agent.status === 'pending';
      // Show expand button if agent has tools OR is currently running/pending (tools may be executing)
      const hasContent = hasTools || isRunningOrPending;

      // Debug: Log child agent info
      if (depth > 0) {
        console.log(`[TreeView] Rendering agent at depth ${depth}:`, {
          id: agent.id,
          level: agent.level,
          name: agent.name,
          status: agent.status,
          hasTools,
          toolCount: agent.tool_invocations?.length || 0,
          isRunningOrPending,
          hasContent,
        });
      }

      // Sort tools by start time
      const sortedTools = [...(agent.tool_invocations || [])].sort((a, b) => a.start_time - b.start_time);

      return (
        <React.Fragment key={agent.id}>
          {/* Agent Node */}
          <div className="tree-node-wrapper" style={{ marginLeft: `${depth * 24}px` }}>
            <div
              className={`tree-node ${isSelected ? 'selected' : ''}`}
              onClick={() => handleNodeClick(agent.id)}
            >
              {hasContent && (
                <button
                  className={`expand-button ${isExpanded ? 'expanded' : ''}`}
                  onClick={(e) => handleToggleExpand(agent.id, e)}
                  aria-label={isExpanded ? 'Collapse' : 'Expand'}
                >
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                    <path
                      d="M6 4L10 8L6 12"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </button>
              )}
              {!hasContent && <div className="expand-button-placeholder" />}

              <AgentNode
                agent={agent}
                isSelected={isSelected}
                indent={false}
              />
            </div>
          </div>

          {/* Children (Tools) */}
          {isExpanded && hasContent && (
            <div className="tree-children">
              {hasTools ? sortedTools.map((tool) => {
                const toolExpanded = isToolExpanded(tool.id);
                const isAgentTool = tool.is_agent_tool || false;

                // Check if we have loaded subtasks for this specific tool
                const loadedSubtasks = tool.loaded_subtasks || [];
                const hasLoadedSubtasks = loadedSubtasks.length > 0;

                if (isAgentTool) {
                  console.log(`[TreeView] Rendering agent_tool ${tool.id}:`, {
                    agentId: agent.id,
                    taskId: agent.task_id,
                    hasLoadedSubtasks,
                    loadedSubtasksCount: loadedSubtasks.length,
                    toolExpanded,
                  });
                }

                return (
                  <React.Fragment key={tool.id}>
                    {/* Tool Node */}
                    <div style={{ marginLeft: `${(depth + 1) * 24}px` }}>
                      <ToolNode
                        tool={tool}
                        isAgentTool={isAgentTool}
                        childAgentCount={isAgentTool && hasLoadedSubtasks ? loadedSubtasks.length : 0}
                        isExpanded={toolExpanded}
                        onToggleExpand={(toolId) => handleToggleToolExpand(toolId, agent, isAgentTool)}
                      />
                    </div>

                    {/* Child Agents (dynamically loaded subtasks for this tool) */}
                    {isAgentTool && toolExpanded && hasLoadedSubtasks && (
                      <div className="child-agents-wrapper">
                        {/* Render dynamically loaded subtasks */}
                        {loadedSubtasks
                          .sort((a, b) => a.start_time - b.start_time)
                          .map(child => {
                            // Child agents should be indented relative to the tool that spawned them
                            // Tool is at depth + 1, so child agent should be at depth + 2
                            const childDepth = depth + 2;
                            return renderAgentTree(child, childDepth);
                          })
                        }
                      </div>
                    )}
                  </React.Fragment>
                );
              }) : (
                <div style={{ marginLeft: `${(depth + 1) * 24}px`, padding: '8px', color: '#9ca3af', fontSize: '12px' }}>
                  {isRunningOrPending ? t('tree.toolsExecuting', { defaultValue: '工具正在执行中...' }) : t('tree.noToolRecords', { defaultValue: '暂无工具执行记录' })}
                </div>
              )}
              {/* Note: This file doesn't have useTranslation hook, keeping Chinese for now */}
            </div>
          )}
        </React.Fragment>
      );
    },
    [isNodeExpanded, selectedAgentId, handleNodeClick, handleToggleExpand, isToolExpanded, handleToggleToolExpand]
  );

  return (
    <div className="tree-view">
      <div className="tree-container">
        <div className="tree-content">
          {renderAgentTree(execution.root_agent)}
        </div>

        <div className="tree-footer">
          <div className="footer-content">
            End of execution tree
          </div>
        </div>
      </div>
    </div>
  );
};

TreeView.displayName = 'TreeView';
