'use client'

import { forwardRef, useCallback, useImperativeHandle, useMemo, useRef } from 'react'
import CodeMirror, { type ReactCodeMirrorRef } from '@uiw/react-codemirror'
import { python } from '@codemirror/lang-python'
import { vscodeDark } from '@uiw/codemirror-theme-vscode'
import { keymap } from '@codemirror/view'
import { linter, type Diagnostic } from '@codemirror/lint'
import { useCodeEditorStore } from '../stores/codeEditorStore'

export interface CodeEditorHandle {
  revealLine: (line: number) => void
}

export const CodeEditor = forwardRef<CodeEditorHandle>(function CodeEditor(_, ref) {
  const code = useCodeEditorStore((s) => s.code)
  const setCode = useCodeEditorStore((s) => s.setCode)
  const parseErrors = useCodeEditorStore((s) => s.parseErrors)
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

  // Inline diagnostics from parse errors
  const errorLinter = useMemo(
    () =>
      linter(() => {
        const errors = useCodeEditorStore.getState().parseErrors
        const view = cmRef.current?.view
        if (!view) return []

        const doc = view.state.doc
        const diagnostics: Diagnostic[] = []

        for (const e of errors) {
          const lineNum = Math.min(Math.max(e.line ?? 1, 1), doc.lines)
          const lineInfo = doc.line(lineNum)
          diagnostics.push({
            from: lineInfo.from,
            to: lineInfo.to,
            severity: e.severity === 'warning' ? 'warning' : 'error',
            message: e.message,
          })
        }
        return diagnostics
      }),
    [],
  )

  const extensions = useMemo(() => [python(), saveKeymap, errorLinter], [saveKeymap, errorLinter])

  const handleChange = useCallback(
    (value: string) => {
      setCode(value)
    },
    [setCode],
  )

  return (
    <CodeMirror
      ref={cmRef}
      value={code}
      onChange={handleChange}
      extensions={extensions}
      theme={vscodeDark}
      basicSetup={{
        lineNumbers: true,
        foldGutter: true,
        highlightActiveLine: true,
        autocompletion: false,
        tabSize: 4,
      }}
      style={{ height: '100%', overflow: 'auto' }}
    />
  )
})
