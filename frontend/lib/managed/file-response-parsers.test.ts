import { describe, expect, it } from 'vitest'

import {
  parseFileResponse,
  parseSessionFileResourceResponse,
  parseSessionRepoResourceResponse,
  parseSessionResourceListResponse,
} from './file-response-parsers'

const FILE_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f060'
const RESOURCE_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f061'
const SESSION_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f062'

describe('file response parsers', () => {
  it('brands file and session resource identities', () => {
    expect(
      parseFileResponse({ id: `file_${FILE_UUID}`, session_id: `sess_${SESSION_UUID}` }),
    ).toMatchObject({ id: `file_${FILE_UUID}`, session_id: `sess_${SESSION_UUID}` })
    expect(
      parseSessionFileResourceResponse({
        id: `sesrsc_${RESOURCE_UUID}`,
        type: 'file',
        file_id: `file_${FILE_UUID}`,
      }),
    ).toMatchObject({ id: `sesrsc_${RESOURCE_UUID}`, file_id: `file_${FILE_UUID}` })
    expect(
      parseSessionRepoResourceResponse({
        id: `sesrsc_${RESOURCE_UUID}`,
        type: 'github_repository',
      }).id,
    ).toBe(`sesrsc_${RESOURCE_UUID}`)
  })

  it('parses mixed resource lists and rejects stale identities', () => {
    expect(
      parseSessionResourceListResponse([
        { id: `sesrsc_${RESOURCE_UUID}`, type: 'file', file_id: `file_${FILE_UUID}` },
      ]),
    ).toHaveLength(1)
    expect(() => parseFileResponse({ id: FILE_UUID })).toThrow()
    expect(() =>
      parseSessionFileResourceResponse({
        id: `file_${RESOURCE_UUID}`,
        type: 'file',
        file_id: `file_${FILE_UUID}`,
      }),
    ).toThrow()
  })
})
