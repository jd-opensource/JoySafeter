'use client'

import { Copy, Check, FileCode, ChevronDown, ChevronRight } from 'lucide-react'
import { useState, useEffect } from 'react'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'

import { Button } from '@/components/ui/button'
import { useTranslation } from '@/lib/i18n'
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
    python: 'bg-[var(--skill-brand-100)] text-[var(--skill-brand-700)] border-[var(--skill-brand-200)]',
    typescript: 'bg-[var(--brand-100)] text-[var(--brand-700)] border-[var(--brand-200)]',
    javascript: 'bg-[var(--status-warning-bg)] text-[var(--status-warning)] border-[var(--status-warning-border)]',
    json: 'bg-[var(--brand-50)] text-[var(--brand-600)] border-[var(--brand-200)]',
    markdown: 'bg-[var(--surface-3)] text-[var(--text-secondary)] border-[var(--border)]',
    bash: 'bg-[var(--status-error-bg)] text-[var(--status-error)] border-[var(--status-error-border)]',
    shell: 'bg-[var(--status-error-bg)] text-[var(--status-error)] border-[var(--status-error-border)]',
    yaml: 'bg-[var(--status-error-bg)] text-[var(--status-error)] border-[var(--status-error-border)]',
    html: 'bg-[var(--status-warning-bg)] text-[var(--status-warning)] border-[var(--status-warning-border)]',
    css: 'bg-[var(--brand-100)] text-[var(--brand-700)] border-[var(--brand-200)]',
    sql: 'bg-[var(--brand-100)] text-[var(--brand-600)] border-[var(--brand-200)]',
  }

  const colorClass = colors[language.toLowerCase()] || 'bg-[var(--surface-3)] text-[var(--text-secondary)] border-[var(--border)]'

  return (
    <span className={cn('rounded border px-2 py-0.5 text-xs font-medium', colorClass)}>
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
  const { t } = useTranslation()
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
              aria-label={isCollapsed ? 'Expand code' : 'Collapse code'}
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
            {filename || t('chat.untitled')}
          </span>
          <LanguageBadge language={prismLanguage} />
          <span className="text-xs text-[var(--text-muted)]">{lineCount} {t('chat.lines')}</span>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={handleCopy}
          className="h-7 gap-1.5 px-2 text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]"
        >
          {copied ? (
            <>
              <Check size={12} className="text-[var(--status-success)]" />
              <span className="text-xs">{t('chat.copied')}</span>
            </>
          ) : (
            <>
              <Copy size={12} />
              <span className="text-xs">{t('chat.copy')}</span>
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
              background: '#ffffff',
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
          {lineCount > 1 && <span className="ml-2 text-[var(--text-muted)]">{t('chat.moreLines', { count: lineCount - 1 })}</span>}
        </div>
      )}
    </div>
  )
}
