'use client'

import { useCodeEditorStore } from '../stores/codeEditorStore'
import { useExecutionStore } from '../stores/execution/executionStore'

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

  const isExecuting = useExecutionStore((s) => s.isExecuting)
  const startExecution = useExecutionStore((s) => s.startExecution)
  const stopExecution = useExecutionStore((s) => s.stopExecution)

  const handleRun = async () => {
    if (isDirty) {
      await save()
    }
    startExecution('')
  }

  return (
    <div className="flex items-center justify-between px-4 py-2 border-b bg-background shrink-0">
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
            isExecuting
              ? 'bg-red-600 hover:bg-red-700'
              : 'bg-primary hover:bg-primary/90'
          }`}
          onClick={isExecuting ? () => stopExecution() : handleRun}
          disabled={false}
        >
          {isExecuting ? 'Stop' : 'Run'}
        </button>
      </div>
    </div>
  )
}
