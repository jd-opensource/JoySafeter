import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

describe('session page scope lifecycle', () => {
  it('reloads event history when project scope changes on the same route', () => {
    const source = readFileSync(
      join(process.cwd(), 'app/managed/sessions/[sessionId]/page.tsx'),
      'utf8',
    )

    expect(source).toContain('}, [id, loadEvents, sessionScope])')
  })
})
