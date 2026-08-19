import { parseReferencesResponse } from './use-credential-references'

describe('parseReferencesResponse', () => {
  it('maps snake_case payload to typed camelCase', () => {
    const parsed = parseReferencesResponse({
      references: [
        { surface: 'agent_model_binding', resource_type: 'agent', id: 'a1', name: '客服机器人' },
        { surface: 'active_session_snapshot', resource_type: 'session', id: 's1', name: null },
      ],
      other_count: 2,
      can_archive: false,
      can_delete: false,
    })
    expect(parsed.references).toHaveLength(2)
    expect(parsed.references[0]).toEqual({
      surface: 'agent_model_binding',
      resourceType: 'agent',
      id: 'a1',
      name: '客服机器人',
    })
    expect(parsed.otherCount).toBe(2)
    expect(parsed.canArchive).toBe(false)
  })

  it('defaults gracefully on empty/missing fields', () => {
    const parsed = parseReferencesResponse({})
    expect(parsed.references).toEqual([])
    expect(parsed.otherCount).toBe(0)
    expect(parsed.canArchive).toBe(true)
    expect(parsed.canDelete).toBe(true)
  })
})
