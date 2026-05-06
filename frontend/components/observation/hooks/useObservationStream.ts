'use client'

import { useEffect, useRef } from 'react'

import { apiGet } from '@/lib/api-client'
import { getExecutionWsClient } from '@/lib/ws/executions/executionWsClient'
import type { ExecutionObservationFrame } from '@/lib/ws/executions/types'

import { useObservationData } from '../contexts/ObservationDataContext'
import { useStreamingTextStore } from '../contexts/StreamingTextContext'
import { normalizeObservation } from '../lib/normalize'

export function useObservationStream(executionId: string | null) {
  const { dispatch, setIsExecuting, loadTrace } = useObservationData()
  const streamingStore = useStreamingTextStore()
  const dispatchRef = useRef(dispatch)
  const setIsExecutingRef = useRef(setIsExecuting)
  const loadTraceRef = useRef(loadTrace)
  const storeRef = useRef(streamingStore)

  useEffect(() => {
    dispatchRef.current = dispatch
    setIsExecutingRef.current = setIsExecuting
    loadTraceRef.current = loadTrace
    storeRef.current = streamingStore
  })

  useEffect(() => {
    if (!executionId) return

    setIsExecutingRef.current(true)
    storeRef.current.reset()
    const client = getExecutionWsClient()

    client.subscribe(executionId, 0, {
      onObservation: (frame: ExecutionObservationFrame) => {
        switch (frame.event) {
          case 'span_open':
            if (frame.observation) {
              dispatchRef.current({
                type: 'INSERT_NODE',
                observation: normalizeObservation(frame.observation),
              })
            }
            break
          case 'span_update':
            if (frame.observation) {
              dispatchRef.current({
                type: 'UPDATE_NODE',
                observation: normalizeObservation(frame.observation),
                data: frame.data,
              })
            }
            break
          case 'span_close':
            if (frame.observation) {
              const obs = normalizeObservation(frame.observation)
              storeRef.current.clearText(obs.id)
              dispatchRef.current({
                type: 'CLOSE_NODE',
                observation: obs,
              })
            }
            break
          case 'streaming_text':
            if (frame.observation) {
              const id = frame.observation.id as string
              const text = frame.data?.text as string
              if (id && text) {
                storeRef.current.setText(id, text)
              }
            }
            break
          case 'trace_complete': {
            setIsExecutingRef.current(false)
            storeRef.current.reset()
            const traceId = frame.data?.trace_id as string | undefined
            if (traceId) {
              apiGet<Record<string, unknown>[]>(`/traces/${traceId}/observations`)
                .then((rawList) => {
                  const observations = rawList.map(normalizeObservation)
                  if (observations.length > 0) {
                    const traceStart = new Date(
                      Math.min(...observations.map((o) => new Date(o.startTime).getTime())),
                    )
                    loadTraceRef.current(observations, traceStart)
                  }
                })
                .catch((err) => console.error('Auto-reload after trace_complete failed:', err))
            }
            break
          }
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
