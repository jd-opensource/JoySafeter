'use client'

import { useEffect, useRef } from 'react'
import { getExecutionWsClient } from '@/lib/ws/executions/executionWsClient'
import { useObservationData } from '../contexts/ObservationDataContext'
import { normalizeObservation } from '../lib/normalize'
import type { WsObservationFrame } from '../lib/types'

export function useObservationStream(executionId: string | null) {
  const { dispatch, setIsExecuting } = useObservationData()
  const dispatchRef = useRef(dispatch)
  dispatchRef.current = dispatch
  const setIsExecutingRef = useRef(setIsExecuting)
  setIsExecutingRef.current = setIsExecuting

  useEffect(() => {
    if (!executionId) return

    setIsExecutingRef.current(true)
    const client = getExecutionWsClient()

    client.subscribe(executionId, 0, {
      onEvent: (frame) => {
        const raw = frame as unknown as Record<string, unknown>
        if (raw.channel !== 'observation') return

        const obsFrame = raw as unknown as WsObservationFrame
        const normalized = normalizeObservation(obsFrame.observation)
        switch (obsFrame.event) {
          case 'span_open':
          case 'record':
            dispatchRef.current({ type: 'INSERT_NODE', observation: normalized })
            break
          case 'span_update':
            dispatchRef.current({ type: 'UPDATE_NODE', observation: normalized })
            break
          case 'span_close':
            dispatchRef.current({ type: 'CLOSE_NODE', observation: normalized })
            break
          case 'trace_complete':
            setIsExecutingRef.current(false)
            break
        }
      },
      onCompleted: () => {
        setIsExecutingRef.current(false)
      },
      onError: (error) => {
        console.error('Observation stream error:', error)
        setIsExecutingRef.current(false)
      },
    })

    return () => {
      client.unsubscribe(executionId)
    }
  }, [executionId])
}
