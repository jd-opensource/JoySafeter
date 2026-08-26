import { describe, expect, it } from 'vitest'

import { quickstartInputPlaceholderKey } from './quickstart-input-state'

describe('quickstart input state', () => {
  it('lets users describe the target before engine selection, then guides model configuration', () => {
    expect(
      quickstartInputPlaceholderKey({
        selectedEngine: '',
        modelCredentialId: '',
        currentStep: 1,
        selectedCredentialCompatible: false,
        isSessionRunning: false,
        isStreaming: false,
        readyKey: 'managed.quickstart.describeAgent',
      }),
    ).toBe('managed.quickstart.describeAgent')

    expect(
      quickstartInputPlaceholderKey({
        selectedEngine: 'codex',
        modelCredentialId: '',
        currentStep: 2,
        selectedCredentialCompatible: false,
        isSessionRunning: false,
        isStreaming: false,
        readyKey: 'managed.quickstart.describeAgent',
      }),
    ).toBe('managed.quickstart.chooseModelConnection')
  })
})
