'use client'

import { AnimatePresence, motion } from 'framer-motion'
import {
  Database, FileText, Layers, Clock, Plus, Search, X, AlertCircle, CheckCircle2, RefreshCw,
  SortAsc, LayoutGrid, LayoutList, Trash2, MoreHorizontal,
} from 'lucide-react'
import Link from 'next/link'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { cn } from '@/lib/core/utils/cn'
import { toastSuccess, toastError, toastInfo } from '@/lib/utils/toast'
import { datasets as initialDatasets, type Dataset } from '@/mocks/datasets'

const STATUS_CONFIG = {
  ready:    { label: 'Ready',    pill: 'text-emerald-300 bg-emerald-500/10 border border-emerald-500/20', dot: 'bg-emerald-400' },
  indexing: { label: 'Indexing', pill: 'text-sky-300 bg-sky-500/10 border border-sky-500/20 animate-pulse', dot: 'bg-sky-400 animate-pulse' },
  error:    { label: 'Error',    pill: 'text-rose-300 bg-rose-500/10 border border-rose-500/20', dot: 'bg-rose-400' },
} as const

function formatDate(ts: string): string {
  return new Date(ts).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

const EMBEDDING_MODELS = [
  'text-embedding-3-large',
  'text-embedding-3-small',
  'text-embedding-ada-002',
  'bge-large-zh-v1.5',
]

const CHUNK_STRATEGIES = ['Fixed length', 'Paragraph', 'Semantic', 'Q&A']

// ==================== Create Dataset Modal ====================

function CreateDatasetModal({ open, onClose, onCreate }: {
  open: boolean
  onClose: () => void
  onCreate: (ds: Dataset) => void
}) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [embeddingModel, setEmbeddingModel] = useState(EMBEDDING_MODELS[0])
  const [chunkStrategy, setChunkStrategy] = useState(CHUNK_STRATEGIES[0])
  const [chunkSize, setChunkSize] = useState(512)
  const [loading, setLoading] = useState(false)

  async function handleCreate() {
    if (!name.trim()) return
    setLoading(true)
    await new Promise((r) => setTimeout(r, 800))
    const ds: Dataset = {
      id: `ds-${Date.now()}`,
      name: name.trim(),
      description: description.trim() || 'No description provided.',
      documentCount: 0,
      chunkCount: 0,
      status: 'indexing',
      lastUpdated: new Date().toISOString(),
      size: '0 B',
      embeddingModel,
    }
    onCreate(ds)
    setLoading(false)
    setName('')
    setDescription('')
    onClose()
    toastSuccess(`Dataset "${ds.name}" created`)
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-50 flex items-center justify-center p-4" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
          <motion.div
            initial={{ scale: 0.95, opacity: 0, y: 12 }}
            animate={{ scale: 1, opacity: 1, y: 0 }}
            exit={{ scale: 0.95, opacity: 0, y: 8 }}
            transition={{ duration: 0.18 }}
            className="relative z-10 w-full max-w-lg rounded-2xl border border-violet-500/25 bg-[#0d0d14]/95 backdrop-blur-2xl shadow-[0_0_60px_rgba(0,0,0,0.8)]"
          >
            {/* Header */}
            <div className="flex items-center justify-between border-b border-[var(--border)] px-6 py-4">
              <h2 className="text-base font-semibold text-[var(--text-primary)]">Create Knowledge Base</h2>
              <button onClick={onClose} className="rounded-lg p-1.5 text-[var(--text-muted)] hover:bg-[var(--surface-3)]">
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* Body */}
            <div className="space-y-4 px-6 py-5">
              <div>
                <label className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]">Name *</label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Security Vulnerability Corpus"
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-subtle)] focus:border-[var(--brand-500)] focus:outline-none focus:ring-2 focus:ring-[var(--brand-500)]/20"
                />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]">Description</label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Briefly describe the content of this knowledge base..."
                  rows={3}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-subtle)] focus:border-[var(--brand-500)] focus:outline-none resize-none"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]">Embedding Model</label>
                  <select
                    value={embeddingModel}
                    onChange={(e) => setEmbeddingModel(e.target.value)}
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 text-xs text-[var(--text-primary)] focus:border-[var(--brand-500)] focus:outline-none"
                  >
                    {EMBEDDING_MODELS.map((m) => <option key={m}>{m}</option>)}
                  </select>
                </div>
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]">Chunk Strategy</label>
                  <select
                    value={chunkStrategy}
                    onChange={(e) => setChunkStrategy(e.target.value)}
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 text-xs text-[var(--text-primary)] focus:border-[var(--brand-500)] focus:outline-none"
                  >
                    {CHUNK_STRATEGIES.map((s) => <option key={s}>{s}</option>)}
                  </select>
                </div>
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]">
                  Chunk Size: <span className="text-[var(--brand-500)] font-semibold">{chunkSize} tokens</span>
                </label>
                <input type="range" min={128} max={2048} step={128} value={chunkSize} onChange={(e) => setChunkSize(Number(e.target.value))} className="w-full accent-[var(--brand-500)]" />
                <div className="mt-1 flex justify-between text-[10px] text-[var(--text-subtle)]">
                  <span>128</span><span>2,048</span>
                </div>
              </div>
            </div>

            {/* Footer */}
            <div className="flex gap-3 border-t border-[var(--border)] px-6 py-4">
              <button onClick={onClose} className="flex-1 rounded-lg border border-[var(--border)] px-4 py-2 text-sm font-medium text-[var(--text-secondary)] hover:bg-[var(--surface-3)]">
                Cancel
              </button>
              <button
                onClick={handleCreate}
                disabled={!name.trim() || loading}
                className={cn('flex-1 flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium text-white transition-colors',
                  name.trim() && !loading ? 'bg-[var(--brand-500)] hover:opacity-90' : 'bg-[var(--surface-5)] cursor-not-allowed text-[var(--text-muted)]'
                )}
              >
                {loading && <RefreshCw className="h-3.5 w-3.5 animate-spin" />}
                {loading ? 'Creating...' : 'Create'}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

// ==================== Main Page ====================

type SortKey = 'name' | 'updated' | 'docs'
type ViewMode = 'grid' | 'list'

export default function DatasetsPage() {
  const { t } = useTranslation()
  const [datasets, setDatasets] = useState<Dataset[]>(initialDatasets)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<'' | 'ready' | 'indexing' | 'error'>('')
  const [sortKey, setSortKey] = useState<SortKey>('updated')
  const [viewMode, setViewMode] = useState<ViewMode>('grid')
  const [showCreate, setShowCreate] = useState(false)

  const filtered = datasets
    .filter((d) => {
      const q = search.toLowerCase()
      return (!q || d.name.toLowerCase().includes(q) || d.description.toLowerCase().includes(q)) &&
        (!statusFilter || d.status === statusFilter)
    })
    .sort((a, b) => {
      if (sortKey === 'name') return a.name.localeCompare(b.name)
      if (sortKey === 'docs') return b.documentCount - a.documentCount
      return new Date(b.lastUpdated).getTime() - new Date(a.lastUpdated).getTime()
    })

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-[var(--text-primary)]">{t('knowledge.title')}</h1>
          <p className="mt-1 text-sm text-[var(--text-tertiary)]">{t('knowledge.subtitle')}</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="group flex items-center gap-2 rounded-full bg-gradient-to-r from-violet-600 to-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-[0_0_12px_rgba(139,92,246,0.3)] transition-all duration-300 hover:shadow-[0_0_24px_rgba(139,92,246,0.5)] hover:-translate-y-0.5"
        >
          <Plus className="h-4 w-4" />
          New Knowledge Base
        </button>
      </div>

      {/* Toolbar */}
      <div className="mb-5 flex flex-wrap items-center gap-3">
        {/* Search */}
        <div className="relative flex-1 min-w-[200px] max-w-xs">
          <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--text-subtle)]" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search datasets..."
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface-2)] pl-8 pr-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-subtle)] focus:border-[var(--brand-500)] focus:outline-none"
          />
          {search && (
            <button onClick={() => setSearch('')} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[var(--text-subtle)] hover:text-[var(--text-primary)]">
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>

        {/* Status filter pills */}
        <div className="flex gap-1.5">
          {([{ v: '', l: 'All' }, { v: 'ready', l: 'Ready' }, { v: 'indexing', l: 'Indexing' }, { v: 'error', l: 'Error' }] as const).map((f) => (
            <button
              key={f.v}
              onClick={() => setStatusFilter(f.v)}
              className={cn(
                'rounded-full px-3 py-1 text-xs font-medium transition-colors',
                statusFilter === f.v ? 'bg-[var(--brand-500)] text-white' : 'bg-[var(--surface-3)] text-[var(--text-muted)] hover:bg-[var(--surface-5)]'
              )}
            >
              {f.l}
            </button>
          ))}
        </div>

        {/* Sort */}
        <div className="flex items-center gap-1 ml-auto">
          <SortAsc className="h-3.5 w-3.5 text-[var(--text-subtle)]" />
          <select
            value={sortKey}
            onChange={(e) => setSortKey(e.target.value as SortKey)}
            className="rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-2 py-1 text-xs text-[var(--text-secondary)] focus:outline-none"
          >
            <option value="updated">Last Updated</option>
            <option value="name">Name</option>
            <option value="docs">Documents</option>
          </select>
          {/* View Toggle */}
          <div className="ml-2 flex rounded-lg border border-[var(--border)] overflow-hidden">
            <button onClick={() => setViewMode('grid')} className={cn('p-1.5 transition-colors', viewMode === 'grid' ? 'bg-[var(--surface-5)]' : 'hover:bg-[var(--surface-3)]')}>
              <LayoutGrid className="h-3.5 w-3.5 text-[var(--text-secondary)]" />
            </button>
            <button onClick={() => setViewMode('list')} className={cn('p-1.5 transition-colors border-l border-[var(--border)]', viewMode === 'list' ? 'bg-[var(--surface-5)]' : 'hover:bg-[var(--surface-3)]')}>
              <LayoutList className="h-3.5 w-3.5 text-[var(--text-secondary)]" />
            </button>
          </div>
        </div>
      </div>

      {/* Results info */}
      {search && (
        <p className="mb-3 text-xs text-[var(--text-muted)]">
          {filtered.length} result{filtered.length !== 1 ? 's' : ''} for "{search}"
        </p>
      )}

      {/* Grid View */}
      {viewMode === 'grid' && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <AnimatePresence mode="popLayout">
            {filtered.map((ds, i) => {
              const status = STATUS_CONFIG[ds.status]
              return (
                <motion.div
                  key={ds.id}
                  layout
                  initial={{ opacity: 0, scale: 0.97 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.97 }}
                  transition={{ delay: i * 0.04 }}
                >
                  <Link href={`/knowledge/datasets/${ds.id}`}>
                    <div className="group rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-5 transition-all hover:-translate-y-0.5 hover:shadow-lg hover:border-[var(--brand-500)]">
                      <div className="flex items-start justify-between">
                        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[var(--surface-5)]">
                          <Database className="h-5 w-5 text-[var(--brand-500)]" />
                        </div>
                        <span className={cn('rounded-full px-2 py-0.5 text-[10px] font-medium', status.pill)}>
                          {status.label}
                        </span>
                      </div>
                      <h3 className="mt-3 text-sm font-semibold text-[var(--text-primary)]">{ds.name}</h3>
                      <p className="mt-1 text-xs text-[var(--text-muted)] line-clamp-2">{ds.description}</p>
                      <div className="mt-4 flex items-center gap-4 text-[11px] text-[var(--text-subtle)]">
                        <span className="flex items-center gap-1"><FileText className="h-3 w-3" /> {ds.documentCount} docs</span>
                        <span className="flex items-center gap-1"><Layers className="h-3 w-3" /> {ds.chunkCount} chunks</span>
                      </div>
                      <div className="mt-2 flex items-center gap-1 text-[10px] text-[var(--text-subtle)]">
                        <Clock className="h-3 w-3" /> {formatDate(ds.lastUpdated)}
                      </div>
                    </div>
                  </Link>
                </motion.div>
              )
            })}
          </AnimatePresence>
        </div>
      )}

      {/* List View */}
      {viewMode === 'list' && (
        <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-2)] overflow-hidden">
          <div className="border-b border-[var(--border)] px-4 py-2.5 flex items-center text-[11px] font-semibold text-[var(--text-muted)] uppercase tracking-wide bg-[var(--surface-3)]">
            <span className="flex-1">Name</span>
            <span className="w-20 text-center hidden sm:block">Docs</span>
            <span className="w-24 text-center hidden md:block">Chunks</span>
            <span className="w-20 text-center">Status</span>
            <span className="w-28 text-right hidden lg:block">Updated</span>
          </div>
          <AnimatePresence mode="popLayout">
            {filtered.map((ds, i) => {
              const status = STATUS_CONFIG[ds.status]
              return (
                <motion.div
                  key={ds.id}
                  layout
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ delay: i * 0.02 }}
                  className={cn('flex items-center px-4 py-3 hover:bg-[var(--surface-3)] transition-colors', i < filtered.length - 1 && 'border-b border-[var(--border)]')}
                >
                  <Link href={`/knowledge/datasets/${ds.id}`} className="flex flex-1 min-w-0 items-center gap-3">
                    <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-md bg-[var(--surface-5)]">
                      <Database className="h-4 w-4 text-[var(--brand-500)]" />
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-[var(--text-primary)] truncate">{ds.name}</p>
                      <p className="text-xs text-[var(--text-muted)] truncate">{ds.description}</p>
                    </div>
                  </Link>
                  <span className="w-20 text-center text-xs text-[var(--text-muted)] hidden sm:block">{ds.documentCount}</span>
                  <span className="w-24 text-center text-xs text-[var(--text-muted)] hidden md:block">{ds.chunkCount}</span>
                  <div className="w-20 flex justify-center">
                    <span className={cn('rounded-full px-2 py-0.5 text-[10px] font-medium', status.pill)}>{status.label}</span>
                  </div>
                  <span className="w-28 text-right text-xs text-[var(--text-subtle)] hidden lg:block">{formatDate(ds.lastUpdated)}</span>
                </motion.div>
              )
            })}
          </AnimatePresence>
          {filtered.length === 0 && (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Database className="h-8 w-8 text-[var(--text-subtle)] mb-3" />
              <p className="text-sm text-[var(--text-muted)]">No datasets found</p>
            </div>
          )}
        </div>
      )}

      {/* Empty state */}
      {filtered.length === 0 && viewMode === 'grid' && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="flex flex-col items-center justify-center py-20 text-center"
        >
          <Database className="h-10 w-10 text-[var(--text-subtle)] mb-4" />
          <p className="text-sm font-medium text-[var(--text-secondary)] mb-1">No datasets found</p>
          <p className="text-xs text-[var(--text-muted)]">
            {search ? 'Try a different search term' : 'Create your first knowledge base to get started'}
          </p>
        </motion.div>
      )}

      <CreateDatasetModal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onCreate={(ds) => setDatasets((prev) => [ds, ...prev])}
      />
    </div>
  )
}
