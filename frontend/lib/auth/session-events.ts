export type SessionChangeType = 'signin' | 'logout' | 'refresh'

const SESSION_CHANGE_KEY = 'auth_session_change'
const sessionChangeListeners = new Set<(type: SessionChangeType) => void>()

export function notifySessionChange(type: SessionChangeType): void {
  if (typeof window === 'undefined') return
  sessionChangeListeners.forEach((listener) => {
    listener(type)
  })
  try {
    const event = { type, timestamp: Date.now() }
    const serializedEvent = JSON.stringify(event)
    localStorage.setItem(SESSION_CHANGE_KEY, serializedEvent)
    setTimeout(() => {
      if (localStorage.getItem(SESSION_CHANGE_KEY) === serializedEvent) {
        localStorage.removeItem(SESSION_CHANGE_KEY)
      }
    }, 100)
  } catch (e) {
    console.warn('Failed to notify session change:', e)
  }
}

export function publishRefreshCompleted(completedAtStorageKey: string): void {
  if (typeof window === 'undefined') return
  try {
    localStorage.setItem(completedAtStorageKey, String(Date.now()))
  } catch {
    /* ignore */
  }
  notifySessionChange('refresh')
}

export function onSessionChange(callback: (type: SessionChangeType) => void): () => void {
  if (typeof window === 'undefined') return () => {}
  sessionChangeListeners.add(callback)

  const handler = (e: StorageEvent) => {
    if (e.key === SESSION_CHANGE_KEY && e.newValue) {
      try {
        const event = JSON.parse(e.newValue) as Partial<{ type: SessionChangeType }>
        if (event.type) callback(event.type)
      } catch {
        /* ignore */
      }
    }
  }

  window.addEventListener('storage', handler)
  return () => {
    sessionChangeListeners.delete(callback)
    window.removeEventListener('storage', handler)
  }
}
