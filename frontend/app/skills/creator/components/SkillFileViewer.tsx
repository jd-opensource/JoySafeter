'use client'

import { Copy, Check } from 'lucide-react'
import React, { useState, useCallback } from 'react'
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

const SkillFileViewer: React.FC<SkillFileViewerProps> = ({ file }) => {
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
      <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">
        Select a file to view its content
      </div>
    )
  }

  const language = getLanguageFromPath(file.path)

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-100 bg-gray-50/50 flex-shrink-0">
        <span className="text-xs font-medium text-gray-600 truncate">{file.path}</span>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-gray-400">
            {file.size > 1024 ? `${(file.size / 1024).toFixed(1)}KB` : `${file.size}B`}
          </span>
          <button
            onClick={handleCopy}
            className="p-1 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-colors"
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

export default SkillFileViewer
