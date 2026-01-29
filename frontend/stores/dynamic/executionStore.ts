/**
 * Zustand store for execution visualization state
 * Manages execution data, selected agents, and view state
 */

import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';

import {
  ExecutionTree,
  Agent,
  VisualizationView,
  ExecutionTimeline,
  TimelineAgent,
} from '@/types/dynamic/execution';

/**
 * Execution store state
 */
interface ExecutionState {
  // Data
  execution: ExecutionTree | null;
  timeline: ExecutionTimeline | null;

  // UI State
  selectedAgentId: string | null;
  selectedToolId: string | null;
  selectedItemType: 'agent' | 'tool' | null;
  expandedNodeIds: Set<string>;
  expandedToolIds: Set<string>; // Track expanded tool nodes (for agent_tool child agents)
  currentView: VisualizationView;

  // Actions
  setExecution: (execution: ExecutionTree) => void;
  updateExecution: (execution: ExecutionTree) => void; // Update without resetting UI state
  clearExecution: () => void;
  selectAgent: (agentId: string | null) => void;
  selectTool: (toolId: string | null) => void;
  toggleNodeExpanded: (nodeId: string) => void;
  setExpandedNodes: (nodeIds: Set<string>) => void;
  toggleToolExpanded: (toolId: string) => void;
  setExpandedTools: (toolIds: Set<string>) => void;
  switchView: (view: VisualizationView) => void;
  generateTimeline: () => void;
  getSelectedAgent: () => Agent | null;
  getAgentById: (id: string) => Agent | null;
}

/**
 * Helper function to find agent by ID in tree
 */
function findAgentById(agent: Agent, id: string): Agent | null {
  if (agent.id === id) return agent;

  // Search in sub_agents
  for (const subAgent of agent.sub_agents) {
    const found = findAgentById(subAgent, id);
    if (found) return found;
  }

  // Search in child_agents (spawned by agent_tool)
  if (agent.child_agents) {
    for (const childAgent of agent.child_agents) {
      const found = findAgentById(childAgent, id);
      if (found) return found;
    }
  }

  return null;
}

/**
 * Helper function to generate timeline from execution tree
 */
function generateTimeline(execution: ExecutionTree): ExecutionTimeline {
  const agents: TimelineAgent[] = [];
  const agentsByRow: Map<number, TimelineAgent[]> = new Map();

  // Flatten agent tree and assign to rows
  const queue = [execution.root_agent];
  const minTime = execution.execution_start_time;

  while (queue.length > 0) {
    const agent = queue.shift()!;

    // Find row for concurrent agents
    let row = 0;
    let placed = false;

    for (let r = 0; r <= row; r++) {
      const rowAgents = agentsByRow.get(r) || [];
      const overlaps = rowAgents.some(
        (ta) =>
          !(agent.end_time <= ta.agent.start_time ||
            agent.start_time >= ta.agent.end_time)
      );

      if (!overlaps) {
        row = r;
        placed = true;
        break;
      }
    }

    if (!placed) {
      row = Math.max(...Array.from(agentsByRow.keys()), -1) + 1;
    }

    const timelineAgent: TimelineAgent = {
      agent,
      row,
      offset_ms: agent.start_time - minTime,
      width_ms: agent.duration_ms,
    };

    if (!agentsByRow.has(row)) {
      agentsByRow.set(row, []);
    }
    agentsByRow.get(row)!.push(timelineAgent);
    agents.push(timelineAgent);

    queue.push(...agent.sub_agents);
  }

  return {
    agents,
    min_time: minTime,
    max_time: execution.execution_end_time,
    total_duration_ms: execution.total_duration_ms,
  };
}

/**
 * Create execution store
 */
export const useExecutionStore = create<ExecutionState>()(
  devtools(
    persist(
      (set, get) => ({
        // Initial state
        execution: null,
        timeline: null,
        selectedAgentId: null,
        selectedToolId: null,
        selectedItemType: null,
        expandedNodeIds: new Set(),
        expandedToolIds: new Set(),
        currentView: 'tree',

        // Actions
        setExecution: (execution: ExecutionTree) => {
          set(() => ({
            execution,
            selectedAgentId: execution.root_agent.id,
            selectedToolId: null,
            selectedItemType: 'agent',
            expandedNodeIds: new Set([execution.root_agent.id]),
            expandedToolIds: new Set(), // Reset tool expansion state
            timeline: generateTimeline(execution),
          }));
        },

        updateExecution: (execution: ExecutionTree) => {
          // Update execution data without resetting UI state (for polling)
          const state = get();
          
          set(() => ({
            execution,
            timeline: generateTimeline(execution),
            // Keep existing UI state
            selectedAgentId: state.selectedAgentId,
            selectedToolId: state.selectedToolId,
            selectedItemType: state.selectedItemType,
            expandedNodeIds: state.expandedNodeIds,
            expandedToolIds: state.expandedToolIds, // Keep tool expansion state
          }));
        },

        clearExecution: () => {
          set({
            execution: null,
            timeline: null,
            selectedAgentId: null,
            selectedToolId: null,
            selectedItemType: null,
            expandedNodeIds: new Set(),
            expandedToolIds: new Set(),
          });
        },

        selectAgent: (agentId: string | null) => {
          set({ 
            selectedAgentId: agentId,
            selectedToolId: null,
            selectedItemType: agentId ? 'agent' : null
          });
        },

        selectTool: (toolId: string | null) => {
          set({ 
            selectedToolId: toolId,
            selectedAgentId: null,
            selectedItemType: toolId ? 'tool' : null
          });
        },

        toggleNodeExpanded: (nodeId: string) => {
          set((state) => {
            const newExpanded = new Set(state.expandedNodeIds);
            if (newExpanded.has(nodeId)) {
              newExpanded.delete(nodeId);
            } else {
              newExpanded.add(nodeId);
            }
            return { expandedNodeIds: newExpanded };
          });
        },

        setExpandedNodes: (nodeIds: Set<string>) => {
          set({ expandedNodeIds: nodeIds });
        },

        toggleToolExpanded: (toolId: string) => {
          set((state) => {
            const newExpanded = new Set(state.expandedToolIds);
            const wasExpanded = newExpanded.has(toolId);
            
            if (wasExpanded) {
              newExpanded.delete(toolId);
            } else {
              newExpanded.add(toolId);
            }
            
            return { expandedToolIds: newExpanded };
          });
        },

        setExpandedTools: (toolIds: Set<string>) => {
          set({ expandedToolIds: toolIds });
        },

        switchView: (view: VisualizationView) => {
          set({ currentView: view });
        },

        generateTimeline: () => {
          set(({ execution }) => {
            if (!execution) return {};
            return { timeline: generateTimeline(execution) };
          });
        },

        getSelectedAgent: () => {
          const state = get();
          if (!state.execution || !state.selectedAgentId) return null;
          return findAgentById(state.execution.root_agent, state.selectedAgentId);
        },

        getAgentById: (id: string) => {
          const state = get();
          if (!state.execution) return null;
          return findAgentById(state.execution.root_agent, id);
        },
      }),
      {
        name: 'execution-store',
        partialize: (state) => ({
          execution: state.execution,
          selectedAgentId: state.selectedAgentId,
          expandedNodeIds: Array.from(state.expandedNodeIds),
          expandedToolIds: Array.from(state.expandedToolIds), // Serialize Set to Array
          currentView: state.currentView,
        }),
        merge: (persistedState: any, currentState) => ({
          ...currentState,
          ...persistedState,
          expandedNodeIds: new Set(persistedState.expandedNodeIds || []),
          expandedToolIds: new Set(persistedState.expandedToolIds || []), // Deserialize Array to Set
        }),
      }
    )
  )
);
