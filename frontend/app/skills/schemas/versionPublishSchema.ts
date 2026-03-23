import { z } from 'zod'

export const versionPublishSchema = z.object({
  version: z
    .string()
    .min(1, 'Version is required')
    .regex(/^\d+\.\d+\.\d+$/, 'Must be MAJOR.MINOR.PATCH format (e.g. 1.0.0)'),
  release_notes: z.string().optional().default(''),
})

export type VersionPublishFormData = z.infer<typeof versionPublishSchema>
