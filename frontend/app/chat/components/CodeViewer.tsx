'use client'

import { Copy, Check, FileCode, ChevronDown, ChevronRight } from 'lucide-react'
import { useState, useEffect } from 'react'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface CodeViewerProps {
  code: string
  language: string
  filename?: string
  className?: string
  showLineNumbers?: boolean
  collapsible?: boolean
  defaultCollapsed?: boolean
  maxHeight?: string
}

// Map file extensions to Prism language names
const languageMap: Record<string, string> = {
  py: 'python',
  python: 'python',
  js: 'javascript',
  javascript: 'javascript',
  jsx: 'jsx',
  ts: 'typescript',
  typescript: 'typescript',
  tsx: 'tsx',
  json: 'json',
  md: 'markdown',
  markdown: 'markdown',
  sh: 'bash',
  bash: 'bash',
  shell: 'bash',
  zsh: 'bash',
  yaml: 'yaml',
  yml: 'yaml',
  html: 'markup',
  css: 'css',
  scss: 'scss',
  sql: 'sql',
  xml: 'xml',
  go: 'go',
  rust: 'rust',
  java: 'java',
  c: 'c',
  cpp: 'cpp',
  text: 'text',
}

// Get Prism language from file extension or language name
const getPrismLanguage = (lang: string): string => {
  const lower = lang.toLowerCase()
  return languageMap[lower] || lower || 'text'
}

function LanguageBadge({ language }: { language: string }) {
  const colors: Record<string, string> = {
    python: 'bg-emerald-100 text-emerald-700 border-emerald-200',
    typescript: 'bg-blue-100 text-blue-700 border-blue-200',
    javascript: 'bg-yellow-100 text-yellow-700 border-yellow-200',
    json: 'bg-purple-100 text-purple-700 border-purple-200',
    markdown: 'bg-[var(--surface-3)] text-[var(--text-secondary)] border-[var(--border)]',
    bash: 'bg-red-100 text-red-700 border-red-200',
    shell: 'bg-red-100 text-red-700 border-red-200',
    yaml: 'bg-pink-100 text-pink-700 border-pink-200',
    html: 'bg-orange-100 text-orange-700 border-orange-200',
    css: 'bg-indigo-100 text-indigo-700 border-indigo-200',
    sql: 'bg-cyan-100 text-cyan-700 border-cyan-200',
  }

  const colorClass = colors[language.toLowerCase()] || 'bg-[var(--surface-3)] text-[var(--text-secondary)] border-[var(--border)]'

  return (
    <span className={cn('rounded border px-2 py-0.5 text-2xs font-medium', colorClass)}>
      {language}
    </span>
  )
}

export default function CodeViewer({
  code,
  language,
  filename,
  className,
  showLineNumbers = true,
  collapsible = false,
  defaultCollapsed = false,
  maxHeight = '400px',
}: CodeViewerProps) {
  const [copied, setCopied] = useState(false)
  const [isCollapsed, setIsCollapsed] = useState(defaultCollapsed)

  useEffect(() => {
    if (copied) {
      const timer = setTimeout(() => setCopied(false), 2000)
      return () => clearTimeout(timer)
    }
  }, [copied])

  const handleCopy = async () => {
    await navigator.clipboard.writeText(code)
    setCopied(true)
  }

  const prismLanguage = getPrismLanguage(language)
  const lines = code.split('\n')
  const lineCount = lines.length

  return (
    <div
      className={cn(
        'flex flex-col overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)]',
        className,
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[var(--border-muted)] bg-[var(--surface-2)] px-3 py-2">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          {collapsible && (
            <button
              onClick={() => setIsCollapsed(!isCollapsed)}
              className="rounded p-0.5 transition-colors hover:bg-[var(--surface-5)]"
            >
              {isCollapsed ? (
                <ChevronRight size={14} className="text-[var(--text-tertiary)]" />
              ) : (
                <ChevronDown size={14} className="text-[var(--text-tertiary)]" />
              )}
            </button>
          )}
          <FileCode size={14} className="flex-shrink-0 text-[var(--text-muted)]" />
          <span className="truncate text-xs font-medium text-[var(--text-secondary)]">
            {filename || 'untitled'}
          </span>
          <LanguageBadge language={prismLanguage} />
          <span className="text-2xs text-[var(--text-muted)]">{lineCount} lines</span>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={handleCopy}
          className="h-7 gap-1.5 px-2 text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
        >
          {copied ? (
            <>
              <Check size={12} className="text-emerald-600" />
              <span className="text-2xs">Copied</span>
            </>
          ) : (
            <>
              <Copy size={12} />
              <span className="text-2xs">Copy</span>
            </>
          )}
        </Button>
      </div>

      {/* Code Content */}
      {!isCollapsed && (
        <div className="overflow-auto" style={{ maxHeight }}>
          <SyntaxHighlighter
            language={prismLanguage}
            style={oneLight}
            showLineNumbers={showLineNumbers}
            showInlineLineNumbers={false}
            lineNumberStyle={{
              minWidth: '2.5em',
              paddingRight: '1em',
              color: 'var(--text-muted)',
              fontSize: '11px',
              textAlign: 'right',
              userSelect: 'none',
            }}
            lineNumberContainerStyle={{
              float: 'left',
              paddingRight: '1em',
            }}
            customStyle={{
              margin: 0,
              padding: '0.75rem 1rem',
              background: 'var(--white)',
              fontSize: '12px',
              lineHeight: '1.6',
              fontFamily: 'JetBrains Mono, Menlo, Monaco, Consolas, monospace',
            }}
            codeTagProps={{
              style: {
                fontFamily: 'JetBrains Mono, Menlo, Monaco, Consolas, monospace',
              },
            }}
          >
            {code}
          </SyntaxHighlighter>
        </div>
      )}

      {/* Collapsed preview */}
      {isCollapsed && (
        <div className="bg-[var(--surface-2)] px-3 py-2 text-xs text-[var(--text-tertiary)]">
          <span className="font-mono">
            {lines[0]?.slice(0, 60)}
            {lines[0]?.length > 60 ? '...' : ''}
          </span>
          {lineCount > 1 && <span className="ml-2 text-[var(--text-muted)]">+{lineCount - 1} more lines</span>}
        </div>
      )}
    </div>
  )
}
