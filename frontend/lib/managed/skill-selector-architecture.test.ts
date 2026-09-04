import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

function readProjectFile(relativePath: string): string {
  return readFileSync(join(process.cwd(), relativePath), 'utf8')
}

describe('managed Skill list architecture', () => {
  it('keeps list transport and option catalogs behind the shared client', () => {
    const skillPage = readProjectFile('app/managed/skills/page.tsx')
    const consumers = [
      'app/managed/quickstart/page.tsx',
      'app/managed/agents/components/create-agent-dialog.tsx',
      'app/managed/agents/[agentId]/edit/page.tsx',
    ]

    expect(skillPage).toContain('useManagedSkillList()')
    expect(skillPage).not.toContain("path: '/skills'")

    for (const relativePath of consumers) {
      const source = readProjectFile(relativePath)
      expect(source).toContain('useManagedSkillOptions')
      expect(source).not.toMatch(/managedGet<[^>]*>\(\s*['"]\/skills['"]/)
      expect(source).not.toMatch(/queryKey:\s*\['skills',\s*managedScope\.key\]/)
    }

    const listHook = readProjectFile('hooks/managed/use-managed-skill-list.ts')
    const optionsHook = readProjectFile('hooks/managed/use-managed-skill-options.ts')
    const client = readProjectFile('lib/managed/skill-client.ts')
    expect(listHook).toContain('fetchPage: fetchManagedSkills')
    expect(optionsHook).toContain('fetchManagedSkillOptions(managedScope)')
    expect(client).toContain("apiCollectionPath('skills', {")
    expect(client).toContain('parseItem: parseSkillResponse')
  })

  it('keeps Skill version transport, pagination, and query identity shared', () => {
    const skillPage = readProjectFile('app/managed/skills/page.tsx')
    const versionSelect = readProjectFile('components/managed/shared/skill-version-select.tsx')
    const versionsHook = readProjectFile('hooks/managed/use-managed-skill-versions.ts')
    const client = readProjectFile('lib/managed/skill-client.ts')

    for (const source of [skillPage, versionSelect]) {
      expect(source).toContain('useManagedSkillVersions')
      expect(source).not.toContain("['versions'], { limit: 50 }")
      expect(source).not.toContain('parseSkillVersionListResponse')
      expect(source).not.toContain("['skill-versions'")
    }

    expect(versionSelect).not.toContain('managedGet')
    expect(versionSelect).not.toContain('apiResourceSubpath')
    expect(versionsHook).toContain('managedSkillVersionsQueryKey(managedScope.key, skillId)')
    expect(versionsHook).toContain('fetchManagedSkillVersionOptions(skillId!, managedScope)')
    expect(client).toContain("apiResourceSubpath('skills', skillId, ['versions'], {")
    expect(client).toContain('parseItem: parseSkillVersionResponse')
    expect(client).toContain('collectManagedCursorPages<SkillVersionRecord, SkillVersionId>')
  })

  it('keeps Skill detail subresources and security history behind the shared client', () => {
    const skillPage = readProjectFile('app/managed/skills/page.tsx')
    const client = readProjectFile('lib/managed/skill-client.ts')

    for (const owner of [
      'fetchManagedSkill(',
      'fetchManagedSkillFiles(',
      'fetchManagedSkillVersionFiles(',
      'fetchManagedSkillSecurityHistory(',
      'fetchManagedSkillRecentUsage(',
      'fetchManagedSkillTargetUsage(',
      'rescanManagedSkillSecurity(',
    ]) {
      expect(skillPage).toContain(owner)
    }
    expect(skillPage).not.toContain('parseSkillFileListResponse')
    expect(skillPage).not.toContain('parseSkillVersionFileListResponse')
    expect(skillPage).not.toContain('parseSkillSecurityScanListResponse')
    expect(skillPage).not.toContain('parseSkillUsageListResponse')
    expect(skillPage).not.toContain("['skill-files'")
    expect(skillPage).not.toContain("['skill-version-files'")
    expect(skillPage).not.toContain("['skill-security-scans'")
    expect(skillPage).not.toContain("['skill-usage'")
    expect(skillPage).not.toContain("['skill-usage-search'")
    expect(skillPage).not.toMatch(
      /\['skills',\s*(?:scopeKey|managedScope\.key|variables\.scope\.key)/,
    )
    expect(skillPage).toContain('managedSkillScopeQueryPrefix(')
    expect(client).toContain('collectManagedCursorPages<SkillSecurityScanRecord')
    expect(client).toContain("responseName: 'Skill security history pagination'")
    expect(client).toContain('{ limit: 5 }')
  })

  it('keeps stable Skill writes behind the shared client', () => {
    const consumers = [
      'app/managed/skills/page.tsx',
      'components/managed/skills/skill-lifecycle-actions.tsx',
      'hooks/managed/use-skill-authoring.ts',
    ]
    const client = readProjectFile('lib/managed/skill-client.ts')

    for (const relativePath of consumers) {
      const source = readProjectFile(relativePath)
      expect(source).not.toMatch(/managed(?:Get|Post|Put|Delete|Upload)/)
      expect(source).not.toMatch(/apiResource(?:Id|Path|Subpath)/)
      expect(source).not.toMatch(/parseSkill(?:Response|FileResponse|VersionResponse)/)
    }

    expect(readProjectFile('app/managed/skills/page.tsx')).toContain('updateManagedSkill(')
    expect(readProjectFile('components/managed/skills/skill-lifecycle-actions.tsx')).toContain(
      'transitionManagedSkillLifecycle(',
    )
    expect(readProjectFile('hooks/managed/use-skill-authoring.ts')).toContain(
      'saveManagedSkillAuthoringDraft(',
    )

    for (const owner of [
      'createManagedSkill(',
      'importManagedSkillZip(',
      'updateManagedSkill(',
      'deleteManagedSkill(',
      'createManagedSkillFile(',
      'updateManagedSkillFile(',
      'deleteManagedSkillFile(',
      'publishManagedSkillVersion(',
      'deleteManagedSkillVersion(',
      'restoreManagedSkillVersion(',
      'submitManagedSkillPromotion(',
      'approveManagedSkillPromotion(',
      'rejectManagedSkillPromotion(',
      'takedownManagedSkill(',
      'transitionManagedSkillLifecycle(',
      'fetchManagedLatestSkillSecurityScan(',
      'saveManagedSkillAuthoringDraft(',
    ]) {
      expect(client).toContain(owner)
    }
  })
})
