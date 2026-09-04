import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

function readProjectFile(relativePath: string): string {
  return readFileSync(join(process.cwd(), relativePath), 'utf8')
}

describe('managed tenant catalog architecture', () => {
  it('keeps Storage mount catalog transport and cache identity centralized', () => {
    for (const relativePath of [
      'app/managed/environments/page.tsx',
      'app/managed/environments/[envId]/page.tsx',
    ]) {
      const source = readProjectFile(relativePath)
      expect(source).toContain('useManagedStorageMountCatalog()')
      expect(source).not.toContain('/storage-volumes/catalog')
      expect(source).not.toContain("queryKey: ['storage-mount-catalog'")
    }

    const client = readProjectFile('lib/managed/storage-volume-client.ts')
    expect(client).toContain("'/storage-volumes/catalog'")
    expect(client).toContain('managedStorageMountCatalogQueryKey')
  })

  it('keeps Storage volume lifecycle and audit pagination centralized', () => {
    const page = readProjectFile('components/managed/storage-volumes/storage-volumes-page.tsx')
    const volumeHook = readProjectFile('hooks/managed/use-managed-storage-volumes.ts')
    const auditHook = readProjectFile('hooks/managed/use-managed-storage-mount-audit-list.ts')
    const client = readProjectFile('lib/managed/storage-volume-client.ts')

    expect(page).toContain('useManagedStorageVolumes(storageView)')
    expect(page).toContain('useManagedStorageMountAuditList(selectedVolume?.id ?? null)')
    expect(page).not.toMatch(/managed(Get|Post|Delete)/)
    expect(page).not.toContain('parseStorageMountAuditResponse')
    expect(page).not.toContain("queryKey: ['storage-volumes'")
    expect(volumeHook).toContain('managedStorageVolumesQueryKey(managedScope.key, view)')
    expect(auditHook).toContain('cacheVersion: volumeId ??')
    expect(auditHook).toContain('fetchManagedStorageMountAudits({ ...request, volumeId }, scope)')
    expect(client).toContain("apiCollectionPath('storage-volumes/audit/logs', {")
    expect(client).toContain('parseManagedCursorPage(response, {')
    for (const owner of [
      'createManagedStorageVolume',
      'updateManagedStorageVolume',
      'saveManagedStorageProjectGrant',
      'saveManagedStorageOrganizationGrant',
      'deleteManagedStorageProjectGrant',
      'deleteManagedStorageOrganizationGrant',
      'deleteManagedStorageVolume',
    ]) {
      expect(client).toContain(`function ${owner}`)
    }
  })

  it('keeps Project list and selector traversal centralized', () => {
    const projectPage = readProjectFile('app/managed/projects/page.tsx')
    const storagePage = readProjectFile(
      'components/managed/storage-volumes/storage-volumes-page.tsx',
    )
    const sidebar = readProjectFile('components/app-sidebar/app-sidebar.tsx')
    expect(projectPage).toContain('useManagedProjectList(showArchived)')
    expect(storagePage).toContain('useManagedProjectOptions()')
    expect(sidebar).toContain('fetchManagedOrganizationProjectOptions(organization.id)')
    expect(projectPage).not.toContain("path: '/auth/projects'")
    expect(storagePage).not.toContain("managedGet<unknown>('/auth/projects')")
    expect(sidebar).not.toContain('/auth/projects?include_archived=false&limit=200')
    expect(projectPage).not.toContain('projects-list')
    expect(storagePage).not.toContain('storage-volumes-projects')

    const client = readProjectFile('lib/managed/project-client.ts')
    expect(client).toContain("apiCollectionPath('auth/projects', {")
    expect(client).toContain('collectManagedCursorPages<ProjectSummary, ProjectId>')
  })

  it('keeps Project detail transport and query identity centralized', () => {
    for (const relativePath of [
      'components/managed/projects/project-overview-page.tsx',
      'components/managed/projects/project-lifecycle-page.tsx',
      'components/managed/projects/project-access-page.tsx',
      'components/managed/projects/project-settings-shell.tsx',
      'app/managed/api-keys/page.tsx',
    ]) {
      const source = readProjectFile(relativePath)
      expect(source).toContain('fetchManagedProject(')
      expect(source).toContain('managedProjectQueryKey(')
      expect(source).not.toMatch(/managedGet<[^>]*>\([^\n]*auth\/projects/)
      expect(source).not.toContain("queryKey: ['project'")
    }
  })

  it('keeps Organization list and platform collection transport centralized', () => {
    const settingsPage = readProjectFile('app/managed/settings/page.tsx')
    const storagePage = readProjectFile(
      'components/managed/storage-volumes/storage-volumes-page.tsx',
    )
    expect(settingsPage).toContain('useManagedOrganizationList(organizationSearch)')
    expect(storagePage).toContain('useManagedPlatformOrganizations(')
    expect(settingsPage).not.toContain('organizations-list')
    expect(storagePage).not.toContain('/auth/platform/organizations')

    const client = readProjectFile('lib/managed/organization-client.ts')
    expect(client).toContain("apiCollectionPath('organizations', {")
    expect(client).toContain("apiCollectionPath('auth/platform/organizations', {")
    expect(client).toContain('collectManagedCursorPages<PlatformOrganization, OrganizationId>')
  })

  it('keeps Organization detail and member contracts centralized', () => {
    for (const relativePath of [
      'components/managed/settings/organization-detail-shell.tsx',
      'app/managed/settings/organizations/[organizationId]/page.tsx',
      'app/managed/settings/organizations/[organizationId]/members/page.tsx',
    ]) {
      const source = readProjectFile(relativePath)
      expect(source).toContain('useManagedOrganization(')
      expect(source).not.toContain('parseOrganizationDetailResponse')
      expect(source).not.toMatch(/managedGet<[^>]*>\([^\n]*organizations\/\$\{organizationId\}/)
      expect(source).not.toMatch(/managed(Post|Put|Delete)/)
    }

    const settings = readProjectFile('app/managed/settings/page.tsx')
    const overview = readProjectFile('app/managed/settings/organizations/[organizationId]/page.tsx')
    const members = readProjectFile(
      'app/managed/settings/organizations/[organizationId]/members/page.tsx',
    )
    expect(settings).toContain('createManagedOrganization(')
    expect(settings).not.toMatch(/managedPost<[^>]*>\([^\n]*organizations/)
    expect(overview).toContain('useManagedOrganizationMemberOptions(')
    expect(overview).not.toContain('members?limit=200')
    expect(members).toContain('useManagedOrganizationMemberList(')
    expect(members).not.toContain("queryKey: 'organization-members'")
    expect(members).not.toContain('parseMemberCandidateListResponse')
    expect(members).not.toContain('parseOrganizationMemberResponse')

    const memberListHook = readProjectFile('hooks/managed/use-managed-organization-member-list.ts')
    expect(memberListHook).toContain('paginationScopeKey: organizationId')
    expect(memberListHook).toContain('requiresManagedScope: false')

    const client = readProjectFile('lib/managed/organization-client.ts')
    for (const owner of [
      'createManagedOrganization',
      'updateManagedOrganization',
      'deleteManagedOrganization',
      'transferManagedOrganizationOwnership',
      'searchManagedOrganizationMemberCandidates',
      'addManagedOrganizationMember',
      'updateManagedOrganizationMemberRole',
      'removeManagedOrganizationMember',
    ]) {
      expect(client).toContain(`function ${owner}`)
    }
  })

  it('keeps Credential list transport and selector traversal centralized', () => {
    for (const relativePath of [
      'app/managed/environments/page.tsx',
      'app/managed/environments/[envId]/page.tsx',
    ]) {
      const source = readProjectFile(relativePath)
      expect(source).toContain('useServiceCredentials()')
      expect(source).not.toContain("path: '/credentials?kind=service'")
      expect(source).not.toContain("queryKey: 'service-credentials'")
    }

    for (const relativePath of [
      'components/managed/credentials/model-connection-list.tsx',
      'components/managed/credentials/service-credential-list.tsx',
    ]) {
      const source = readProjectFile(relativePath)
      expect(source).toContain('useManagedCredentialList({')
      expect(source).not.toContain("path: '/credentials'")
      expect(source).not.toContain('parseCredentialResponse')
    }

    const serviceHook = readProjectFile('hooks/managed/use-service-credentials.ts')
    const compatibleHook = readProjectFile('hooks/managed/use-compatible-credentials.ts')
    expect(serviceHook).toContain('fetchManagedServiceCredentialOptions(scope)')
    expect(serviceHook).not.toContain("apiCollectionPath('credentials'")
    expect(compatibleHook).toContain('fetchManagedModelCredentialOptions(')
    expect(compatibleHook).not.toContain("apiCollectionPath('credentials'")

    const client = readProjectFile('lib/managed/credential-client.ts')
    expect(client).toContain("apiCollectionPath('credentials', {")
    expect(client).toContain('parseManagedCursorPage(response, {')
    expect(client).toContain('collectManagedCursorPages<Credential, CredentialId>')
    for (const owner of [
      'fetchManagedCredential',
      'createManagedCredential',
      'updateManagedCredential',
      'deleteManagedCredential',
      'setManagedCredentialDefault',
      'changeManagedCredentialLifecycle',
      'testManagedCredential',
    ]) {
      expect(client).toContain(`function ${owner}`)
    }

    for (const relativePath of [
      'components/managed/credentials/credential-detail.tsx',
      'components/managed/credentials/create-standalone-credential-dialog.tsx',
      'components/managed/credentials/model-connection-detail.tsx',
      'components/managed/credentials/model-connection-list.tsx',
      'components/managed/credentials/service-credential-detail.tsx',
      'components/managed/credentials/service-credential-list.tsx',
      'components/managed/llm/model-connection-configurator.tsx',
    ]) {
      const source = readProjectFile(relativePath)
      expect(source).not.toMatch(/managed(Get|Post|Patch|Delete)/)
      expect(source).not.toContain("apiResourcePath('credentials'")
      expect(source).not.toContain("'/credentials'")
    }
  })
})
