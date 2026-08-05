import { describe, expect, it } from 'vitest'

import {
  dreamingButtonLabelForStatus,
  dreamingRunPollInterval,
  isDreamingRunActive,
  isDreamingRunTerminal,
} from './dreaming-run-status'

describe('dreaming run status helpers', () => {
  it('treats scheduling lifecycle statuses as active', () => {
    for (const status of ['pending', 'scheduling', 'rescheduling', 'running']) {
      expect(isDreamingRunActive(status), status).toBe(true)
      expect(dreamingRunPollInterval(status), status).toBe(2000)
      expect(dreamingButtonLabelForStatus(status, false), status).toBe('Dreaming run...')
    }
  })

  it('treats terminal statuses as finished', () => {
    for (const status of ['success', 'failed', 'dead_letter', 'crashed']) {
      expect(isDreamingRunTerminal(status), status).toBe(true)
      expect(isDreamingRunActive(status), status).toBe(false)
      expect(dreamingRunPollInterval(status), status).toBe(false)
    }
  })

  it('keeps the button in running state while the trigger mutation is pending', () => {
    expect(dreamingButtonLabelForStatus(undefined, true)).toBe('Dreaming run...')
    expect(dreamingButtonLabelForStatus('success', false)).toBe('Dreaming Complete')
    expect(dreamingButtonLabelForStatus(undefined, false)).toBe('Dreaming')
  })
})
