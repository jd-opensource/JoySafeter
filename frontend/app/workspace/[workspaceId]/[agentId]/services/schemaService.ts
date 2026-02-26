'use client'

import { apiGet, apiPost } from '@/lib/api-client'


// --- Types ---

export interface StateFieldSchema {
    name: string
    field_type: string
    default_value?: unknown
    description?: string
    reducer?: string
}

export interface NodeSchema {
    id: string
    node_type: string
    label: string
    config: Record<string, unknown>
    state_reads: string[]
    state_writes: string[]
}

export interface EdgeSchema {
    source: string
    target: string
    edge_type?: string
    condition?: string
    route_key?: string
    source_handle_id?: string
    label?: string
    data?: Record<string, unknown>
}

export interface GraphSchema {
    name: string
    description?: string
    state_fields: StateFieldSchema[]
    nodes: NodeSchema[]
    edges: EdgeSchema[]
    entry_point: string
    metadata?: Record<string, unknown>
}

export interface SchemaValidationResult {
    valid: boolean
    errors: string[]
    warnings: string[]
    node_count: number
    edge_count: number
    state_field_count: number
}


// --- Service ---

export const schemaService = {
    /**
     * Export graph as JSON schema
     */
    async getSchema(graphId: string): Promise<GraphSchema> {
        return apiGet<GraphSchema>(`graphs/${graphId}/schema`)
    },

    /**
     * Export graph as Python code
     */
    async getSchemaCode(graphId: string): Promise<string> {
        return apiGet<string>(`graphs/${graphId}/schema/code`)
    },

    /**
     * Validate graph schema structure
     */
    async validateSchema(graphId: string): Promise<SchemaValidationResult> {
        return apiGet<SchemaValidationResult>(`graphs/${graphId}/schema/validate`)
    },

    /**
     * Import a schema to create a new graph
     */
    async importSchema(schema: GraphSchema, workspaceId?: string): Promise<{ graph_id: string }> {
        return apiPost<{ graph_id: string }>('graphs/schema/import', {
            schema,
            workspace_id: workspaceId,
        })
    },

    /**
     * Validate raw graph schema data (stateless)
     */
    async validateGraphData(schemaData: Record<string, unknown>): Promise<SchemaValidationResult> {
        return apiPost<SchemaValidationResult>('graphs/schema/validate', {
            schema_data: schemaData,
        })
    },

    /**
     * Transform ReactFlow nodes/edges to GraphSchema format
     */
    transformToGraphSchema(nodes: any[], edges: any[], name: string = 'Validation Schema'): GraphSchema {
        return {
            name,
            description: 'Temporary schema for validation',
            entry_point: '', // Not strictly needed for stateless validation unless checking entry
            state_fields: [], // We might not have state fields in frontend easily, pass empty for now
            nodes: nodes.map(n => ({
                id: n.id,
                node_type: n.data?.type || 'unknown',
                label: n.data?.label || n.id,
                config: n.data?.config || {},
                state_reads: n.data?.stateReads || [],
                state_writes: n.data?.stateWrites || [],
                metadata: {
                    position: n.position,
                    ...n.data?.metadata
                }
            })),
            edges: edges.map(e => ({
                source: e.source,
                target: e.target,
                edge_type: e.data?.edge_type || 'normal',
                route_key: e.data?.route_key,
                source_handle_id: e.data?.source_handle_id,
                condition: e.data?.condition,
                label: e.data?.label,
                data: e.data
            }))
        }
    }
}
