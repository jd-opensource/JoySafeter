'use client'

import { X, Copy, Check, FileJson, Code, Loader2 } from 'lucide-react'
import { useState, useEffect } from 'react'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { cn } from '@/lib/utils'

import { schemaService, type GraphSchema } from '../services/schemaService'

interface SchemaExportPanelProps {
  graphId: string
  open: boolean
  onClose: () => void
}

export function SchemaExportPanel({ graphId, open, onClose }: SchemaExportPanelProps) {
  const [activeTab, setActiveTab] = useState<'json' | 'code'>('json')
  const [schema, setSchema] = useState<GraphSchema | null>(null)
  const [code, setCode] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!open || !graphId) return

    const fetchData = async () => {
      setLoading(true)
      setError(null)
      try {
        const [schemaResult, codeResult] = await Promise.all([
          schemaService.getSchema(graphId),
          schemaService.getSchemaCode(graphId),
        ])
        setSchema(schemaResult)
        setCode(typeof codeResult === 'string' ? codeResult : JSON.stringify(codeResult))
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load schema')
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [open, graphId])

  const handleCopy = async () => {
    const content = activeTab === 'json' ? JSON.stringify(schema, null, 2) : code
    await navigator.clipboard.writeText(content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const tabs = [
    { id: 'json' as const, label: 'JSON Schema', icon: FileJson },
    { id: 'code' as const, label: 'Python Code', icon: Code },
  ]

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent
        hideCloseButton
        className="flex max-h-[85vh] flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface-elevated)] p-0 shadow-2xl sm:max-w-[600px]"
      >
        <DialogHeader className="flex shrink-0 flex-row items-center justify-between border-b border-[var(--border-muted)] px-4 py-3.5">
          <div className="flex items-center gap-3 overflow-hidden text-[var(--text-primary)]">
            <div className="shrink-0 rounded-lg border border-[var(--border-muted)] bg-indigo-50 p-1.5 text-indigo-600 shadow-sm">
              <FileJson size={14} />
            </div>
            <div className="flex min-w-0 flex-col">
              <DialogTitle className="truncate text-sm font-bold leading-tight">
                Schema Export
              </DialogTitle>
              <span className="text-[9px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
                Graph Definition
              </span>
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            className="h-7 w-7 shrink-0 text-[var(--text-subtle)] hover:bg-[var(--surface-3)] hover:text-[var(--text-secondary)]"
          >
            <X size={16} />
          </Button>
        </DialogHeader>

        {/* Tab Bar */}
        <div className="flex gap-1 border-b border-[var(--border-muted)] px-4">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                '-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-medium transition-colors',
                activeTab === tab.id
                  ? 'border-primary text-primary'
                  : 'border-transparent text-[var(--text-muted)] hover:text-[var(--text-secondary)]',
              )}
            >
              <tab.icon size={12} />
              {tab.label}
            </button>
          ))}
          <div className="flex-1" />
          <button
            onClick={handleCopy}
            disabled={loading || !!error}
            className="flex items-center gap-1 px-2 py-1 text-[10px] font-medium text-[var(--text-muted)] transition-colors hover:text-[var(--text-secondary)] disabled:opacity-50"
          >
            {copied ? <Check size={12} className="text-green-500" /> : <Copy size={12} />}
            {copied ? 'Copied' : 'Copy'}
          </button>
        </div>

        {/* Content */}
        <div className="custom-scrollbar flex-1 overflow-y-auto p-4">
          {loading && (
            <div className="flex items-center justify-center py-12 text-[var(--text-muted)]">
              <Loader2 size={20} className="mr-2 animate-spin" />
              <span className="text-sm">Loading schema...</span>
            </div>
          )}
          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-700">
              {error}
            </div>
          )}
          {!loading && !error && (
            <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded-lg border border-[var(--border-muted)] bg-[var(--surface-2)] p-3 font-mono text-[11px] leading-relaxed text-[var(--text-secondary)]">
              {activeTab === 'json' ? JSON.stringify(schema, null, 2) : code}
            </pre>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-[var(--border-muted)] bg-[var(--surface-2)] px-4 py-2 font-mono text-[9px] text-[var(--text-muted)]">
          <span>{activeTab === 'json' ? 'JSON' : 'Python'}</span>
          <span className="flex items-center gap-1">
            {schema && (
              <>
                {schema.nodes?.length || 0} nodes · {schema.edges?.length || 0} edges
              </>
            )}
          </span>
        </div>
      </DialogContent>
    </Dialog>
  )
}
