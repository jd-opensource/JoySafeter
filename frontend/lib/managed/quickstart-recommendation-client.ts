import { z } from 'zod'

import { managedPost } from '@/lib/api-client'
import { managedRequestOptions, type ManagedRequestScope } from '@/lib/managed/request-scope'

import {
  QUICKSTART_ENGINE_READINESS,
  QUICKSTART_EXTERNAL_TOOLS_REASONS,
  QUICKSTART_HOST_REASONS,
  type QuickstartRecommendationPhase,
  type QuickstartRecommendation,
  QUICKSTART_MCP_AUTH_REQUIREMENTS,
} from './quickstart-recommendation-contract'

// Only understand + secure are served by POST /v1/quickstart/recommendations;
// design uses the SSE /chat endpoint and prove is derived client-side.
export interface QuickstartRecommendRequestBody {
  phase: QuickstartRecommendationPhase
  intent?: string
  agent_context?: Record<string, unknown>
}

const quickstartEngineOptionSchema = z
  .object({
    engine_id: z.string().min(1),
    readiness: z.enum(QUICKSTART_ENGINE_READINESS),
    compatible_connection_count: z.number().int().nonnegative(),
  })
  .strict()

const quickstartEngineSchema = z
  .object({
    recommended_engine_id: z.string().min(1).nullable(),
    options: z.array(quickstartEngineOptionSchema).min(1),
  })
  .strict()
  .superRefine((engine, context) => {
    const optionIds = engine.options.map((option) => option.engine_id)
    if (new Set(optionIds).size !== optionIds.length) {
      context.addIssue({ code: z.ZodIssueCode.custom, message: 'Engine option IDs must be unique' })
    }
    if (engine.recommended_engine_id === null) return
    const recommended = engine.options.find(
      (option) => option.engine_id === engine.recommended_engine_id,
    )
    if (!recommended || recommended.readiness === 'unavailable') {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'Recommended engine must reference an available option',
      })
    }
  })

const quickstartEnvironmentSchema = z
  .object({
    allowed_hosts: z
      .array(z.string().trim().min(1))
      .refine((hosts) => new Set(hosts).size === hosts.length, 'Allowed hosts must be unique'),
    host_reason: z.enum(QUICKSTART_HOST_REASONS),
  })
  .strict()

const quickstartMcpServerSchema = z
  .object({
    name: z.string().min(1),
    url: z
      .string()
      .url()
      .refine((value) => {
        const protocol = new URL(value).protocol
        return protocol === 'http:' || protocol === 'https:'
      }, 'MCP URL must use HTTP or HTTPS'),
    auth_requirement: z.enum(QUICKSTART_MCP_AUTH_REQUIREMENTS),
  })
  .strict()

const quickstartCredentialGroupSchema = z
  .object({
    mcp_servers: z.array(quickstartMcpServerSchema),
    external_tools_reason: z.enum(QUICKSTART_EXTERNAL_TOOLS_REASONS),
  })
  .strict()
  .superRefine((credentialGroup, context) => {
    if (
      credentialGroup.external_tools_reason === 'mcpServers' &&
      credentialGroup.mcp_servers.length === 0
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'mcpServers reason requires at least one MCP server',
      })
    }
    if (
      credentialGroup.mcp_servers.length > 0 &&
      credentialGroup.external_tools_reason !== 'mcpServers'
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'MCP server recommendations require mcpServers reason',
      })
    }
  })

const quickstartRecommendationSchema = z.discriminatedUnion('phase', [
  z.object({ phase: z.literal('understand'), engine: quickstartEngineSchema }).strict(),
  z
    .object({
      phase: z.literal('secure'),
      environment: quickstartEnvironmentSchema,
      credential_group: quickstartCredentialGroupSchema.nullable(),
    })
    .strict(),
])

export function parseQuickstartRecommendation(raw: unknown): QuickstartRecommendation {
  return quickstartRecommendationSchema.parse(raw)
}

export async function fetchQuickstartRecommendation(
  body: QuickstartRecommendRequestBody,
  requestScope: ManagedRequestScope,
): Promise<QuickstartRecommendation> {
  const raw = await managedPost<unknown>(
    'quickstart/recommendations',
    body,
    managedRequestOptions(requestScope),
  )
  return parseQuickstartRecommendation(raw)
}
