'use client'

import { Node, Edge } from 'reactflow'

import { agentService, type AgentGraph } from './agentService'

export interface GraphTemplate {
  nodes: Node[]
  edges: Edge[]
  viewport?: { x: number; y: number; zoom: number }
}

/**
 * Graph Template Service
 * Provides functionality to load graph templates and create graphs from templates
 */
class GraphTemplateService {
  /**
   * Load a graph template from JSON file
   * @param templateName Template name (without .json extension)
   * @returns Template data with nodes, edges, and viewport
   */
  async loadTemplate(templateName: string): Promise<GraphTemplate> {
    try {
      const response = await fetch(`/data/graph-templates/${templateName}.json`)
      if (!response.ok) {
        throw new Error(`Failed to load template: ${templateName}. Status: ${response.status}`)
      }

      const data = await response.json()

      // Validate template structure
      if (!data.nodes || !Array.isArray(data.nodes)) {
        throw new Error(`Invalid template format: missing or invalid nodes array`)
      }
      if (!data.edges || !Array.isArray(data.edges)) {
        throw new Error(`Invalid template format: missing or invalid edges array`)
      }

      return {
        nodes: data.nodes,
        edges: data.edges,
        viewport: data.viewport || { x: 0, y: 0, zoom: 1 },
      }
    } catch (error) {
      console.error(`Error loading template ${templateName}:`, error)
      throw error
    }
  }

  /**
   * Create a new graph from a template
   * - Loads the template
   * - Regenerates all node IDs to avoid conflicts
   * - Updates edge references to new node IDs
   * - Creates the graph and saves its state
   *
   * @param templateName Template name (without .json extension)
   * @param graphName Name for the new graph
   * @param workspaceId Workspace ID where the graph will be created
   * @param description Optional description (defaults to template-specific fallback)
   * @returns Created graph object
   */
  async createGraphFromTemplate(
    templateName: string,
    graphName: string,
    workspaceId: string,
    description?: string
  ): Promise<AgentGraph> {
    // 1. Load template
    const template = await this.loadTemplate(templateName)

    // 2. Regenerate node IDs and create mapping
    const nodeIdMap = new Map<string, string>()
    const timestamp = Date.now()
    const newNodes = template.nodes.map((node, index) => {
      // Use index to ensure uniqueness even if called in quick succession
      const newId = `node_${timestamp}_${index}_${Math.random().toString(36).slice(2, 7)}`
      nodeIdMap.set(node.id, newId)
      return {
        ...node,
        id: newId,
      }
    })

    // 3. Update edges with new source and target IDs
    const newEdges = template.edges.map((edge, index) => ({
      ...edge,
      source: nodeIdMap.get(edge.source) || edge.source,
      target: nodeIdMap.get(edge.target) || edge.target,
      // Regenerate edge ID as well
      id: `edge_${timestamp}_${index}_${Math.random().toString(36).slice(2, 7)}`,
    }))

    // 4. Create graph metadata
    const graphDescription =
      description ?? (templateName === 'default-chat' ? 'Default chat with all available skills, Docker backend' : 'APK Intent Bridge Security Analyzer')
    const graph = await agentService.createGraph({
      name: graphName,
      description: graphDescription,
      workspaceId: workspaceId,
    })

    // 5. Save graph state (nodes, edges, viewport)
    await agentService.saveGraphState({
      graphId: graph.id,
      nodes: newNodes,
      edges: newEdges,
      viewport: template.viewport || { x: 0, y: 0, zoom: 1 },
    })

    return graph
  }
}

export const graphTemplateService = new GraphTemplateService()
