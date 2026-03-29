'use client'

import { useRef } from 'react'
import { ReactFlowProvider } from 'reactflow'
import { CodeEditor, type CodeEditorHandle } from './components/CodeEditor'
import { CodePreviewCanvas } from './components/CodePreviewCanvas'
import { CodeErrorPanel } from './components/CodeErrorPanel'
import { CodeEditorToolbar } from './components/CodeEditorToolbar'
import { ExecutionPanelNew } from './components/execution/ExecutionPanelNew'
import { useCodeParse } from './hooks/useCodeParse'
import { useExecutionStore } from './stores/execution/executionStore'

interface Props {
  graphId: string
  workspaceId: string
}

export function CodeEditorPage({ graphId, workspaceId }: Props) {
  useCodeParse(graphId)
  const editorRef = useRef<CodeEditorHandle>(null)
  const showPanel = useExecutionStore((s) => s.showPanel)

  const handleLineClick = (line: number) => {
    editorRef.current?.revealLine(line)
  }

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <CodeEditorToolbar graphId={graphId} workspaceId={workspaceId} />

      {/* Main content: editor + preview */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left: Monaco Editor */}
        <div className="w-1/2 border-r flex flex-col min-h-0">
          <CodeEditor ref={editorRef} />
        </div>

        {/* Right: Read-only canvas preview */}
        <div className="w-1/2 min-h-0">
          <ReactFlowProvider>
            <CodePreviewCanvas />
          </ReactFlowProvider>
        </div>
      </div>

      {/* Error panel */}
      <CodeErrorPanel onLineClick={handleLineClick} />

      {/* Execution panel (collapsed by default) */}
      {showPanel && <ExecutionPanelNew />}
    </div>
  )
}
