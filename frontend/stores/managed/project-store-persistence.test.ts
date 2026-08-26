import { JSDOM } from 'jsdom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const ORGANIZATION_ID = 'org_018f6f42-0a51-7cc4-98c8-4f6f0ca5f020'
const PROJECT_ID = 'proj_018f6f42-0a51-7cc4-98c8-4f6f0ca5f021'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.localStorage = dom.window.localStorage

function persistContext(currentOrgId: unknown, currentProjectId: unknown, version = 0) {
  localStorage.setItem(
    'managed-project-state',
    JSON.stringify({ state: { currentOrgId, currentProjectId }, version }),
  )
}

async function loadStore() {
  const { useProjectStore } = await import('./project-store')
  await useProjectStore.persist.rehydrate()
  return useProjectStore
}

describe('managed project store persistence boundary', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.resetModules()
  })

  it('rehydrates canonical organization and project IDs', async () => {
    persistContext(ORGANIZATION_ID, PROJECT_ID)

    const store = await loadStore()

    expect(store.getState().currentOrgId).toBe(ORGANIZATION_ID)
    expect(store.getState().currentProjectId).toBe(PROJECT_ID)
  })

  it.each([
    [{}, PROJECT_ID],
    ['018f6f42-0a51-7cc4-98c8-4f6f0ca5f020', PROJECT_ID],
    [PROJECT_ID, PROJECT_ID],
  ])('drops the whole context when the organization ID is invalid', async (orgId, projectId) => {
    persistContext(orgId, projectId)

    const store = await loadStore()

    expect(store.getState().currentOrgId).toBeNull()
    expect(store.getState().currentProjectId).toBeNull()
  })

  it.each([{}, '018f6f42-0a51-7cc4-98c8-4f6f0ca5f021', ORGANIZATION_ID])(
    'keeps a valid organization but drops an invalid project ID',
    async (projectId) => {
      persistContext(ORGANIZATION_ID, projectId)

      const store = await loadStore()

      expect(store.getState().currentOrgId).toBe(ORGANIZATION_ID)
      expect(store.getState().currentProjectId).toBeNull()
    },
  )

  it('drops a project ID persisted without an organization ID', async () => {
    persistContext(null, PROJECT_ID)

    const store = await loadStore()

    expect(store.getState().currentOrgId).toBeNull()
    expect(store.getState().currentProjectId).toBeNull()
  })

  it('validates the current storage version instead of trusting it', async () => {
    persistContext(ORGANIZATION_ID, {}, 1)

    const store = await loadStore()

    expect(store.getState().currentOrgId).toBe(ORGANIZATION_ID)
    expect(store.getState().currentProjectId).toBeNull()
  })
})
