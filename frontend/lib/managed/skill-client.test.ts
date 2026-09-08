import { beforeEach, describe, expect, it, vi } from 'vitest'

import { managedDelete, managedGet, managedPost, managedPut, managedUpload } from '@/lib/api-client'
import { ORGANIZATION_ID, PROJECT_ID } from '@/test-utils/entity-ids'
import {
  parseSkillFileId,
  parseSkillId,
  parseSkillSecurityScanId,
  parseSkillUsageId,
  parseSkillVersionFileId,
  parseSkillVersionId,
} from '@/types/entity-id'

import {
  approveManagedSkillPromotion,
  createManagedSkill,
  createManagedSkillFile,
  deleteManagedSkill,
  deleteManagedSkillFile,
  deleteManagedSkillVersion,
  fetchManagedSkill,
  fetchManagedSkillFiles,
  fetchManagedLatestSkillSecurityScan,
  fetchManagedSkillOptions,
  fetchManagedSkillRecentUsage,
  fetchManagedSkillSecurityHistory,
  fetchManagedSkillSecurityScans,
  fetchManagedSkillTargetUsage,
  fetchManagedSkillVersionFiles,
  fetchManagedSkillVersionOptions,
  fetchManagedSkillVersions,
  fetchManagedSkills,
  importManagedSkillZip,
  managedSkillFilesQueryKey,
  managedSkillOptionsQueryKey,
  managedSkillQueryKey,
  managedSkillRecentUsageQueryKey,
  managedSkillSecurityHistoryQueryKey,
  managedSkillScopeQueryPrefix,
  managedSkillTargetUsageQueryKey,
  managedSkillVersionFilesQueryKey,
  managedSkillVersionsQueryKey,
  publishManagedSkillVersion,
  rejectManagedSkillPromotion,
  rescanManagedSkillSecurity,
  restoreManagedSkillVersion,
  saveManagedSkillAuthoringDraft,
  submitManagedSkillPromotion,
  takedownManagedSkill,
  transitionManagedSkillLifecycle,
  updateManagedSkill,
  updateManagedSkillFile,
} from './skill-client'
import type {
  SkillDeleteResponse,
  SkillFileDeleteResponse,
  SkillVersionDeleteResponse,
} from './skill-response-parsers'

vi.mock('@/lib/api-client', () => ({
  managedDelete: vi.fn(),
  managedGet: vi.fn(),
  managedPost: vi.fn(),
  managedPut: vi.fn(),
  managedUpload: vi.fn(),
}))

const SKILL_ID = parseSkillId('skill_018f6f42-0a51-7cc4-98c8-4f6f0ca5f120')
const OTHER_SKILL_ID = parseSkillId('skill_018f6f42-0a51-7cc4-98c8-4f6f0ca5f121')
const SKILL_VERSION_ID = parseSkillVersionId('sklver_018f6f42-0a51-7cc4-98c8-4f6f0ca5f122')
const OTHER_SKILL_VERSION_ID = parseSkillVersionId('sklver_018f6f42-0a51-7cc4-98c8-4f6f0ca5f123')
const SKILL_FILE_ID = parseSkillFileId('sklfile_018f6f42-0a51-7cc4-98c8-4f6f0ca5f124')
const SKILL_VERSION_FILE_ID = parseSkillVersionFileId(
  'sklvfile_018f6f42-0a51-7cc4-98c8-4f6f0ca5f125',
)
const SKILL_SECURITY_SCAN_ID = parseSkillSecurityScanId(
  'sklscan_018f6f42-0a51-7cc4-98c8-4f6f0ca5f126',
)
const OTHER_SKILL_SECURITY_SCAN_ID = parseSkillSecurityScanId(
  'sklscan_018f6f42-0a51-7cc4-98c8-4f6f0ca5f127',
)
const SKILL_USAGE_ID = parseSkillUsageId('skluse_018f6f42-0a51-7cc4-98c8-4f6f0ca5f128')
const SKILL_DELETED_TYPE = ['skill', 'deleted'].join('_') as SkillDeleteResponse['type']
const SKILL_FILE_DELETED_TYPE = ['skill', 'file', 'deleted'].join(
  '_',
) as SkillFileDeleteResponse['type']
const SKILL_VERSION_DELETED_TYPE = ['skill', 'version', 'deleted'].join(
  '_',
) as SkillVersionDeleteResponse['type']
const requestScope = {
  orgId: ORGANIZATION_ID,
  projectId: PROJECT_ID,
  key: `${ORGANIZATION_ID}:${PROJECT_ID}`,
}

function rawSkill(id: string) {
  return {
    id,
    name: id === SKILL_ID ? 'Primary' : 'Secondary',
    created_at: '2026-09-03T00:00:00Z',
    updated_at: '2026-09-03T00:00:00Z',
  }
}

function rawSkillVersion(id: string, version: string) {
  return {
    id,
    skill_id: SKILL_ID,
    version,
  }
}

function rawSkillFile(id: string) {
  return {
    id,
    skill_id: SKILL_ID,
    path: '',
    file_name: 'SKILL.md',
    content: null,
  }
}

function rawSecurityScan(id: string) {
  return {
    id,
    skill_id: SKILL_ID,
    owner_id: null,
    target_hash: 'a'.repeat(64),
  }
}

describe('managed Skill client', () => {
  beforeEach(() => {
    vi.mocked(managedGet).mockReset()
    vi.mocked(managedPost).mockReset()
    vi.mocked(managedPut).mockReset()
    vi.mocked(managedDelete).mockReset()
    vi.mocked(managedUpload).mockReset()
  })

  it('owns typed paginated Skill transport', async () => {
    vi.mocked(managedGet).mockResolvedValue({
      data: [rawSkill(SKILL_ID)],
      has_more: false,
      first_id: SKILL_ID,
      last_id: SKILL_ID,
    })

    await expect(
      fetchManagedSkills({ limit: 25, afterId: OTHER_SKILL_ID }, requestScope),
    ).resolves.toEqual({
      items: [expect.objectContaining({ id: SKILL_ID, name: 'Primary' })],
      hasMore: false,
      firstId: SKILL_ID,
      lastId: SKILL_ID,
    })
    expect(managedGet).toHaveBeenCalledWith(
      `/skills?limit=25&after_id=${OTHER_SKILL_ID}`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('collects every option page under one cache identity', async () => {
    vi.mocked(managedGet)
      .mockResolvedValueOnce({
        data: [rawSkill(SKILL_ID)],
        has_more: true,
        first_id: SKILL_ID,
        last_id: SKILL_ID,
      })
      .mockResolvedValueOnce({
        data: [rawSkill(OTHER_SKILL_ID)],
        has_more: false,
        first_id: OTHER_SKILL_ID,
        last_id: OTHER_SKILL_ID,
      })

    expect(managedSkillOptionsQueryKey(requestScope.key)).toEqual([
      'skills',
      requestScope.key,
      'options',
    ])
    expect(managedSkillScopeQueryPrefix(requestScope.key)).toEqual(['skills', requestScope.key])
    await expect(fetchManagedSkillOptions(requestScope)).resolves.toEqual([
      expect.objectContaining({ id: SKILL_ID }),
      expect.objectContaining({ id: OTHER_SKILL_ID }),
    ])
    expect(managedGet).toHaveBeenNthCalledWith(
      2,
      `/skills?limit=100&after_id=${SKILL_ID}`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('rejects non-canonical list responses', async () => {
    vi.mocked(managedGet).mockResolvedValue([rawSkill(SKILL_ID)])
    await expect(fetchManagedSkills({}, requestScope)).rejects.toThrow(/Skill list response/)
  })

  it('owns typed paginated Skill version transport', async () => {
    vi.mocked(managedGet).mockResolvedValue({
      data: [rawSkillVersion(SKILL_VERSION_ID, '1.0.0')],
      has_more: false,
      first_id: SKILL_VERSION_ID,
      last_id: SKILL_VERSION_ID,
    })

    await expect(
      fetchManagedSkillVersions(
        SKILL_ID,
        { limit: 25, afterId: OTHER_SKILL_VERSION_ID },
        requestScope,
      ),
    ).resolves.toEqual({
      items: [
        expect.objectContaining({
          id: SKILL_VERSION_ID,
          skill_id: SKILL_ID,
          version: '1.0.0',
        }),
      ],
      hasMore: false,
      firstId: SKILL_VERSION_ID,
      lastId: SKILL_VERSION_ID,
    })
    expect(managedGet).toHaveBeenCalledWith(
      `/skills/${SKILL_ID}/versions?limit=25&after_id=${OTHER_SKILL_VERSION_ID}`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('collects every Skill version page under one cache identity', async () => {
    vi.mocked(managedGet)
      .mockResolvedValueOnce({
        data: [rawSkillVersion(SKILL_VERSION_ID, '2.0.0')],
        has_more: true,
        first_id: SKILL_VERSION_ID,
        last_id: SKILL_VERSION_ID,
      })
      .mockResolvedValueOnce({
        data: [rawSkillVersion(OTHER_SKILL_VERSION_ID, '1.0.0')],
        has_more: false,
        first_id: OTHER_SKILL_VERSION_ID,
        last_id: OTHER_SKILL_VERSION_ID,
      })

    expect(managedSkillVersionsQueryKey(requestScope.key, SKILL_ID)).toEqual([
      'skills',
      requestScope.key,
      SKILL_ID,
      'versions',
    ])
    await expect(fetchManagedSkillVersionOptions(SKILL_ID, requestScope)).resolves.toEqual([
      expect.objectContaining({ id: SKILL_VERSION_ID, version: '2.0.0' }),
      expect.objectContaining({ id: OTHER_SKILL_VERSION_ID, version: '1.0.0' }),
    ])
    expect(managedGet).toHaveBeenNthCalledWith(
      2,
      `/skills/${SKILL_ID}/versions?limit=100&after_id=${SKILL_VERSION_ID}`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('rejects non-canonical Skill version pages', async () => {
    vi.mocked(managedGet).mockResolvedValue([rawSkillVersion(SKILL_VERSION_ID, '1.0.0')])
    await expect(fetchManagedSkillVersions(SKILL_ID, {}, requestScope)).rejects.toThrow(
      /Skill version list response/,
    )
  })

  it('rejects Skill version pagination that does not advance', async () => {
    vi.mocked(managedGet)
      .mockResolvedValueOnce({
        data: [rawSkillVersion(SKILL_VERSION_ID, '2.0.0')],
        has_more: true,
        first_id: SKILL_VERSION_ID,
        last_id: SKILL_VERSION_ID,
      })
      .mockResolvedValueOnce({
        data: [rawSkillVersion(SKILL_VERSION_ID, '2.0.0')],
        has_more: true,
        first_id: SKILL_VERSION_ID,
        last_id: SKILL_VERSION_ID,
      })

    await expect(fetchManagedSkillVersionOptions(SKILL_ID, requestScope)).rejects.toThrow(
      /Skill version options pagination returned an invalid cursor/,
    )
  })

  it('owns Skill detail and non-paginated file collection transport', async () => {
    vi.mocked(managedGet)
      .mockResolvedValueOnce(rawSkill(SKILL_ID))
      .mockResolvedValueOnce({
        data: [{ id: SKILL_FILE_ID, skill_id: SKILL_ID, content: null }],
      })
      .mockResolvedValueOnce({
        data: [{ id: SKILL_VERSION_FILE_ID, version_id: SKILL_VERSION_ID, content: null }],
      })

    expect(managedSkillQueryKey(requestScope.key, SKILL_ID)).toEqual([
      'skills',
      requestScope.key,
      SKILL_ID,
      'detail',
    ])
    expect(managedSkillFilesQueryKey(requestScope.key, SKILL_ID)).toEqual([
      'skills',
      requestScope.key,
      SKILL_ID,
      'files',
    ])
    expect(managedSkillVersionFilesQueryKey(requestScope.key, SKILL_ID, '1.0.0')).toEqual([
      'skills',
      requestScope.key,
      SKILL_ID,
      'versions',
      '1.0.0',
      'files',
    ])
    await expect(fetchManagedSkill(SKILL_ID, requestScope)).resolves.toEqual(
      expect.objectContaining({ id: SKILL_ID }),
    )
    await expect(fetchManagedSkillFiles(SKILL_ID, requestScope)).resolves.toEqual([
      expect.objectContaining({ id: SKILL_FILE_ID, skill_id: SKILL_ID, content: '' }),
    ])
    await expect(fetchManagedSkillVersionFiles(SKILL_ID, '1.0.0', requestScope)).resolves.toEqual([
      expect.objectContaining({
        id: SKILL_VERSION_FILE_ID,
        version_id: SKILL_VERSION_ID,
        content: '',
      }),
    ])
  })

  it('rejects non-canonical Skill file collection responses', async () => {
    vi.mocked(managedGet).mockResolvedValue([])
    await expect(fetchManagedSkillFiles(SKILL_ID, requestScope)).rejects.toThrow(
      /Skill file list response/,
    )
  })

  it('collects complete Skill security history under one cache identity', async () => {
    vi.mocked(managedGet)
      .mockResolvedValueOnce({
        data: [rawSecurityScan(SKILL_SECURITY_SCAN_ID)],
        has_more: true,
        first_id: SKILL_SECURITY_SCAN_ID,
        last_id: SKILL_SECURITY_SCAN_ID,
      })
      .mockResolvedValueOnce({
        data: [rawSecurityScan(OTHER_SKILL_SECURITY_SCAN_ID)],
        has_more: false,
        first_id: OTHER_SKILL_SECURITY_SCAN_ID,
        last_id: OTHER_SKILL_SECURITY_SCAN_ID,
      })

    expect(managedSkillSecurityHistoryQueryKey(requestScope.key, SKILL_ID)).toEqual([
      'skills',
      requestScope.key,
      SKILL_ID,
      'security-scans',
    ])
    await expect(fetchManagedSkillSecurityHistory(SKILL_ID, requestScope)).resolves.toEqual([
      expect.objectContaining({ id: SKILL_SECURITY_SCAN_ID, skill_id: SKILL_ID }),
      expect.objectContaining({ id: OTHER_SKILL_SECURITY_SCAN_ID, skill_id: SKILL_ID }),
    ])
    expect(managedGet).toHaveBeenNthCalledWith(
      2,
      `/skills/${SKILL_ID}/security-scans?limit=100&after_id=${SKILL_SECURITY_SCAN_ID}`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('rejects malformed or non-advancing Skill security history', async () => {
    vi.mocked(managedGet).mockResolvedValueOnce({ data: [], has_more: 'false' })
    await expect(fetchManagedSkillSecurityScans(SKILL_ID, {}, requestScope)).rejects.toThrow(
      /Skill security scan list response/,
    )

    vi.mocked(managedGet)
      .mockResolvedValueOnce({
        data: [rawSecurityScan(SKILL_SECURITY_SCAN_ID)],
        has_more: true,
        first_id: SKILL_SECURITY_SCAN_ID,
        last_id: SKILL_SECURITY_SCAN_ID,
      })
      .mockResolvedValueOnce({
        data: [rawSecurityScan(SKILL_SECURITY_SCAN_ID)],
        has_more: true,
        first_id: SKILL_SECURITY_SCAN_ID,
        last_id: SKILL_SECURITY_SCAN_ID,
      })
    await expect(fetchManagedSkillSecurityHistory(SKILL_ID, requestScope)).rejects.toThrow(
      /Skill security history pagination returned an invalid cursor/,
    )
  })

  it('owns explicit recent and target-hash Skill usage windows', async () => {
    vi.mocked(managedGet).mockResolvedValue({
      data: [{ id: SKILL_USAGE_ID, skill_id: SKILL_ID }],
      has_more: true,
      first_id: SKILL_USAGE_ID,
      last_id: SKILL_USAGE_ID,
    })
    const targetHash = 'b'.repeat(64)

    expect(managedSkillRecentUsageQueryKey(requestScope.key, SKILL_ID)).toEqual([
      'skills',
      requestScope.key,
      SKILL_ID,
      'usage',
      'recent',
    ])
    expect(managedSkillTargetUsageQueryKey(requestScope.key, targetHash)).toEqual([
      'skills',
      requestScope.key,
      'usage',
      'target-hash',
      targetHash,
    ])
    await expect(fetchManagedSkillRecentUsage(SKILL_ID, requestScope)).resolves.toEqual([
      expect.objectContaining({ id: SKILL_USAGE_ID, skill_id: SKILL_ID }),
    ])
    await expect(fetchManagedSkillTargetUsage(targetHash, requestScope)).resolves.toEqual([
      expect.objectContaining({ id: SKILL_USAGE_ID, skill_id: SKILL_ID }),
    ])
    expect(managedGet).toHaveBeenNthCalledWith(
      1,
      `/skills/${SKILL_ID}/usage?limit=5`,
      expect.objectContaining({ skipManagedContext: true }),
    )
    expect(managedGet).toHaveBeenNthCalledWith(
      2,
      `/skills/usage/search?limit=5&target_hash=${targetHash}`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('owns Skill security rescan transport', async () => {
    vi.mocked(managedPost).mockResolvedValue(rawSecurityScan(SKILL_SECURITY_SCAN_ID))
    await expect(rescanManagedSkillSecurity(SKILL_ID, requestScope)).resolves.toEqual(
      expect.objectContaining({ id: SKILL_SECURITY_SCAN_ID, skill_id: SKILL_ID }),
    )
    expect(managedPost).toHaveBeenCalledWith(
      `/skills/${SKILL_ID}/security-scans/rescan`,
      {},
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('owns Skill create, import, update, and delete transport', async () => {
    vi.mocked(managedPost).mockResolvedValue(rawSkill(SKILL_ID))
    vi.mocked(managedUpload).mockResolvedValue(rawSkill(SKILL_ID))
    vi.mocked(managedPut).mockResolvedValue(rawSkill(SKILL_ID))
    vi.mocked(managedDelete).mockResolvedValue({ id: SKILL_ID, type: SKILL_DELETED_TYPE })
    const createInput = {
      name: 'primary',
      description: 'Primary skill',
      content: '# Primary',
      tags: ['test'],
      license: 'MIT',
      source_type: 'local',
      files: [
        {
          path: '',
          file_name: 'SKILL.md',
          file_type: 'markdown',
          content: '# Primary',
          size: 9,
        },
      ],
    }
    const updateInput = {
      name: 'primary',
      description: 'Updated',
      content: '# Updated',
      license: 'MIT',
      tags: ['updated'],
      source_type: 'local',
      source_url: '',
    }

    await expect(createManagedSkill(createInput, requestScope)).resolves.toEqual(
      expect.objectContaining({ id: SKILL_ID }),
    )
    expect(managedPost).toHaveBeenCalledWith(
      '/skills',
      createInput,
      expect.objectContaining({ skipManagedContext: true, timeout: 200_000 }),
    )

    const zip = new File(['zip'], 'skill.zip', { type: 'application/zip' })
    await expect(importManagedSkillZip(zip, requestScope)).resolves.toEqual(
      expect.objectContaining({ id: SKILL_ID }),
    )
    expect(managedUpload).toHaveBeenCalledWith(
      '/skills/import-zip',
      expect.any(FormData),
      expect.objectContaining({ skipManagedContext: true }),
    )

    await expect(updateManagedSkill(SKILL_ID, updateInput, requestScope)).resolves.toEqual(
      expect.objectContaining({ id: SKILL_ID }),
    )
    expect(managedPut).toHaveBeenCalledWith(
      `/skills/${SKILL_ID}`,
      updateInput,
      expect.objectContaining({ skipManagedContext: true, timeout: 200_000 }),
    )

    await expect(deleteManagedSkill(SKILL_ID, requestScope)).resolves.toEqual({
      id: SKILL_ID,
      type: SKILL_DELETED_TYPE,
    })
    expect(managedDelete).toHaveBeenCalledWith(
      `/skills/${SKILL_ID}`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('owns Skill file write transport', async () => {
    vi.mocked(managedPost).mockResolvedValue(rawSkillFile(SKILL_FILE_ID))
    vi.mocked(managedPut).mockResolvedValue(rawSkillFile(SKILL_FILE_ID))
    vi.mocked(managedDelete).mockResolvedValue({
      id: SKILL_FILE_ID,
      type: SKILL_FILE_DELETED_TYPE,
    })

    await expect(
      createManagedSkillFile(
        SKILL_ID,
        { path: '', file_name: 'SKILL.md', file_type: 'markdown', content: '' },
        requestScope,
      ),
    ).resolves.toEqual(expect.objectContaining({ id: SKILL_FILE_ID, content: '' }))
    expect(managedPost).toHaveBeenCalledWith(
      `/skills/${SKILL_ID}/files`,
      { path: '', file_name: 'SKILL.md', file_type: 'markdown', content: '' },
      expect.objectContaining({ skipManagedContext: true, timeout: 200_000 }),
    )

    await expect(
      updateManagedSkillFile(SKILL_ID, SKILL_FILE_ID, { path: 'docs/' }, requestScope),
    ).resolves.toEqual(expect.objectContaining({ id: SKILL_FILE_ID }))
    expect(managedPut).toHaveBeenCalledWith(
      `/skills/${SKILL_ID}/files/${SKILL_FILE_ID}`,
      { path: 'docs/' },
      expect.objectContaining({ skipManagedContext: true, timeout: 200_000 }),
    )

    await expect(deleteManagedSkillFile(SKILL_ID, SKILL_FILE_ID, requestScope)).resolves.toEqual({
      id: SKILL_FILE_ID,
      type: SKILL_FILE_DELETED_TYPE,
    })
    expect(managedDelete).toHaveBeenCalledWith(
      `/skills/${SKILL_ID}/files/${SKILL_FILE_ID}`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('owns Skill version, promotion, takedown, and lifecycle transport', async () => {
    vi.mocked(managedPost)
      .mockResolvedValueOnce(rawSkillVersion(SKILL_VERSION_ID, '1.0.0'))
      .mockResolvedValueOnce(rawSkill(SKILL_ID))
      .mockResolvedValueOnce(rawSkillVersion(SKILL_VERSION_ID, '1.0.0'))
      .mockResolvedValueOnce(rawSkillVersion(SKILL_VERSION_ID, '1.0.0'))
      .mockResolvedValueOnce(rawSkillVersion(SKILL_VERSION_ID, '1.0.0'))
      .mockResolvedValueOnce(rawSkill(SKILL_ID))
      .mockResolvedValueOnce({
        skill_id: SKILL_ID,
        from_status: 'draft',
        to_status: 'pending_review',
      })
    vi.mocked(managedDelete).mockResolvedValue({ type: SKILL_VERSION_DELETED_TYPE })

    await publishManagedSkillVersion(SKILL_ID, {}, requestScope)
    await restoreManagedSkillVersion(SKILL_ID, '1.0.0', requestScope)
    await submitManagedSkillPromotion(SKILL_ID, '1.0.0', 'organization', requestScope)
    await approveManagedSkillPromotion(SKILL_ID, '1.0.0', requestScope)
    await rejectManagedSkillPromotion(SKILL_ID, '1.0.0', 'needs work', requestScope)
    await takedownManagedSkill(SKILL_ID, 'organization', requestScope)
    await expect(
      transitionManagedSkillLifecycle(SKILL_ID, 'submit-review', requestScope),
    ).resolves.toEqual({
      skill_id: SKILL_ID,
      from_status: 'draft',
      to_status: 'pending_review',
    })
    await expect(deleteManagedSkillVersion(SKILL_ID, '1.0.0', true, requestScope)).resolves.toEqual(
      { type: SKILL_VERSION_DELETED_TYPE },
    )

    expect(managedPost).toHaveBeenNthCalledWith(
      1,
      `/skills/${SKILL_ID}/versions`,
      { release_notes: '' },
      expect.objectContaining({ skipManagedContext: true }),
    )
    expect(managedPost).toHaveBeenNthCalledWith(
      2,
      `/skills/${SKILL_ID}/versions/restore/1.0.0`,
      {},
      expect.objectContaining({ skipManagedContext: true }),
    )
    expect(managedPost).toHaveBeenNthCalledWith(
      3,
      `/skills/${SKILL_ID}/versions/1.0.0/submit-promotion`,
      { target_tier: 'organization' },
      expect.objectContaining({ skipManagedContext: true }),
    )
    expect(managedPost).toHaveBeenNthCalledWith(
      5,
      `/skills/${SKILL_ID}/versions/1.0.0/reject-promotion`,
      { reason: 'needs work' },
      expect.objectContaining({ skipManagedContext: true }),
    )
    expect(managedPost).toHaveBeenNthCalledWith(
      7,
      `/skills/${SKILL_ID}/submit-review`,
      {},
      expect.objectContaining({ skipManagedContext: true }),
    )
    expect(managedDelete).toHaveBeenCalledWith(
      `/skills/${SKILL_ID}/versions/1.0.0?force=true`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('owns latest scan and AI authoring draft transport', async () => {
    vi.mocked(managedGet).mockResolvedValue(rawSecurityScan(SKILL_SECURITY_SCAN_ID))
    vi.mocked(managedPost).mockResolvedValue({ skill_id: SKILL_ID, created: true })

    await expect(fetchManagedLatestSkillSecurityScan(SKILL_ID, requestScope)).resolves.toEqual(
      expect.objectContaining({ id: SKILL_SECURITY_SCAN_ID }),
    )
    await expect(
      saveManagedSkillAuthoringDraft(
        {
          draft_skill_id: null,
          name: 'primary',
          description: '',
          content: '# Primary',
          tags: [],
          files: [],
        },
        requestScope,
      ),
    ).resolves.toEqual({ skill_id: SKILL_ID, created: true })
    expect(managedGet).toHaveBeenCalledWith(
      `/skills/${SKILL_ID}/security-scans/latest`,
      expect.objectContaining({ skipManagedContext: true }),
    )
    expect(managedPost).toHaveBeenCalledWith(
      'skills/ai-authoring/save-draft',
      expect.objectContaining({ draft_skill_id: null, name: 'primary' }),
      expect.objectContaining({ skipManagedContext: true }),
    )
  })
})
