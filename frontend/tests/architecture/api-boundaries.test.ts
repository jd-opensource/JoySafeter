import fs from 'fs'
import path from 'path'

import { describe, expect, it } from 'vitest'

const SOURCE_ROOTS = ['app', 'components', 'hooks', 'lib']
const ALLOWED_RAW_FETCH_FILES = new Set([
  path.join('lib', 'api-client.ts'),
  path.join('lib', 'managed', 'sse.ts'),
])
const ALLOWED_ID_NORMALIZATION_FILES = new Set([
  path.join('lib', 'managed', 'api-paths.ts'),
  path.join('lib', 'managed', 'id.ts'),
])
const SOURCE_EXTENSIONS = new Set(['.ts', '.tsx'])
const RESOURCE_MEMBER_PATH_RE =
  /\bmanaged(?:Get|Post|Patch|Put|Delete)\s*\(\s*`[^`]*(?:sessions|agents|environments|vaults|memory_stores|schedules|secrets|skills)\/\$\{/s
const STRIP_PREFIX_IN_REQUEST_RE =
  /\bmanaged(?:Get|Post|Patch|Put|Delete)\s*\(\s*`[^`]*\$\{\s*stripIdPrefix/s
const HAND_ROLLED_PREFIX_RE = /replace\([^)]*memstore_/

function walk(dir: string): string[] {
  const entries = fs.readdirSync(dir, { withFileTypes: true })
  const files: string[] = []
  for (const entry of entries) {
    if (entry.name === 'node_modules' || entry.name.startsWith('.')) continue
    const fullPath = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      files.push(...walk(fullPath))
      continue
    }
    if (
      SOURCE_EXTENSIONS.has(path.extname(entry.name)) &&
      !entry.name.endsWith('.test.ts') &&
      !entry.name.endsWith('.test.tsx')
    ) {
      files.push(fullPath)
    }
  }
  return files
}

describe('managed API boundaries', () => {
  it('keeps raw fetch inside the low-level API clients', () => {
    const root = process.cwd()
    const offenders = SOURCE_ROOTS.flatMap((sourceRoot) => walk(path.join(root, sourceRoot)))
      .map((file) => path.relative(root, file))
      .filter((file) => !ALLOWED_RAW_FETCH_FILES.has(file))
      .filter((file) => /\bfetch\s*\(/.test(fs.readFileSync(path.join(root, file), 'utf8')))

    expect(offenders).toEqual([])
  })

  it('keeps managed resource id normalization inside API path helpers', () => {
    const root = process.cwd()
    const offenders = SOURCE_ROOTS.flatMap((sourceRoot) => walk(path.join(root, sourceRoot)))
      .map((file) => path.relative(root, file))
      .filter((file) => !ALLOWED_ID_NORMALIZATION_FILES.has(file))
      .filter((file) => {
        const content = fs.readFileSync(path.join(root, file), 'utf8')
        return (
          RESOURCE_MEMBER_PATH_RE.test(content) ||
          STRIP_PREFIX_IN_REQUEST_RE.test(content) ||
          HAND_ROLLED_PREFIX_RE.test(content)
        )
      })

    expect(offenders).toEqual([])
  })

  it('keeps organization management actions scoped to each organization role', () => {
    const root = process.cwd()
    const settingsPage = fs.readFileSync(
      path.join(root, 'app', 'managed', 'settings', 'page.tsx'),
      'utf8',
    )

    expect(settingsPage).not.toContain('useUserPermissionsContext')
    expect(settingsPage).not.toContain('canManageOrganizations')
    expect(settingsPage).toContain('canAdmin(org.role)')
    expect(settingsPage).toContain('canOwn(org.role)')
  })
})
