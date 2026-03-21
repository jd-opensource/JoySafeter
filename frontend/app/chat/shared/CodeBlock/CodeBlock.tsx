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
  background: '#f9fafb',
  border: '1px solid #e5e7eb',
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
        className="absolute right-2 top-2 z-10 rounded-md border border-gray-200 bg-white p-1.5 text-gray-400 opacity-0 transition-all hover:bg-gray-50 hover:text-gray-600 group-hover/code:opacity-100"
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
