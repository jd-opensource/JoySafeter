import { beforeEach, describe, expect, it, vi } from 'vitest'

import { managedDelete, managedGet, managedPost, managedPut } from '@/lib/api-client'
import {
  ORGANIZATION_ID,
  OTHER_ORGANIZATION_ID,
  PROJECT_ID,
  USER_ID,
} from '@/test-utils/entity-ids'
import { parseOrganizationMemberId } from '@/types/entity-id'

import {
  addManagedOrganizationMember,
  createManagedOrganization,
  deleteManagedOrganization,
  fetchManagedOrganization,
  fetchManagedOrganizationMemberOptions,
  fetchManagedOrganizationMembers,
  fetchManagedOrganizations,
  fetchManagedPlatformOrganizationPage,
  fetchManagedPlatformOrganizations,
  managedOrganizationMemberOptionsQueryKey,
  managedOrganizationMembersQueryPrefix,
  managedOrganizationQueryKey,
  managedPlatformOrganizationsQueryKey,
  removeManagedOrganizationMember,
  searchManagedOrganizationMemberCandidates,
  transferManagedOrganizationOwnership,
  updateManagedOrganization,
  updateManagedOrganizationMemberRole,
} from './organization-client'

vi.mock('@/lib/api-client', () => ({
  managedDelete: vi.fn(),
  managedGet: vi.fn(),
  managedPost: vi.fn(),
  managedPut: vi.fn(),
}))

const requestScope = {
  orgId: ORGANIZATION_ID,
  projectId: PROJECT_ID,
  key: `${ORGANIZATION_ID}:${PROJECT_ID}`,
}
const MEMBER_ID = parseOrganizationMemberId('orgmem_018f6f42-0a51-7cc4-98c8-4f6f0ca5f120')
const OTHER_MEMBER_ID = parseOrganizationMemberId('orgmem_018f6f42-0a51-7cc4-98c8-4f6f0ca5f121')

function rawMember(id: string) {
  return {
    id,
    user_id: 'user_018f6f42-0a51-7cc4-98c8-4f6f0ca5f122',
    organization_id: ORGANIZATION_ID,
    role: 'member',
    user_name: 'Member',
    user_email: 'member@example.com',
  }
}

describe('managed Organization client', () => {
  beforeEach(() => {
    vi.mocked(managedDelete).mockReset()
    vi.mocked(managedGet).mockReset()
    vi.mocked(managedPost).mockReset()
    vi.mocked(managedPut).mockReset()
  })

  it('owns Organization lifecycle mutations and parses their responses', async () => {
    vi.mocked(managedPost)
      .mockResolvedValueOnce({
        id: ORGANIZATION_ID,
        name: 'Org',
        slug: 'org',
        project_id: PROJECT_ID,
        project_creation_policy: 'admins_only',
      })
      .mockResolvedValueOnce({
        organization_id: ORGANIZATION_ID,
        previous_owner_user_id: USER_ID,
        previous_owner_role: 'admin',
        new_owner_user_id: USER_ID,
        new_owner_role: 'owner',
      })
    vi.mocked(managedPut).mockResolvedValue({
      id: ORGANIZATION_ID,
      name: 'Renamed Org',
      slug: 'org',
      project_creation_policy: 'all_members',
    })
    vi.mocked(managedDelete).mockResolvedValue(undefined)

    await expect(createManagedOrganization({ name: 'Org' })).resolves.toMatchObject({
      id: ORGANIZATION_ID,
      project_id: PROJECT_ID,
    })
    expect(managedPost).toHaveBeenNthCalledWith(1, '/organizations', { name: 'Org' })

    await expect(
      updateManagedOrganization(ORGANIZATION_ID, {
        name: 'Renamed Org',
        projectCreationPolicy: 'all_members',
      }),
    ).resolves.toMatchObject({ id: ORGANIZATION_ID, project_creation_policy: 'all_members' })
    expect(managedPut).toHaveBeenCalledWith(`/organizations/${ORGANIZATION_ID}`, {
      name: 'Renamed Org',
      project_creation_policy: 'all_members',
    })

    await expect(
      transferManagedOrganizationOwnership(ORGANIZATION_ID, USER_ID),
    ).resolves.toMatchObject({ organization_id: ORGANIZATION_ID, new_owner_user_id: USER_ID })
    expect(managedPost).toHaveBeenNthCalledWith(
      2,
      `/organizations/${ORGANIZATION_ID}/transfer-ownership`,
      { new_owner_user_id: USER_ID },
    )

    await expect(deleteManagedOrganization(ORGANIZATION_ID)).resolves.toBeUndefined()
    expect(managedDelete).toHaveBeenCalledWith(`/organizations/${ORGANIZATION_ID}`)
  })

  it('owns searched Organization pagination', async () => {
    vi.mocked(managedGet).mockResolvedValue({
      data: [{ id: ORGANIZATION_ID, name: 'Org', slug: 'org', role: 'owner' }],
      has_more: false,
      first_id: ORGANIZATION_ID,
      last_id: ORGANIZATION_ID,
    })

    await expect(
      fetchManagedOrganizations(
        { limit: 50, afterId: OTHER_ORGANIZATION_ID, search: 'owner' },
        requestScope,
      ),
    ).resolves.toEqual({
      items: [expect.objectContaining({ id: ORGANIZATION_ID })],
      hasMore: false,
      firstId: ORGANIZATION_ID,
      lastId: ORGANIZATION_ID,
    })
    expect(managedGet).toHaveBeenCalledWith(
      `/organizations?q=owner&limit=50&after_id=${OTHER_ORGANIZATION_ID}`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('owns Organization detail transport and identity', async () => {
    vi.mocked(managedGet).mockResolvedValue({
      id: ORGANIZATION_ID,
      name: 'Org',
      slug: 'org',
      role: 'owner',
      project_creation_policy: 'admins_only',
    })

    expect(managedOrganizationQueryKey(ORGANIZATION_ID)).toEqual([
      'organization-detail',
      ORGANIZATION_ID,
    ])
    await expect(fetchManagedOrganization(ORGANIZATION_ID)).resolves.toEqual(
      expect.objectContaining({ id: ORGANIZATION_ID, role: 'owner' }),
    )
    expect(managedGet).toHaveBeenCalledWith(`/organizations/${ORGANIZATION_ID}`)
  })

  it('owns typed member pagination and complete member options', async () => {
    vi.mocked(managedGet)
      .mockResolvedValueOnce({
        data: [rawMember(MEMBER_ID)],
        has_more: true,
        first_id: MEMBER_ID,
        last_id: MEMBER_ID,
      })
      .mockResolvedValueOnce({
        data: [rawMember(OTHER_MEMBER_ID)],
        has_more: false,
        first_id: OTHER_MEMBER_ID,
        last_id: OTHER_MEMBER_ID,
      })

    expect(managedOrganizationMemberOptionsQueryKey(ORGANIZATION_ID)).toEqual([
      'organization-members',
      ORGANIZATION_ID,
      'options',
    ])
    expect(managedOrganizationMembersQueryPrefix(ORGANIZATION_ID)).toEqual([
      'organization-members',
      ORGANIZATION_ID,
    ])
    await expect(fetchManagedOrganizationMemberOptions(ORGANIZATION_ID)).resolves.toHaveLength(2)
    expect(managedGet).toHaveBeenNthCalledWith(
      1,
      `/organizations/${ORGANIZATION_ID}/members?limit=200`,
    )
    expect(managedGet).toHaveBeenNthCalledWith(
      2,
      `/organizations/${ORGANIZATION_ID}/members?limit=200&after_id=${MEMBER_ID}`,
    )
  })

  it('owns member candidate and mutation contracts', async () => {
    vi.mocked(managedGet).mockResolvedValue([
      {
        id: USER_ID,
        email: 'member@example.com',
        name: 'Member',
        already_member: false,
      },
    ])
    vi.mocked(managedPost).mockResolvedValue(rawMember(MEMBER_ID))
    vi.mocked(managedPut).mockResolvedValue({ ...rawMember(MEMBER_ID), role: 'admin' })
    vi.mocked(managedDelete).mockResolvedValue(undefined)

    await expect(
      searchManagedOrganizationMemberCandidates(ORGANIZATION_ID, 'member@example.com', 5),
    ).resolves.toEqual([expect.objectContaining({ id: USER_ID })])
    expect(managedGet).toHaveBeenCalledWith(
      `/organizations/${ORGANIZATION_ID}/member-candidates?q=member%40example.com&limit=5`,
    )

    await expect(
      addManagedOrganizationMember(ORGANIZATION_ID, {
        email: 'member@example.com',
        role: 'member',
      }),
    ).resolves.toMatchObject({ id: MEMBER_ID, role: 'member' })
    expect(managedPost).toHaveBeenCalledWith(`/organizations/${ORGANIZATION_ID}/members`, {
      email: 'member@example.com',
      role: 'member',
    })

    await expect(
      updateManagedOrganizationMemberRole(ORGANIZATION_ID, USER_ID, 'admin'),
    ).resolves.toMatchObject({ id: MEMBER_ID, role: 'admin' })
    expect(managedPut).toHaveBeenCalledWith(
      `/organizations/${ORGANIZATION_ID}/members/${USER_ID}`,
      { role: 'admin' },
    )

    await expect(removeManagedOrganizationMember(ORGANIZATION_ID, USER_ID)).resolves.toBeUndefined()
    expect(managedDelete).toHaveBeenCalledWith(
      `/organizations/${ORGANIZATION_ID}/members/${USER_ID}`,
    )
  })

  it('rejects malformed member pages', async () => {
    vi.mocked(managedGet).mockResolvedValue({ data: [rawMember(MEMBER_ID)] })
    await expect(fetchManagedOrganizationMembers({ limit: 50 }, ORGANIZATION_ID)).rejects.toThrow(
      /Organization member list response/,
    )
  })

  it('collects the complete platform Organization catalog', async () => {
    const organization = (id: string, name: string) => ({
      id,
      name,
      slug: name.toLowerCase(),
      member_count: 1,
      project_count: 1,
      member_emails: ['owner@example.com'],
      created_at: '2026-09-03T00:00:00Z',
    })
    vi.mocked(managedGet)
      .mockResolvedValueOnce({
        data: [organization(ORGANIZATION_ID, 'Org')],
        has_more: true,
        first_id: ORGANIZATION_ID,
        last_id: ORGANIZATION_ID,
      })
      .mockResolvedValueOnce({
        data: [organization(OTHER_ORGANIZATION_ID, 'Other')],
        has_more: false,
        first_id: OTHER_ORGANIZATION_ID,
        last_id: OTHER_ORGANIZATION_ID,
      })

    expect(managedPlatformOrganizationsQueryKey()).toEqual(['platform-organizations'])
    await expect(fetchManagedPlatformOrganizations(requestScope)).resolves.toHaveLength(2)
    expect(managedGet).toHaveBeenNthCalledWith(
      1,
      '/auth/platform/organizations?limit=500',
      expect.objectContaining({ skipManagedContext: true }),
    )
    expect(managedGet).toHaveBeenNthCalledWith(
      2,
      `/auth/platform/organizations?limit=500&after_id=${ORGANIZATION_ID}`,
      expect.objectContaining({ skipManagedContext: true }),
    )
  })

  it('rejects malformed platform Organization pages', async () => {
    vi.mocked(managedGet).mockResolvedValue({ data: [] })
    await expect(
      fetchManagedPlatformOrganizationPage({ limit: 500 }, requestScope),
    ).rejects.toThrow(/Platform Organization list response/)
  })
})
