import { useEffect, useRef } from 'react'
import { useCodeEditorStore } from '../stores/codeEditorStore'
import { apiPost } from '@/lib/api-client'

/**
 * Debounced parse hook — calls POST /graphs/{id}/code/parse on code change.
 * Updates the store with parse results, preview data, and errors.
 */
export function useCodeParse(graphId: string | null) {
  const code = useCodeEditorStore((s) => s.code)
  const setParseResult = useCodeEditorStore((s) => s.setParseResult)
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined)

  useEffect(() => {
    if (!graphId || !code.trim()) {
      setParseResult(null, null, [])
      return
    }

    useCodeEditorStore.setState({ isParsing: true })

    clearTimeout(timerRef.current)
    timerRef.current = setTimeout(async () => {
      try {
        const res = await apiPost<any>(`graphs/${graphId}/code/parse`, { code })
        if (res.success) {
          setParseResult(res.data.schema, res.data.preview, res.data.errors ?? [])
        }
      } catch {
        // Network error — leave previous state, clear parsing flag
        useCodeEditorStore.setState({ isParsing: false })
      }
    }, 500)

    return () => clearTimeout(timerRef.current)
  }, [code, graphId, setParseResult])
}
