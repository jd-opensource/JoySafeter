'use client'

import { useState } from 'react'
import { useCodeEditorStore } from '../stores/codeEditorStore'
import { apiPost } from '@/lib/api-client'

interface Props {
  graphId: string
  workspaceId: string
}

export function CodeEditorToolbar({ graphId, workspaceId }: Props) {
  const isDirty = useCodeEditorStore((s) => s.isDirty)
  const isSaving = useCodeEditorStore((s) => s.isSaving)
  const save = useCodeEditorStore((s) => s.save)
  const graphName = useCodeEditorStore((s) => s.graphName)
  const setGraphName = useCodeEditorStore((s) => s.setGraphName)

  const [isRunning, setIsRunning] = useState(false)
  const [runResult, setRunResult] = useState<any>(null)
  const [runError, setRunError] = useState<string | null>(null)

  const handleRun = async () => {
    if (isDirty) {
      await save()
    }
    setIsRunning(true)
    setRunResult(null)
    setRunError(null)
    try {
      // apiPost auto-unwraps { data } on success, throws ApiError on failure
      const result = await apiPost<any>(`graphs/${graphId}/code/run`, { input: {} })
      // result is already the unwrapped data (e.g. { result: {...} })
      setRunResult(result?.result ?? result)
    } catch (e: any) {
      // ApiError.message contains the backend error message
      setRunError(e?.message || 'Request failed')
    } finally {
      setIsRunning(false)
    }
  }

  return (
    <div className="flex flex-col shrink-0">
      <div className="flex items-center justify-between px-4 py-2 border-b bg-background">
        {/* Left: graph name */}
        <input
          className="text-sm font-medium bg-transparent border-none outline-none min-w-0 flex-1 max-w-xs"
          value={graphName ?? ''}
          onChange={(e) => setGraphName(e.target.value)}
          placeholder="Untitled Graph"
        />

        {/* Right: actions */}
        <div className="flex items-center gap-2">
          <button
            className="px-3 py-1.5 text-sm border rounded-md hover:bg-accent disabled:opacity-50 disabled:cursor-not-allowed"
            onClick={() => save()}
            disabled={!isDirty || isSaving}
          >
            {isSaving ? 'Saving...' : 'Save'}
          </button>

          <button
            className={`px-3 py-1.5 text-sm rounded-md text-white disabled:opacity-50 disabled:cursor-not-allowed ${
              isRunning
                ? 'bg-amber-600 hover:bg-amber-700'
                : 'bg-primary hover:bg-primary/90'
            }`}
            onClick={handleRun}
            disabled={isRunning}
          >
            {isRunning ? 'Running...' : 'Run'}
          </button>
        </div>
      </div>

      {/* Run result / error panel */}
      {(runResult || runError) && (
        <div className={`border-b px-4 py-3 text-sm ${runError ? 'bg-red-50 text-red-800' : 'bg-green-50 text-green-800'}`}>
          <div className="flex items-center justify-between mb-1">
            <span className="font-medium">{runError ? 'Error' : 'Result'}</span>
            <button
              className="text-xs opacity-60 hover:opacity-100"
              onClick={() => { setRunResult(null); setRunError(null) }}
            >
              Close
            </button>
          </div>
          <pre className="whitespace-pre-wrap font-mono text-xs max-h-60 overflow-auto">
            {runError || JSON.stringify(runResult, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}
