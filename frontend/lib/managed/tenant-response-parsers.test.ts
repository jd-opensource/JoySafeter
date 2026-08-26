import { describe, expect, it } from 'vitest'

import { ORGANIZATION_ID, PROJECT_ID, USER_ID } from '@/test-utils/entity-ids'

import {
  parseAuthContextResponse,
  parseMemberCandidateResponse,
  parseMemberCandidateListResponse,
  parseOrganizationDetailResponse,
  parseOrganizationMemberPageResponse,
  parsePlatformOrganizationPageResponse,
  parseOrganizationMemberResponse,
  parsePlatformUserResponse,
  parseProjectAccessRecordResponse,
  parseProjectSummaryResponse,
  parseSwitchContextResponse,
} from './tenant-response-parsers'

const ORGANIZATION_MEMBER_ID = 'orgmem_018f6f42-0a51-7cc4-98c8-4f6f0ca5f022'

const organization = {
  id: ORGANIZATION_ID,
  name: 'Org',
  slug: 'org',
  role: 'admin',
}

const project = {
  id: PROJECT_ID,
  org_id: ORGANIZATION_ID,
  name: 'Project',
  slug: 'project',
  is_default: true,
}

describe('tenant response parsers', () => {
  it('parses canonical auth context IDs', () => {
    const parsed = parseAuthContextResponse({
      user: { id: USER_ID, email: 'user@example.com', name: 'User' },
      organization,
      project,
      organizations: [organization],
      projects: [project],
    })

    expect(parsed.user.id).toBe(USER_ID)
    expect(parsed.organization.id).toBe(ORGANIZATION_ID)
    expect(parsed.project.id).toBe(PROJECT_ID)
  })

  it('rejects bare and cross-entity tenant IDs', () => {
    expect(() =>
      parseAuthContextResponse({
        user: { id: {}, email: 'user@example.com', name: 'User' },
        organization,
        project,
        organizations: [organization],
        projects: [project],
      }),
    ).toThrow(TypeError)

    expect(() =>
      parseAuthContextResponse({
        user: { id: PROJECT_ID, email: 'user@example.com', name: 'User' },
        organization,
        project,
        organizations: [organization],
        projects: [project],
      }),
    ).toThrow(TypeError)

    expect(() =>
      parseSwitchContextResponse({
        org_id: ORGANIZATION_ID,
        project_id: '018f6f42-0a51-7cc4-98c8-4f6f0ca5f021',
        project,
        projects: [project],
      }),
    ).toThrow(TypeError)
  })

  it('parses canonical tenant management DTO IDs', () => {
    expect(
      parseProjectSummaryResponse({
        id: PROJECT_ID,
        org_id: ORGANIZATION_ID,
        name: 'Project',
        slug: 'project',
        is_default: false,
      }),
    ).toMatchObject({ id: PROJECT_ID, org_id: ORGANIZATION_ID })
    expect(
      parseOrganizationDetailResponse({
        id: ORGANIZATION_ID,
        name: 'Org',
        slug: 'org',
        role: 'admin',
        project_creation_policy: 'admins_only',
      }),
    ).toMatchObject({ id: ORGANIZATION_ID })
    expect(
      parseOrganizationMemberResponse({
        id: ORGANIZATION_MEMBER_ID,
        user_id: USER_ID,
        organization_id: ORGANIZATION_ID,
        role: 'member',
      }),
    ).toMatchObject({
      id: ORGANIZATION_MEMBER_ID,
      user_id: USER_ID,
      organization_id: ORGANIZATION_ID,
    })
    expect(
      parseProjectAccessRecordResponse({
        id: ORGANIZATION_MEMBER_ID,
        user_id: USER_ID,
        email: 'user@example.com',
        display_name: 'User',
        org_role: 'member',
        access: 'explicit',
      }),
    ).toMatchObject({ id: ORGANIZATION_MEMBER_ID, user_id: USER_ID })
    expect(
      parseMemberCandidateResponse({
        id: USER_ID,
        email: 'user@example.com',
        name: 'User',
        already_member: false,
      }),
    ).toMatchObject({ id: USER_ID })
    expect(
      parseOrganizationMemberPageResponse({
        data: [
          {
            id: ORGANIZATION_MEMBER_ID,
            user_id: USER_ID,
            organization_id: ORGANIZATION_ID,
            role: 'member',
          },
        ],
        has_more: false,
        first_id: ORGANIZATION_MEMBER_ID,
        last_id: ORGANIZATION_MEMBER_ID,
      }),
    ).toMatchObject({
      data: [{ id: ORGANIZATION_MEMBER_ID }],
      first_id: ORGANIZATION_MEMBER_ID,
      last_id: ORGANIZATION_MEMBER_ID,
    })
    expect(
      parseMemberCandidateListResponse([
        {
          id: USER_ID,
          email: 'user@example.com',
          name: 'User',
          already_member: false,
        },
      ]),
    ).toMatchObject([{ id: USER_ID }])
    expect(
      parsePlatformOrganizationPageResponse({
        data: [
          {
            id: ORGANIZATION_ID,
            name: 'Org',
            slug: 'org',
            member_count: 1,
            project_count: 1,
            member_emails: ['owner@example.com'],
            created_at: '2026-08-25T00:00:00Z',
          },
        ],
      }),
    ).toMatchObject({ data: [{ id: ORGANIZATION_ID }] })
    expect(
      parsePlatformUserResponse({
        id: USER_ID,
        email: 'user@example.com',
        name: 'User',
        image: null,
        email_verified: true,
        is_active: true,
        is_super_user: false,
        created_at: '2026-08-25T00:00:00Z',
        updated_at: '2026-08-25T00:00:00Z',
      }),
    ).toMatchObject({ id: USER_ID })
  })

  it('rejects cross-entity IDs in tenant management DTOs', () => {
    expect(() =>
      parseProjectSummaryResponse({
        id: ORGANIZATION_ID,
        org_id: ORGANIZATION_ID,
        name: 'Project',
        slug: 'project',
        is_default: false,
      }),
    ).toThrow(TypeError)
    expect(() =>
      parseOrganizationMemberResponse({
        id: PROJECT_ID,
        user_id: USER_ID,
        organization_id: ORGANIZATION_ID,
        role: 'member',
      }),
    ).toThrow(TypeError)
    expect(() =>
      parseProjectAccessRecordResponse({
        user_id: PROJECT_ID,
        email: 'user@example.com',
        display_name: 'User',
        org_role: 'member',
        access: 'none',
      }),
    ).toThrow(TypeError)
    expect(() =>
      parsePlatformUserResponse({
        id: PROJECT_ID,
        email: 'user@example.com',
        name: 'User',
        email_verified: true,
        is_active: true,
        is_super_user: false,
        created_at: '2026-08-25T00:00:00Z',
        updated_at: '2026-08-25T00:00:00Z',
      }),
    ).toThrow(TypeError)
  })
})
