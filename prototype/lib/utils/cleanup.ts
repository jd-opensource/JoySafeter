/**
 * Cleanup utilities for preventing memory leaks
 *
 * Provides reusable patterns and utilities for cleaning up resources
 * like timers, event listeners, and subscriptions.
 */

import React from 'react'

/**
 * Creates a safe state updater that only updates if component is mounted
 *
 * @param isMountedRef - Ref tracking component mount status
 * @param setState - React state setter function
 * @returns Safe state updater function
 *
 * @example
 * ```tsx
 * const isMountedRef = useRef(true)
 * useEffect(() => {
 *   isMountedRef.current = true
 *   return () => { isMountedRef.current = false }
 * }, [])
 *
 * const safeSetState = createSafeStateUpdater(isMountedRef, setState)
 * safeSetState(newValue) // Only updates if component is mounted
 * ```
 */
export function createSafeStateUpdater<T>(
  isMountedRef: React.MutableRefObject<boolean>,
  setState: React.Dispatch<React.SetStateAction<T>>
): React.Dispatch<React.SetStateAction<T>> {
  return (value: React.SetStateAction<T>) => {
    if (isMountedRef.current) {
      setState(value)
    }
  }
}

/**
 * Creates a cleanup function for multiple timers
 *
 * @param timers - Array of timer IDs to track
 * @returns Cleanup function that clears all timers
 *
 * @example
 * ```tsx
 * const timersRef = useRef<NodeJS.Timeout[]>([])
 *
 * useEffect(() => {
 *   timersRef.current.push(setTimeout(() => {}, 100))
 *   timersRef.current.push(setInterval(() => {}, 1000))
 *
 *   return createTimerCleanup(timersRef.current)
 * }, [])
 * ```
 */
export function createTimerCleanup(
  timers: (NodeJS.Timeout | null)[]
): () => void {
  return () => {
    timers.forEach(timer => {
      if (timer) {
        clearTimeout(timer)
        clearInterval(timer)
      }
    })
    timers.length = 0
  }
}

/**
 * Creates a cleanup function for WebSocket connections
 *
 * @param ws - WebSocket instance
 * @returns Cleanup function that properly closes WebSocket
 *
 * @example
 * ```tsx
 * useEffect(() => {
 *   const ws = new WebSocket(url)
 *   return createWebSocketCleanup(ws)
 * }, [url])
 * ```
 */
export function createWebSocketCleanup(
  ws: WebSocket | null
): () => void {
  return () => {
    if (ws) {
      // Remove all event handlers to prevent memory leaks
      ws.onopen = null
      ws.onmessage = null
      ws.onclose = null
      ws.onerror = null

      // Close connection if still open or connecting
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close()
      }
    }
  }
}

/**
 * Creates a cleanup function for AbortController
 *
 * @param abortController - AbortController instance
 * @returns Cleanup function that aborts the controller
 *
 * @example
 * ```tsx
 * const abortRef = useRef<AbortController | null>(null)
 *
 * useEffect(() => {
 *   abortRef.current = new AbortController()
 *   return createAbortControllerCleanup(abortRef.current)
 * }, [])
 * ```
 */
export function createAbortControllerCleanup(
  abortController: AbortController | null
): () => void {
  return () => {
    if (abortController) {
      abortController.abort()
    }
  }
}

/**
 * Creates a cleanup function for event listeners
 *
 * @param target - Event target (window, document, element, etc.)
 * @param event - Event name
 * @param handler - Event handler function
 * @param options - Event listener options
 * @returns Cleanup function that removes the event listener
 *
 * @example
 * ```tsx
 * useEffect(() => {
 *   const handler = () => {}
 *   window.addEventListener('resize', handler)
 *   return createEventListenerCleanup(window, 'resize', handler)
 * }, [])
 * ```
 */
export function createEventListenerCleanup(
  target: EventTarget,
  event: string,
  handler: EventListener,
  options?: boolean | AddEventListenerOptions
): () => void {
  return () => {
    target.removeEventListener(event, handler, options)
  }
}

/**
 * Hook to track component mount status
 *
 * @returns Ref object tracking mount status
 *
 * @example
 * ```tsx
 * const isMountedRef = useIsMounted()
 *
 * useEffect(() => {
 *   fetchData().then(data => {
 *     if (isMountedRef.current) {
 *       setData(data)
 *     }
 *   })
 * }, [])
 * ```
 */
export function useIsMounted(): React.MutableRefObject<boolean> {
  const isMountedRef = React.useRef(true)

  React.useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
    }
  }, [])

  return isMountedRef
}
