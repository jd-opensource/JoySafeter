import { describe, expect, it } from 'vitest'

import { parseStorageMountAuditResponse } from './storage-mount-response-parsers'

const UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f012'

describe('storage mount response parsers', () => {
  it('brands session and environment audit references', () => {
    const audit = parseStorageMountAuditResponse({
      id: UUID,
      session_id: `sess_${UUID}`,
      environment_id: `env_${UUID}`,
      action: 'mount',
      result: 'success',
      created_at: '2026-08-06T00:00:00Z',
    })

    expect(audit.session_id).toBe(`sess_${UUID}`)
    expect(audit.environment_id).toBe(`env_${UUID}`)
  })

  it('rejects cross-entity environment references', () => {
    expect(() =>
      parseStorageMountAuditResponse({
        id: UUID,
        environment_id: `agent_${UUID}`,
        action: 'mount',
        result: 'success',
        created_at: '2026-08-06T00:00:00Z',
      }),
    ).toThrow()
  })
})
