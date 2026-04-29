'use client'

import React, {
  createContext, useCallback, useContext, useMemo, useRef, useSyncExternalStore,
} from 'react'

interface StreamingTextStore {
  setText: (id: string, text: string) => void
  clearText: (id: string) => void
  reset: () => void
  subscribe: (id: string, listener: () => void) => () => void
  getText: (id: string) => string | undefined
}

const StreamingTextCtx = createContext<StreamingTextStore | null>(null)

export function StreamingTextProvider({ children }: { children: React.ReactNode }) {
  const textsRef = useRef<Map<string, string>>(new Map())
  const listenersRef = useRef<Map<string, Set<() => void>>>(new Map())

  const notify = useCallback((id: string) => {
    const set = listenersRef.current.get(id)
    if (!set) return
    for (const listener of set) listener()
  }, [])

  const store = useMemo<StreamingTextStore>(
    () => ({
      setText: (id, text) => {
        if (textsRef.current.get(id) === text) return
        textsRef.current.set(id, text)
        notify(id)
      },
      clearText: (id) => {
        if (!textsRef.current.has(id)) return
        textsRef.current.delete(id)
        notify(id)
      },
      reset: () => {
        const ids = [...textsRef.current.keys()]
        textsRef.current.clear()
        for (const id of ids) notify(id)
      },
      subscribe: (id, listener) => {
        let listeners = listenersRef.current.get(id)
        if (!listeners) {
          listeners = new Set()
          listenersRef.current.set(id, listeners)
        }
        listeners.add(listener)
        const captured = listeners
        return () => {
          captured.delete(listener)
          if (captured.size === 0) listenersRef.current.delete(id)
        }
      },
      getText: (id) => textsRef.current.get(id),
    }),
    [notify],
  )

  return (
    <StreamingTextCtx.Provider value={store}>
      {children}
    </StreamingTextCtx.Provider>
  )
}

export function useStreamingTextStore() {
  const ctx = useContext(StreamingTextCtx)
  if (!ctx) throw new Error('useStreamingTextStore must be used within StreamingTextProvider')
  return ctx
}

export function useStreamingText(id: string | null | undefined): string | undefined {
  const store = useStreamingTextStore()
  return useSyncExternalStore(
    useCallback(
      (listener) => (id ? store.subscribe(id, listener) : () => {}),
      [store, id],
    ),
    () => (id ? store.getText(id) : undefined),
    () => undefined,
  )
}
