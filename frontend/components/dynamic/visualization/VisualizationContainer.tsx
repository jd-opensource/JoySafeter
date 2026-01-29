/**
 * VisualizationContainer Component
 * Main container for agent execution visualization
 * Combines tree view, timeline view, and tool invocation panel
 */

import React, { useState, useEffect, useRef } from 'react';

import { useExecutionStore } from '@/stores/dynamic/executionStore';
import { ExecutionTree, Agent, ToolInvocation } from '@/types/dynamic/execution';

import { ExecutionItemDetailPanel } from './ExecutionItemDetailPanel';
import { TreeView } from './TreeView';
import '@/styles/dynamic/visualization/VisualizationContainer.css';

interface VisualizationContainerProps {
  execution: ExecutionTree;
  onLoadSubtasks?: (agentId: string, taskId: string, stepId: string) => Promise<void>;
}

const STORAGE_KEY = 'visualization-detail-width';
const DEFAULT_WIDTH = 525;
const MIN_WIDTH = 300;
const MAX_WIDTH = 1200;

/**
 * VisualizationContainer component - main visualization layout
 */
export const VisualizationContainer: React.FC<VisualizationContainerProps> = ({
  execution,
  onLoadSubtasks,
}) => {
  const selectedAgentId = useExecutionStore((state) => state.selectedAgentId);
  const selectedToolId = useExecutionStore((state) => state.selectedToolId);
  const selectedItemType = useExecutionStore((state) => state.selectedItemType);

  // Detail panel width state with localStorage persistence
  const [detailWidth, setDetailWidth] = useState<number>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        const parsed = parseInt(saved, 10);
        if (!isNaN(parsed) && parsed >= MIN_WIDTH && parsed <= MAX_WIDTH) {
          return parsed;
        }
      }
    }
    return DEFAULT_WIDTH;
  });

  const [isResizing, setIsResizing] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Save width to localStorage when it changes
  useEffect(() => {
    if (typeof window !== 'undefined') {
      localStorage.setItem(STORAGE_KEY, detailWidth.toString());
    }
  }, [detailWidth]);

  // Handle mouse move during resize
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isResizing || !containerRef.current) return;

      const containerRect = containerRef.current.getBoundingClientRect();
      const newWidth = containerRect.right - e.clientX;

      // Clamp width between min and max
      const clampedWidth = Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, newWidth));
      setDetailWidth(clampedWidth);
    };

    const handleMouseUp = () => {
      setIsResizing(false);
    };

    if (isResizing) {
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);

      return () => {
        document.removeEventListener('mousemove', handleMouseMove);
        document.removeEventListener('mouseup', handleMouseUp);
      };
    }
  }, [isResizing]);

  const handleResizeStart = (e: React.MouseEvent) => {
    e.preventDefault();
    setIsResizing(true);
  };

  // Helper function to find agent by ID in the current execution
  const findAgentById = (agent: Agent, id: string): Agent | null => {
    if (agent.id === id) return agent;

    // Search in sub_agents
    if (agent.sub_agents && agent.sub_agents.length > 0) {
      for (const subAgent of agent.sub_agents) {
        const found = findAgentById(subAgent, id);
        if (found) return found;
      }
    }

    // Search in child_agents (spawned by agent_tool)
    if (agent.child_agents && agent.child_agents.length > 0) {
      for (const childAgent of agent.child_agents) {
        const found = findAgentById(childAgent, id);
        if (found) return found;
      }
    }

    // Search in loaded_subtasks (dynamically loaded child agents)
    if (agent.loaded_subtasks && agent.loaded_subtasks.length > 0) {
      for (const subtask of agent.loaded_subtasks) {
        const found = findAgentById(subtask, id);
        if (found) return found;
      }
    }

    // Search in tool.loaded_subtasks (subtask's loaded_subtasks are stored on tool)
    if (agent.tool_invocations) {
      for (const tool of agent.tool_invocations) {
        if (tool.loaded_subtasks && tool.loaded_subtasks.length > 0) {
          for (const subtask of tool.loaded_subtasks) {
            const found = findAgentById(subtask, id);
            if (found) return found;
          }
        }
      }
    }

    return null;
  };

  // Helper function to find tool by ID in the current execution
  const findToolById = (agent: Agent, id: string): ToolInvocation | null => {
    // Search in this agent's tools
    if (agent.tool_invocations) {
      const tool = agent.tool_invocations.find(t => t.id === id);
      if (tool) return tool;
    }

    // Search in sub_agents
    if (agent.sub_agents && agent.sub_agents.length > 0) {
      for (const subAgent of agent.sub_agents) {
        const found = findToolById(subAgent, id);
        if (found) return found;
      }
    }

    // Search in child_agents
    if (agent.child_agents && agent.child_agents.length > 0) {
      for (const childAgent of agent.child_agents) {
        const found = findToolById(childAgent, id);
        if (found) return found;
      }
    }

    // Search in loaded_subtasks (dynamically loaded child agents)
    if (agent.loaded_subtasks && agent.loaded_subtasks.length > 0) {
      for (const subtask of agent.loaded_subtasks) {
        const found = findToolById(subtask, id);
        if (found) return found;
      }
    }

    // Search in tool.loaded_subtasks (subtask's loaded_subtasks are stored on tool)
    if (agent.tool_invocations) {
      for (const tool of agent.tool_invocations) {
        if (tool.loaded_subtasks && tool.loaded_subtasks.length > 0) {
          for (const subtask of tool.loaded_subtasks) {
            const found = findToolById(subtask, id);
            if (found) return found;
          }
        }
      }
    }

    return null;
  };

  // Get the selected item (agent or tool)
  const selectedAgent = selectedAgentId ? findAgentById(execution.root_agent, selectedAgentId) : null;
  const selectedTool = selectedToolId ? findToolById(execution.root_agent, selectedToolId) : null;
  const selectedItem = selectedItemType === 'agent' ? selectedAgent : selectedTool;

  return (
    <div className="visualization-container" ref={containerRef}>
      {/* Main content area - Tree and Detail Panel */}
      <div className="visualization-content">
        {/* Tree Panel */}
        <div className="visualization-main">
          <TreeView
            execution={execution}
            onLoadSubtasks={onLoadSubtasks}
          />
        </div>

        {/* Resizer Handle */}
        <div
          className={`visualization-resizer ${isResizing ? 'active' : ''}`}
          onMouseDown={handleResizeStart}
          title="Drag to resize panel"
        />

        {/* Detail Panel */}
        <div
          className="visualization-detail"
          style={{ flex: `0 0 ${detailWidth}px` }}
        >
          <ExecutionItemDetailPanel item={selectedItem} itemType={selectedItemType} />
        </div>
      </div>
    </div>
  );
};

VisualizationContainer.displayName = 'VisualizationContainer';
