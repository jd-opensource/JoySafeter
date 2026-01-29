/**
 * Node Configuration Templates - Predefined templates for easy node configuration.
 *
 * Provides ready-to-use configuration templates for complex nodes.
 */

export interface NodeConfigTemplate {
  name: string
  description: string
  config: Record<string, unknown>
}

export const nodeConfigTemplates: Record<string, NodeConfigTemplate[]> = {
  router_node: [
    {
      name: 'Simple If/Else',
      description: 'Basic two-way routing based on a condition',
      config: {
        routes: [
          {
            id: `route_template_1_${Date.now()}`,
            condition: "state.get('value', 0) > 10",
            targetEdgeKey: 'high',
            label: 'High Value',
            priority: 0,
          },
          {
            id: `route_template_2_${Date.now()}`,
            condition: 'True',
            targetEdgeKey: 'low',
            label: 'Low Value',
            priority: 1,
          },
        ],
        defaultRoute: 'low',
      },
    },
    {
      name: 'Multi-Condition',
      description: 'Route based on multiple conditions',
      config: {
        routes: [
          {
            id: `route_template_3_${Date.now()}`,
            condition: "state.get('value', 0) > 100",
            targetEdgeKey: 'very_high',
            label: 'Very High',
            priority: 0,
          },
          {
            id: `route_template_4_${Date.now()}`,
            condition: "state.get('value', 0) > 50",
            targetEdgeKey: 'high',
            label: 'High',
            priority: 1,
          },
          {
            id: `route_template_5_${Date.now()}`,
            condition: "state.get('value', 0) > 10",
            targetEdgeKey: 'medium',
            label: 'Medium',
            priority: 2,
          },
          {
            id: `route_template_6_${Date.now()}`,
            condition: 'True',
            targetEdgeKey: 'low',
            label: 'Low',
            priority: 3,
          },
        ],
        defaultRoute: 'low',
      },
    },
  ],
  loop_condition_node: [
    {
      name: 'Count-Based While Loop',
      description: 'Loop a fixed number of times',
      config: {
        conditionType: 'while',
        condition: 'loop_count < 3',
        maxIterations: 5,
      },
    },
    {
      name: 'Error Retry Loop',
      description: 'Retry until success or max attempts',
      config: {
        conditionType: 'doWhile',
        condition: "loop_count < 2 and state.get('has_error', False) == True",
        maxIterations: 3,
      },
    },
    {
      name: 'ForEach List Iterator',
      description: 'Iterate over a list variable',
      config: {
        conditionType: 'forEach',
        listVariable: 'items',
        maxIterations: 10,
      },
    },
    {
      name: 'Condition-Based Loop',
      description: 'Continue while condition is true',
      config: {
        conditionType: 'while',
        condition: "state.get('items_remaining', 0) > 0",
        maxIterations: 10,
      },
    },
  ],
  aggregator_node: [
    {
      name: 'Fail Fast',
      description: 'Stop immediately if any task fails',
      config: {
        error_strategy: 'fail_fast',
      },
    },
    {
      name: 'Best Effort',
      description: 'Collect all successful results, mark failures',
      config: {
        error_strategy: 'best_effort',
      },
    },
  ],
}

export const getTemplatesForNodeType = (nodeType: string): NodeConfigTemplate[] => {
  return nodeConfigTemplates[nodeType] || []
}

export const applyTemplate = (
  nodeType: string,
  templateName: string
): Record<string, unknown> | null => {
  const templates = getTemplatesForNodeType(nodeType)
  const template = templates.find((t) => t.name === templateName)
  return template ? template.config : null
}
