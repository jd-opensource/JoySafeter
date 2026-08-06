import { JSDOM } from 'jsdom'
import { afterEach, beforeAll, describe, expect, it } from 'vitest'

import type { OrgInfo, ProjectInfo } from './project-store'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.localStorage = dom.window.localStorage

let useProjectStore: typeof import('./project-store').useProjectStore
let currentProjectAllowsWrite: typeof import('@/hooks/managed/use-current-project-read-only').currentProjectAllowsWrite

const orgs: OrgInfo[] = [
  { id: 'org-a', name: 'Org A', slug: 'org-a', role: 'owner' },
  { id: 'org-b', name: 'Org B', slug: 'org-b', role: 'owner' },
]

const projectA: ProjectInfo = {
  id: 'project-a',
  org_id: 'org-a',
  name: 'Project A',
  slug: 'project-a',
  is_default: true,
  capability: 'write',
}

describe('managed project store context semantics', () => {
  beforeAll(async () => {
    const storeModule = await import('./project-store')
    const readOnlyModule = await import('@/hooks/managed/use-current-project-read-only')
    useProjectStore = storeModule.useProjectStore
    currentProjectAllowsWrite = readOnlyModule.currentProjectAllowsWrite
  })

  afterEach(() => {
    useProjectStore.getState().clearContext()
    localStorage.clear()
  })

  it('clears stale project identity and metadata when switching to a different organization without a resolved project', () => {
    useProjectStore.getState().setContext('org-a', projectA.id, orgs, [projectA], projectA)

    useProjectStore.getState().setCurrentOrg('org-b')

    expect(useProjectStore.getState().currentOrgId).toBe('org-b')
    expect(useProjectStore.getState().currentProjectId).toBeNull()
    expect(useProjectStore.getState().currentProject).toBeNull()
    expect(useProjectStore.getState().projects).toEqual([])
  })

  it('keeps current project metadata when setting the same organization again', () => {
    useProjectStore.getState().setContext('org-a', projectA.id, orgs, [projectA], projectA)

    useProjectStore.getState().setCurrentOrg('org-a')

    expect(useProjectStore.getState().currentProjectId).toBe(projectA.id)
    expect(useProjectStore.getState().currentProject?.name).toBe('Project A')
    expect(useProjectStore.getState().projects).toEqual([projectA])
  })

  it('does not allow project-scoped writes until current project metadata is resolved active', () => {
    useProjectStore.setState({
      currentOrgId: 'org-a',
      currentProjectId: 'project-a',
      currentProject: null,
      organizations: orgs,
      projects: [],
    })

    expect(currentProjectAllowsWrite()).toBe(false)

    useProjectStore.setState({
      currentProject: {
        ...projectA,
        archived_at: '2026-01-02T00:00:00Z',
      },
      projects: [
        {
          ...projectA,
          archived_at: '2026-01-02T00:00:00Z',
        },
      ],
    })

    expect(currentProjectAllowsWrite()).toBe(false)

    useProjectStore.setState({
      currentProject: { ...projectA, capability: undefined },
      projects: [{ ...projectA, capability: undefined }],
    })

    expect(currentProjectAllowsWrite()).toBe(false)

    useProjectStore.setState({
      currentProject: projectA,
      projects: [projectA],
    })

    expect(currentProjectAllowsWrite()).toBe(true)
  })
})
