
import { describe, expect, it, vi } from 'vitest'
import { schemaService } from '../schemaService'
import * as apiClient from '@/lib/api-client'

// Mock the API client
vi.mock('@/lib/api-client', () => ({
    apiGet: vi.fn(),
    apiPost: vi.fn(),
}))

describe('schemaService', () => {
    const graphId = 'test-graph-id'

    it('getSchema calls apiGet with correct URL', async () => {
        const mockSchema = { name: 'Test Graph', nodes: [], edges: [], state_fields: [], entry_point: 'agent' }
        vi.mocked(apiClient.apiGet).mockResolvedValue(mockSchema)

        const result = await schemaService.getSchema(graphId)

        expect(apiClient.apiGet).toHaveBeenCalledWith(`graphs/${graphId}/schema`)
        expect(result).toEqual(mockSchema)
    })

    it('getSchemaCode calls apiGet with correct URL', async () => {
        const mockCode = 'def build_graph(): pass'
        vi.mocked(apiClient.apiGet).mockResolvedValue(mockCode)

        const result = await schemaService.getSchemaCode(graphId)

        expect(apiClient.apiGet).toHaveBeenCalledWith(`graphs/${graphId}/schema/code`)
        expect(result).toEqual(mockCode)
    })

    it('validateSchema calls apiGet with correct URL', async () => {
        const mockValidation = { valid: true, errors: [], warnings: [], node_count: 5, edge_count: 4, state_field_count: 0 }
        vi.mocked(apiClient.apiGet).mockResolvedValue(mockValidation)

        const result = await schemaService.validateSchema(graphId)

        expect(apiClient.apiGet).toHaveBeenCalledWith(`graphs/${graphId}/schema/validate`)
        expect(result).toEqual(mockValidation)
    })

    it('importSchema calls apiPost with correct URL and body', async () => {
        const mockSchema = { name: 'Imported Graph', nodes: [], edges: [], state_fields: [], entry_point: 'agent' }
        const mockResponse = { graph_id: 'new-graph-id' }
        vi.mocked(apiClient.apiPost).mockResolvedValue(mockResponse)

        const result = await schemaService.importSchema(mockSchema as any, 'workspace-1')

        expect(apiClient.apiPost).toHaveBeenCalledWith('graphs/schema/import', {
            schema: mockSchema,
            workspace_id: 'workspace-1',
        })
        expect(result).toEqual(mockResponse)
    })
})
