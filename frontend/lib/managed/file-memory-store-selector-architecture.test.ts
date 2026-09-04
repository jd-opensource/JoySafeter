import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

function readProjectFile(relativePath: string): string {
  return readFileSync(join(process.cwd(), relativePath), 'utf8')
}

describe('managed File and Memory Store list architecture', () => {
  it('keeps File list transport and complete option catalogs behind the shared client', () => {
    const filePage = readProjectFile('app/managed/files/page.tsx')
    const consumers = [
      'app/managed/sessions/components/create-session-dialog.tsx',
      'app/managed/sessions/[sessionId]/page.tsx',
    ]

    expect(filePage).toContain('useManagedFileList()')
    expect(filePage).not.toContain("path: '/files'")

    for (const relativePath of consumers) {
      const source = readProjectFile(relativePath)
      expect(source).toContain('useManagedFileOptions')
      expect(source).not.toMatch(/managedGet<[^>]*>\(\s*['"]\/files/)
      expect(source).not.toContain('parseFileListResponse')
      expect(source).not.toContain('files-for-session')
      expect(source).not.toContain('files-for-add')
    }

    const listHook = readProjectFile('hooks/managed/use-managed-file-list.ts')
    const optionsHook = readProjectFile('hooks/managed/use-managed-file-options.ts')
    const client = readProjectFile('lib/managed/file-client.ts')
    expect(listHook).toContain('fetchPage: fetchManagedFiles')
    expect(optionsHook).toContain('fetchManagedFileOptions(managedScope)')
    expect(client).toContain("apiCollectionPath('files', {")
    expect(client).toContain('parseItem: parseFileResponse')
  })

  it('keeps Memory Store list transport and active options behind the shared client', () => {
    const memoryStorePage = readProjectFile('app/managed/memory-stores/page.tsx')
    const createDialog = readProjectFile(
      'app/managed/sessions/components/create-session-dialog.tsx',
    )

    expect(memoryStorePage).toContain('useManagedMemoryStoreList(showArchived)')
    expect(memoryStorePage).not.toContain("path: '/memory_stores'")
    expect(createDialog).toContain('useManagedMemoryStoreOptions')
    expect(createDialog).not.toMatch(/managedGet<[^>]*>\(\s*['"]\/memory_stores/)
    expect(createDialog).not.toContain('parseMemoryStoreResponse')
    expect(createDialog).not.toContain('memory-stores-for-session')

    const listHook = readProjectFile('hooks/managed/use-managed-memory-store-list.ts')
    const optionsHook = readProjectFile('hooks/managed/use-managed-memory-store-options.ts')
    const client = readProjectFile('lib/managed/memory-store-client.ts')
    expect(listHook).toContain('fetchPage: fetchManagedMemoryStores')
    expect(optionsHook).toContain('fetchManagedMemoryStoreOptions(managedScope)')
    expect(client).toContain("apiCollectionPath('memory_stores', {")
    expect(client).toContain('parseItem: parseMemoryStoreResponse')
  })

  it('keeps complete Memory directory traversal behind the shared client', () => {
    const detailPage = readProjectFile('app/managed/memory-stores/[storeId]/page.tsx')
    const directoryHook = readProjectFile('hooks/managed/use-managed-memory-directory.ts')
    const client = readProjectFile('lib/managed/memory-store-client.ts')

    expect(detailPage).toContain('useManagedMemoryDirectory(storeId)')
    expect(detailPage).toContain('managedMemoryDirectoryQueryKey(')
    expect(detailPage).not.toContain('parseMemoryListResponse')
    expect(detailPage).not.toContain("['memory-store-memories'")
    expect(detailPage).not.toContain("['memories'], {")
    expect(directoryHook).toContain('fetchManagedMemoryDirectory(storeId!, managedScope)')
    expect(client).toContain("apiResourceSubpath('memory_stores', storeId, ['memories'], {")
    expect(client).toContain('parseItem: parseMemoryResponse')
    expect(client).toContain('collectManagedCursorPages<MemoryRecord, MemoryId>')
  })
})
