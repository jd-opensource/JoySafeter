import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useSaveStore } from '../saveStore'

describe('saveStore', () => {
  beforeEach(() => {
    useSaveStore.setState(useSaveStore.getInitialState())
  })

  it('initializes with idle save status', () => {
    const s = useSaveStore.getState()
    expect(s.isSaving).toBe(false)
    expect(s.lastAutoSaveTime).toBeNull()
    expect(s.saveRetryCount).toBe(0)
  })

  it('tracks save errors', () => {
    useSaveStore.setState({ lastSaveError: 'network error', saveRetryCount: 1 })
    expect(useSaveStore.getState().lastSaveError).toBe('network error')
  })
})
