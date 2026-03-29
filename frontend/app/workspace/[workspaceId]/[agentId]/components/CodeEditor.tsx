'use client'

import { forwardRef, useCallback, useImperativeHandle, useMemo, useRef } from 'react'
import CodeMirror, { type ReactCodeMirrorRef } from '@uiw/react-codemirror'
import { python } from '@codemirror/lang-python'
import { vscodeDark } from '@uiw/codemirror-theme-vscode'
import { keymap } from '@codemirror/view'
import { useCodeEditorStore } from '../stores/codeEditorStore'

export interface CodeEditorHandle {
  revealLine: (line: number) => void
}

export const CodeEditor = forwardRef<CodeEditorHandle>(function CodeEditor(_, ref) {
  const code = useCodeEditorStore((s) => s.code)
  const setCode = useCodeEditorStore((s) => s.setCode)
  const cmRef = useRef<ReactCodeMirrorRef>(null)

  useImperativeHandle(ref, () => ({
    revealLine(line: number) {
      const view = cmRef.current?.view
      if (!view) return
      const lineInfo = view.state.doc.line(Math.min(line, view.state.doc.lines))
      view.dispatch({ selection: { anchor: lineInfo.from } })
      view.focus()
      const coords = view.coordsAtPos(lineInfo.from)
      if (coords) {
        view.scrollDOM.scrollTop = coords.top - view.scrollDOM.clientHeight / 2
      }
    },
  }))

  // Cmd/Ctrl+S → save
  const saveKeymap = useMemo(
    () =>
      keymap.of([
        {
          key: 'Mod-s',
          run: () => {
            useCodeEditorStore.getState().save()
            return true
          },
        },
      ]),
    [],
  )

  const handleChange = useCallback((value: string) => setCode(value), [setCode])

  return (
    <CodeMirror
      ref={cmRef}
      value={code}
      onChange={handleChange}
      theme={vscodeDark}
      extensions={[python(), saveKeymap]}
      height="100%"
      className="h-full overflow-hidden text-sm"
      basicSetup={{
        lineNumbers: true,
        foldGutter: true,
        bracketMatching: true,
        autocompletion: true,
        highlightActiveLine: true,
      }}
    />
  )
})
