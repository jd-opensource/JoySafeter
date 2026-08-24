import { parseCredentialGroupId } from '@/types/entity-id'
import type { CredentialGroup, CredentialGroupCredential } from '@/types/managed'

import { parseCredentialResponse } from './credential-response-parsers'

type RawCredentialGroup = Omit<CredentialGroup, 'id'> & { id: string }
export function parseCredentialGroupResponse(response: unknown): CredentialGroup {
  const raw = response as RawCredentialGroup
  return { ...raw, id: parseCredentialGroupId(raw.id) }
}

export function parseCredentialGroupListResponse(response: unknown[]): CredentialGroup[] {
  return response.map(parseCredentialGroupResponse)
}

export function parseCredentialGroupCredentialResponse(
  response: unknown,
): CredentialGroupCredential {
  const credential = parseCredentialResponse(response)
  if (
    credential.kind !== 'mcp' ||
    !credential.group_id ||
    !credential.mcp_server_url?.trim() ||
    !credential.auth_scheme
  ) {
    throw new Error('Invalid MCP credential group member')
  }
  return {
    id: credential.id,
    group_id: credential.group_id,
    name: credential.name,
    mcp_server_url: credential.mcp_server_url,
    auth_scheme: credential.auth_scheme,
    data: credential.data,
    created_at: credential.created_at,
    updated_at: credential.updated_at,
    archived_at: credential.archived_at,
  }
}

export function parseCredentialGroupCredentialListResponse(
  response: unknown[],
): CredentialGroupCredential[] {
  return response.map(parseCredentialGroupCredentialResponse)
}
