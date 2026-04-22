'use client'

/**
 * Model Service
 *
 * Model API calls for non-React components.
 *
 * Note: For React components, React Query hooks are recommended:
 * - useAvailableModels() - instead of getAvailableModels()
 * - useModelInstances() - get model instance list
 * - useCreateModelInstance() - create model instance
 *
 * See @/hooks/queries/models.ts for details
 */

import { apiGet, apiPost } from '@/lib/api-client'
import type {
  AvailableModel,
  TestModelOutputRequest,
  TestModelOutputResponse,
} from '@/types/models'

// Re-export types for convenience
export type { AvailableModel }

export const modelService = {
  /**
   * Get available model list (global, not workspace-specific)
   */
  async getAvailableModels(modelType: string = 'chat'): Promise<AvailableModel[]> {
    try {
      const params = new URLSearchParams()
      params.append('model_type', modelType)
      return await apiGet<AvailableModel[]>(`models?${params.toString()}`)
    } catch (error) {
      console.error('Failed to fetch available models:', error)
      throw error
    }
  },

  /**
   * Test model output (global, not workspace-specific)
   */
  async testModelOutput(modelName: string, input: string): Promise<string> {
    try {
      const payload: TestModelOutputRequest = {
        model_name: modelName,
        input,
      }
      const result = await apiPost<TestModelOutputResponse>('models/test-output', payload)

      return result.output
    } catch (error) {
      console.error('Failed to test model output:', error)
      throw error
    }
  },
}
