import { describe, expect, it } from 'vitest'

import { quickstartInputPlaceholderKey } from './quickstart-input-state'

describe('quickstart input state', () => {
  it('guides users through engine selection before model configuration', () => {
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
    ).toBe('managed.quickstart.selectEngineFirst')

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
