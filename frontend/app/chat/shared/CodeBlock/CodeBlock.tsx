'use client'

import { Check, Copy } from 'lucide-react'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'

import { useCopyToClipboard } from '../hooks/useCopyToClipboard'

interface CodeBlockProps {
  language: string
  code: string
}

const highlighterStyle = {
  background: 'var(--surface-1)',
  border: '1px solid var(--border)',
  borderRadius: '0.5rem',
  fontSize: '13px',
  margin: '1em 0',
}

export function CodeBlock({ language, code }: CodeBlockProps) {
  const { copied, handleCopy } = useCopyToClipboard()

  return (
    <div className="group/code relative">
      <button
        onClick={() => handleCopy(code)}
        className="absolute right-2 top-2 z-10 rounded-md border border-[var(--border)] bg-[var(--surface-elevated)] p-1.5 text-[var(--text-muted)] opacity-0 transition-all hover:bg-[var(--surface-2)] hover:text-[var(--text-secondary)] group-hover/code:opacity-100"
        aria-label="Copy code"
      >
        {copied ? <Check size={13} className="text-green-500" /> : <Copy size={13} />}
      </button>
      <SyntaxHighlighter
        style={oneLight}
        language={language}
        PreTag="div"
        customStyle={highlighterStyle}
      >
        {code}
      </SyntaxHighlighter>
    </div>
  )
}
