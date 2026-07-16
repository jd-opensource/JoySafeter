'use client'
/**
 * Reusable CodeMirror-based editor for SKILL.md and helper files.
 *
 * Extracted from ``app/managed/skills/page.tsx`` (which is the skill detail
 * page) so the AI authoring workspace can use the exact same editor with
 * the same theme + python highlighting behavior.
 */
import CodeMirror from '@uiw/react-codemirror'
import { python } from '@codemirror/lang-python'
import { vscodeDark } from '@uiw/codemirror-theme-vscode'
import { EditorView } from '@codemirror/view'
import { useTheme } from 'next-themes'

function getEditorExtensions(fileType?: string, fileName?: string) {
  const normalizedType = (fileType || '').toLowerCase()
  const normalizedName = (fileName || '').toLowerCase()
  const extensions = [EditorView.lineWrapping]

  if (normalizedType === 'python' || normalizedName.endsWith('.py')) {
    extensions.push(python())
  }

  return extensions
}

export function SkillCodeEditor({
  value,
  onChange,
  fileType,
  fileName,
  minHeight = '360px',
  height = '420px',
  readOnly = false,
}: {
  value: string
  onChange: (value: string) => void
  fileType?: string
  fileName?: string
  minHeight?: string
  height?: string
  readOnly?: boolean
}) {
  const { resolvedTheme } = useTheme()
  const editorTheme = resolvedTheme === 'dark' ? vscodeDark : 'light'

  return (
    <CodeMirror
      value={value}
      onChange={onChange}
      readOnly={readOnly}
      editable={!readOnly}
      theme={editorTheme}
      height={height}
      minHeight={minHeight}
      extensions={getEditorExtensions(fileType, fileName)}
      className="h-full overflow-hidden text-sm [&_.cm-editor]:h-full [&_.cm-scroller]:overflow-auto"
      basicSetup={{
        lineNumbers: true,
        foldGutter: true,
        bracketMatching: true,
        closeBrackets: true,
        autocompletion: true,
        highlightActiveLine: true,
        highlightActiveLineGutter: true,
        searchKeymap: true,
      }}
    />
  )
}
