'use client'

import { Copy, Check } from 'lucide-react'
import { useState, useCallback } from 'react'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'

import type { PreviewFile } from './SkillFileTree'

// ---------------------------------------------------------------------------
// Language mapping
// ---------------------------------------------------------------------------

function getLanguageFromPath(path: string): string {
  const ext = path.split('.').pop()?.toLowerCase() || ''
  const map: Record<string, string> = {
    py: 'python',
    js: 'javascript',
    jsx: 'jsx',
    ts: 'typescript',
    tsx: 'tsx',
    md: 'markdown',
    json: 'json',
    yaml: 'yaml',
    yml: 'yaml',
    sh: 'bash',
    bash: 'bash',
    html: 'html',
    css: 'css',
    scss: 'scss',
    toml: 'toml',
    xml: 'xml',
    svg: 'xml',
    txt: 'text',
  }
  return map[ext] || 'text'
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface SkillFileViewerProps {
  file: PreviewFile | null
}

export default function SkillFileViewer({ file }: SkillFileViewerProps) {
  const [copied, setCopied] = useState(false)

  const handleCopy = useCallback(async () => {
    if (!file) return
    try {
      await navigator.clipboard.writeText(file.content)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // ignore
    }
  }, [file])

  if (!file) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-gray-400">
        Select a file to view its content
      </div>
    )
  }

  const language = getLanguageFromPath(file.path)

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Header */}
      <div className="flex flex-shrink-0 items-center justify-between border-b border-gray-100 bg-gray-50/50 px-3 py-2">
        <span className="truncate text-xs font-medium text-gray-600">{file.path}</span>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-gray-400">
            {file.size > 1024 ? `${(file.size / 1024).toFixed(1)}KB` : `${file.size}B`}
          </span>
          <button
            onClick={handleCopy}
            className="rounded p-1 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600"
            title="Copy content"
          >
            {copied ? <Check size={12} className="text-green-500" /> : <Copy size={12} />}
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto">
        <SyntaxHighlighter
          language={language}
          style={oneLight}
          customStyle={{
            margin: 0,
            padding: '12px',
            fontSize: '12px',
            lineHeight: '1.5',
            background: 'transparent',
            minHeight: '100%',
          }}
          showLineNumbers
          lineNumberStyle={{ color: '#d1d5db', fontSize: '10px', minWidth: '2em' }}
        >
          {file.content}
        </SyntaxHighlighter>
      </div>
    </div>
  )
}
