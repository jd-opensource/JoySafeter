import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

describe('Agent build architecture boundaries', () => {
  it('does not depend on the Visual graph builder implementation', () => {
    const buildDir = join(process.cwd(), 'components/agents/agent-build')
    const sourceFiles = collectSourceFiles(buildDir)
    const forbiddenImport = ['components', 'editors', 'graph-builder'].join('/')

    const violatingFiles = sourceFiles.filter((filePath) =>
      readFileSync(filePath, 'utf8').includes(forbiddenImport),
    )

    expect(violatingFiles).toEqual([])
  })
})

function collectSourceFiles(dirPath: string): string[] {
  return readdirSync(dirPath).flatMap((entry) => {
    const entryPath = join(dirPath, entry)
    const stat = statSync(entryPath)

    if (stat.isDirectory()) {
      return collectSourceFiles(entryPath)
    }

    return /\.(ts|tsx)$/.test(entryPath) ? [entryPath] : []
  })
}
