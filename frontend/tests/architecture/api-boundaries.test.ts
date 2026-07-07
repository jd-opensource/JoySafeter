import fs from 'fs'
import path from 'path'

import { describe, expect, it } from 'vitest'

const SOURCE_ROOTS = ['app', 'components', 'hooks', 'lib']
const ALLOWED_RAW_FETCH_FILES = new Set([
  path.join('lib', 'api-client.ts'),
  path.join('lib', 'managed', 'sse.ts'),
])
const SOURCE_EXTENSIONS = new Set(['.ts', '.tsx'])

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
    if (SOURCE_EXTENSIONS.has(path.extname(entry.name)) && !entry.name.endsWith('.test.ts')) {
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
})
