import { z } from 'zod'

import { validateSkillName, validateSkillDescription, validateCompatibility } from '@/utils/skillValidators'

/**
 * Skill form schema using Zod validation
 * Per Agent Skills specification: https://agentskills.io/specification
 */
export const skillFormSchema = z.object({
  name: z.string()
    .min(1, 'Skill name is required')
    .max(64, 'Skill name must be 64 characters or less')
    .refine(
      (val) => {
        const result = validateSkillName(val)
        return result.valid
      },
      (val) => {
        const result = validateSkillName(val)
        return { message: result.error || 'Invalid skill name format' }
      }
    ),
  description: z.string()
    .min(1, 'Skill description is required')
    .max(1024, 'Skill description must be 1024 characters or less')
    .refine(
      (val) => {
        const result = validateSkillDescription(val)
        return result.valid
      },
      (val) => {
        const result = validateSkillDescription(val)
        return { message: result.error || 'Invalid skill description' }
      }
    ),
  content: z.string().default(''),
  license: z.string().optional(),
  compatibility: z.string()
    .max(500, 'Compatibility must be 500 characters or less')
    .nullish()
    .refine(
      (val) => {
        if (!val) return true
        const result = validateCompatibility(val)
        return result.valid
      },
      (val) => {
        if (!val) return { message: '' }
        const result = validateCompatibility(val)
        return { message: result.error || 'Invalid compatibility' }
      }
    ),
  metadata: z.record(z.string(), z.string()).optional().default({}),
  allowed_tools: z.array(z.string()).optional().default([]),
  is_public: z.boolean().default(false),
  files: z.array(z.any()).optional().default([]),
  source: z.enum(['local', 'git', 's3']).optional().default('local'),
})

export type SkillFormData = z.infer<typeof skillFormSchema>
