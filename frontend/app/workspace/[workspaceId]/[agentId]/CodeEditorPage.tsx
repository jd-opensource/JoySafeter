'use client'

import { useRef } from 'react'
import { CodeEditor, type CodeEditorHandle } from './components/CodeEditor'
import { CodeEditorToolbar } from './components/CodeEditorToolbar'
import { ExecutionPanelNew } from './components/execution/ExecutionPanelNew'
import { useExecutionStore } from './stores/execution/executionStore'

interface Props {
  graphId: string
  workspaceId: string
}

export function CodeEditorPage({ graphId, workspaceId }: Props) {
  const editorRef = useRef<CodeEditorHandle>(null)
  const showPanel = useExecutionStore((s) => s.showPanel)

  return (
    <div className="flex h-full flex-col">
      <CodeEditorToolbar graphId={graphId} workspaceId={workspaceId} />

      <div className="flex-1 overflow-hidden">
        <CodeEditor ref={editorRef} />
      </div>

      {showPanel && <ExecutionPanelNew />}
    </div>
  )
}
