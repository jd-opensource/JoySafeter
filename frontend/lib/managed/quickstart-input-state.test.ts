import { describe, expect, it } from 'vitest'

import { quickstartInputPlaceholderKey } from './quickstart-input-state'

describe('quickstart input state', () => {
  it('lets users describe the target before engine selection, then guides model configuration', () => {
    expect(
      quickstartInputPlaceholderKey({
        selectedEngine: '',
        secretRef: '',
        currentStep: 1,
        selectedSecretCompatible: false,
        isSessionRunning: false,
        isStreaming: false,
        readyKey: 'managed.quickstart.describeAgent',
      }),
    ).toBe('managed.quickstart.describeAgent')

    expect(
      quickstartInputPlaceholderKey({
        selectedEngine: 'codex',
        secretRef: '',
        currentStep: 2,
        selectedSecretCompatible: false,
        isSessionRunning: false,
        isStreaming: false,
        readyKey: 'managed.quickstart.describeAgent',
      }),
    ).toBe('managed.quickstart.chooseSecret')
  })
})
