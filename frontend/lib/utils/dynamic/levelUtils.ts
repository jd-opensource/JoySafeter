/**
 * Utility functions for multi-level agent execution hierarchy
 * Provides functions to traverse, analyze, and manipulate agent trees
 */

import type { Agent, ExecutionTree, LevelStatistics } from '@/types/dynamic/execution';

/**
 * Get all agents from an execution tree (flattened)
 * @param execution - The execution tree
 * @returns Array of all agents in the tree
 */
export function getAllAgents(execution: ExecutionTree): Agent[] {
  const agents: Agent[] = [];

  function traverse(agent: Agent) {
    agents.push(agent);

    // Traverse sub_agents
    if (agent.sub_agents && agent.sub_agents.length > 0) {
      agent.sub_agents.forEach(traverse);
    }

    // Traverse child_agents (spawned by agent_tool)
    if (agent.child_agents && agent.child_agents.length > 0) {
      agent.child_agents.forEach(traverse);
    }
  }

  traverse(execution.root_agent);
  return agents;
}

/**
 * Get agents filtered by level
 * @param execution - The execution tree
 * @param level - The level to filter by (1, 2, 3, ...)
 * @returns Array of agents at the specified level
 */
export function getAgentsByLevel(execution: ExecutionTree, level: number): Agent[] {
  const allAgents = getAllAgents(execution);
  return allAgents.filter(agent => agent.level === level);
}

/**
 * Get the maximum nesting depth in the execution tree
 * @param execution - The execution tree
 * @returns The highest level number in the tree
 */
export function getMaxDepth(execution: ExecutionTree): number {
  const allAgents = getAllAgents(execution);
  if (allAgents.length === 0) return 0;

  return Math.max(...allAgents.map(agent => agent.level));
}

/**
 * Calculate statistics for each level in the execution tree
 * @param execution - The execution tree
 * @returns Array of level statistics, one per level
 */
export function calculateLevelStatistics(execution: ExecutionTree): LevelStatistics[] {
  const maxDepth = getMaxDepth(execution);
  const statistics: LevelStatistics[] = [];

  for (let level = 1; level <= maxDepth; level++) {
    const agentsAtLevel = getAgentsByLevel(execution, level);

    if (agentsAtLevel.length === 0) {
      continue;
    }

    // Calculate tool count
    const toolCount = agentsAtLevel.reduce(
      (sum, agent) => sum + (agent.tool_invocations?.length || 0),
      0
    );

    // Calculate total duration
    const totalDuration = agentsAtLevel.reduce(
      (sum, agent) => sum + agent.duration_ms,
      0
    );

    // Calculate average duration
    const avgDuration = totalDuration / agentsAtLevel.length;

    // Calculate success rate
    const completedAgents = agentsAtLevel.filter(
      agent => agent.status === 'completed'
    ).length;
    const successRate = (completedAgents / agentsAtLevel.length) * 100;

    statistics.push({
      level,
      agent_count: agentsAtLevel.length,
      tool_count: toolCount,
      avg_duration_ms: avgDuration,
      success_rate: successRate,
      total_duration_ms: totalDuration,
    });
  }

  return statistics;
}

/**
 * Get color for a specific level (for visual hierarchy)
 * @param level - The level number (1, 2, 3, ...)
 * @returns CSS color string
 */
export function getLevelColor(level: number): string {
  const colors = [
    '#667eea', // Level 1: Purple
    '#3b82f6', // Level 2: Blue
    '#10b981', // Level 3: Green
    '#f59e0b', // Level 4: Orange
    '#ef4444', // Level 5: Red
    '#8b5cf6', // Level 6: Violet
  ];

  // Cycle through colors if level exceeds array length
  return colors[(level - 1) % colors.length];
}

/**
 * Find the parent agent of a given agent
 * @param execution - The execution tree
 * @param agentId - The ID of the agent to find parent for
 * @returns The parent agent, or null if not found or is root
 */
export function findParentAgent(execution: ExecutionTree, agentId: string): Agent | null {
  if (execution.root_agent.id === agentId) {
    return null; // Root agent has no parent
  }

  function search(agent: Agent): Agent | null {
    // Check sub_agents
    if (agent.sub_agents && agent.sub_agents.length > 0) {
      for (const subAgent of agent.sub_agents) {
        if (subAgent.id === agentId) {
          return agent;
        }
        const found = search(subAgent);
        if (found) return found;
      }
    }

    // Check child_agents
    if (agent.child_agents && agent.child_agents.length > 0) {
      for (const childAgent of agent.child_agents) {
        if (childAgent.id === agentId) {
          return agent;
        }
        const found = search(childAgent);
        if (found) return found;
      }
    }

    return null;
  }

  return search(execution.root_agent);
}

/**
 * Get level badge text for display
 * @param level - The level number (1, 2, 3, ...)
 * @returns Formatted level badge text
 */
export function getLevelBadgeText(level: number): string {
  // Level is already 1-based from backend
  return `Level ${level}`;
}

/**
 * Calculate indentation in pixels for a given level
 * @param level - The level number (1, 2, 3, ...)
 * @returns Indentation in pixels
 */
export function getLevelIndentation(level: number): number {
  // Level 1: 0px, Level 2: 20px, Level 3: 40px, etc.
  return (level - 1) * 20;
}

/**
 * Check if an agent has child agents spawned by agent_tool
 * @param agent - The agent to check
 * @returns True if agent has child agents
 */
export function hasChildAgents(agent: Agent): boolean {
  return Boolean(agent.child_agents && agent.child_agents.length > 0);
}

/**
 * Get all agent_tool invocations from an agent
 * @param agent - The agent to check
 * @returns Array of agent_tool invocations
 */
export function getAgentToolInvocations(agent: Agent) {
  if (!agent.tool_invocations) return [];

  return agent.tool_invocations.filter((tool: any) => tool.is_agent_tool === true);
}

/**
 * Find an agent by ID in the execution tree
 * @param execution - The execution tree
 * @param agentId - The ID of the agent to find
 * @returns The agent, or null if not found
 */
export function findAgentById(execution: ExecutionTree, agentId: string): Agent | null {
  const allAgents = getAllAgents(execution);
  return allAgents.find(agent => agent.id === agentId) || null;
}
