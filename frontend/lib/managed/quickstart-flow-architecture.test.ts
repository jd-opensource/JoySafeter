import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

function readProjectFile(relativePath: string): string {
  return readFileSync(join(process.cwd(), relativePath), 'utf8')
}

describe('Quickstart flow architecture', () => {
  it('keeps production step control on QUICKSTART_STEP constants', () => {
    const sources = [
      'app/managed/quickstart/page.tsx',
      'hooks/managed/use-quickstart-controller.ts',
      'lib/managed/quickstart-input-state.ts',
    ].map(readProjectFile)
    const forbiddenPatterns = [
      /stepOverride:\s*[1-6]/,
      /goToStep\([1-6]/,
      /reopenStep\([1-6]/,
      /currentStep\s*(?:===|!==|>=|<=|>|<)\s*[1-6]/,
      /completedSteps\.has\([1-6]\)/,
    ]

    for (const source of sources) {
      for (const pattern of forbiddenPatterns) {
        expect(source).not.toMatch(pattern)
      }
    }
  })

  it('uses secure and security-plan vocabulary without legacy phase aliases', () => {
    const quickstartSources = [
      'app/managed/quickstart/page.tsx',
      'app/managed/quickstart/components/quickstart-prove-phase.tsx',
      'hooks/managed/use-quickstart-controller.ts',
      'lib/managed/quickstart-recommendation-contract.ts',
      'lib/i18n/locales/en.ts',
      'lib/i18n/locales/zh.ts',
    ].map(readProjectFile)

    for (const source of quickstartSources) {
      expect(source).not.toContain('safetyPlan')
      expect(source).not.toMatch(/QuickstartProtect|QuickstartProtection|protection_plan/)
    }
    expect(
      existsSync(
        join(process.cwd(), 'app/managed/quickstart/components/quickstart-protect-phase.tsx'),
      ),
    ).toBe(false)
    expect(existsSync(join(process.cwd(), 'hooks/managed/use-quickstart-protection-flow.ts'))).toBe(
      false,
    )
  })

  it('keeps trial task transport out of the page component', () => {
    const page = readProjectFile('app/managed/quickstart/page.tsx')
    const client = readProjectFile('lib/managed/quickstart-task-client.ts')

    expect(page).not.toContain('managedGet')
    expect(page).not.toContain('/tasks?session_id=')
    expect(client).toContain("apiCollectionPath('tasks'")
    expect(client).toContain('parseQuickstartTaskPage')
  })
})
