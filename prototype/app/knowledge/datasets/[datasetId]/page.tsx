'use client'

import { AnimatePresence, motion } from 'framer-motion'
import {
  ArrowLeft, FileText, Layers, Search, Clock, Database, Cpu, HardDrive, Plus,
  Trash2, RefreshCw, X, AlertCircle, Upload, CheckCircle2, Settings, ChevronDown,
} from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { cn } from '@/lib/core/utils/cn'
import { toastSuccess, toastError, toastInfo } from '@/lib/utils/toast'
import { datasets, datasetDocuments, mockSearchResults, type Document } from '@/mocks/datasets'

const FILE_TYPE_STYLES: Record<string, string> = {
  pdf: 'text-red-500 bg-red-50 dark:bg-red-950/20',
  md: 'text-blue-500 bg-blue-50 dark:bg-blue-950/20',
  txt: 'text-gray-500 bg-gray-50 dark:bg-gray-950/20',
  html: 'text-orange-500 bg-orange-50 dark:bg-orange-950/20',
  json: 'text-green-500 bg-green-50 dark:bg-green-950/20',
  docx: 'text-blue-600 bg-blue-50 dark:bg-blue-950/20',
  csv: 'text-teal-500 bg-teal-50 dark:bg-teal-950/20',
}

const MOCK_UPLOAD_FILES = [
  'NIST-Cybersecurity-Framework.pdf',
  'CVE-2026-Analysis.md',
  'API-Security-Checklist.html',
  'Threat-Model-Template.docx',
  'Vulnerability-Signatures.json',
]

// ==================== Confirm Dialog ====================
function ConfirmDialog({ open, title, description, onConfirm, onCancel }: {
  open: boolean; title: string; description: string; onConfirm: () => void; onCancel: () => void
}) {
  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-50 flex items-center justify-center" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onCancel} />
          <motion.div initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }}
            className="relative z-10 w-full max-w-sm rounded-2xl border border-[var(--border)] bg-[var(--surface-1)] p-6 shadow-xl">
            <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-full bg-red-100">
              <AlertCircle className="h-5 w-5 text-red-600" />
            </div>
            <h3 className="mb-1 text-base font-semibold text-[var(--text-primary)]">{title}</h3>
            <p className="mb-6 text-sm text-[var(--text-muted)]">{description}</p>
            <div className="flex gap-3">
              <button onClick={onCancel} className="flex-1 rounded-lg border border-[var(--border)] px-4 py-2 text-sm font-medium text-[var(--text-secondary)] hover:bg-[var(--surface-3)]">Cancel</button>
              <button onClick={onConfirm} className="flex-1 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700">Delete</button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

// ==================== Upload Modal ====================
function UploadModal({ open, onClose, onUploaded }: {
  open: boolean; onClose: () => void; onUploaded: (doc: Document) => void
}) {
  const [dragOver, setDragOver] = useState(false)
  const [processing, setProcessing] = useState(false)
  const [selectedFile, setSelectedFile] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  function pickRandomFile() {
    const f = MOCK_UPLOAD_FILES[Math.floor(Math.random() * MOCK_UPLOAD_FILES.length)]
    setSelectedFile(f)
  }

  async function handleUpload() {
    if (!selectedFile) return
    setProcessing(true)
    await new Promise((r) => setTimeout(r, 1200))
    const ext = selectedFile.split('.').pop() as Document['type'] || 'txt'
    const doc: Document = {
      id: `doc-${Date.now()}`,
      name: selectedFile,
      type: ext,
      chunks: Math.floor(Math.random() * 30) + 5,
      size: `${(Math.random() * 2 + 0.1).toFixed(1)} MB`,
      addedAt: new Date().toISOString().split('T')[0],
    }
    onUploaded(doc)
    setProcessing(false)
    setSelectedFile(null)
    onClose()
    toastSuccess(`"${selectedFile}" indexed successfully`)
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-50 flex items-center justify-center p-4" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
          <motion.div initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }} transition={{ duration: 0.18 }}
            className="relative z-10 w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--surface-1)] shadow-2xl">
            <div className="flex items-center justify-between border-b border-[var(--border)] px-6 py-4">
              <h2 className="text-base font-semibold text-[var(--text-primary)]">Add Documents</h2>
              <button onClick={onClose} className="rounded-lg p-1.5 text-[var(--text-muted)] hover:bg-[var(--surface-3)]"><X className="h-4 w-4" /></button>
            </div>

            <div className="px-6 py-5 space-y-4">
              {/* Drop zone */}
              <div
                onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
                onDragLeave={() => setDragOver(false)}
                onDrop={(e) => { e.preventDefault(); setDragOver(false); pickRandomFile() }}
                onClick={() => { pickRandomFile() }}
                className={cn(
                  'flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed py-10 transition-colors',
                  dragOver ? 'border-[var(--brand-500)] bg-[var(--brand-500)]/5' : 'border-[var(--border)] hover:border-[var(--brand-500)]/50 hover:bg-[var(--surface-3)]'
                )}
              >
                <Upload className={cn('h-8 w-8 mb-3', dragOver ? 'text-[var(--brand-500)]' : 'text-[var(--text-subtle)]')} />
                <p className="text-sm font-medium text-[var(--text-secondary)]">Drop files here or click to select</p>
                <p className="mt-1 text-xs text-[var(--text-subtle)]">PDF, MD, TXT, HTML, JSON, DOCX, CSV</p>
                <input ref={fileInputRef} type="file" className="sr-only" />
              </div>

              {/* Selected file */}
              {selectedFile && (
                <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
                  className="flex items-center gap-3 rounded-lg border border-[var(--brand-500)]/30 bg-[var(--brand-500)]/5 px-4 py-3">
                  <FileText className="h-4 w-4 text-[var(--brand-500)]" />
                  <span className="flex-1 text-sm text-[var(--text-primary)] truncate">{selectedFile}</span>
                  <button onClick={() => setSelectedFile(null)} className="text-[var(--text-subtle)] hover:text-[var(--text-primary)]"><X className="h-3.5 w-3.5" /></button>
                </motion.div>
              )}
            </div>

            <div className="flex gap-3 border-t border-[var(--border)] px-6 py-4">
              <button onClick={onClose} className="flex-1 rounded-lg border border-[var(--border)] px-4 py-2 text-sm font-medium text-[var(--text-secondary)] hover:bg-[var(--surface-3)]">Cancel</button>
              <button
                onClick={handleUpload}
                disabled={!selectedFile || processing}
                className={cn('flex-1 flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium text-white transition-colors',
                  selectedFile && !processing ? 'bg-[var(--brand-500)] hover:opacity-90' : 'bg-[var(--surface-5)] cursor-not-allowed text-[var(--text-muted)]'
                )}
              >
                {processing && <RefreshCw className="h-3.5 w-3.5 animate-spin" />}
                {processing ? 'Indexing...' : 'Upload & Index'}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

// ==================== Settings Tab ====================
function SettingsTab({ dataset }: { dataset: ReturnType<typeof datasets.find> }) {
  if (!dataset) return null
  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-2)] divide-y divide-[var(--border)]">
        {[
          { label: 'Name', value: dataset.name },
          { label: 'Embedding Model', value: dataset.embeddingModel },
          { label: 'Chunk Strategy', value: 'Fixed length (512 tokens)' },
          { label: 'Overlap', value: '50 tokens' },
          { label: 'Language', value: 'Auto-detect' },
          { label: 'Index Type', value: 'High quality (HNSW)' },
        ].map(({ label, value }) => (
          <div key={label} className="flex items-center justify-between px-5 py-3">
            <span className="text-sm text-[var(--text-muted)]">{label}</span>
            <span className="text-sm font-medium text-[var(--text-primary)]">{value}</span>
          </div>
        ))}
      </div>
      <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-5">
        <h3 className="mb-3 text-sm font-semibold text-[var(--text-secondary)]">Storage</h3>
        <div className="flex items-center gap-4 text-xs text-[var(--text-muted)]">
          <span className="flex items-center gap-1.5"><HardDrive className="h-3.5 w-3.5" />{dataset.size} used</span>
          <span className="flex items-center gap-1.5"><FileText className="h-3.5 w-3.5" />{dataset.documentCount} documents</span>
          <span className="flex items-center gap-1.5"><Layers className="h-3.5 w-3.5" />{dataset.chunkCount} chunks</span>
        </div>
      </div>
      <div className="rounded-xl border border-red-200 dark:border-red-900/30 bg-red-50 dark:bg-red-950/10 p-5">
        <h3 className="mb-1 text-sm font-semibold text-red-700 dark:text-red-400">Danger Zone</h3>
        <p className="mb-3 text-xs text-red-600/70 dark:text-red-400/70">Permanently delete this knowledge base and all its data.</p>
        <button className="rounded-lg border border-red-300 dark:border-red-800 bg-white dark:bg-transparent px-4 py-1.5 text-xs font-medium text-red-600 transition-colors hover:bg-red-600 hover:text-white">
          Delete Knowledge Base
        </button>
      </div>
    </div>
  )
}

// ==================== Main Page ====================

type Tab = 'documents' | 'search' | 'settings'

export default function DatasetDetailPage() {
  const { t } = useTranslation()
  const params = useParams<{ datasetId: string }>()
  const [searchQuery, setSearchQuery] = useState('')
  const [activeTab, setActiveTab] = useState<Tab>('documents')
  const [showUpload, setShowUpload] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState<{ open: boolean; docId: string; docName: string }>({ open: false, docId: '', docName: '' })

  const dataset = datasets.find((d) => d.id === params.datasetId)
  const [documents, setDocuments] = useState<Document[]>(datasetDocuments[params.datasetId] || [])

  if (!dataset) {
    return <div className="flex h-full items-center justify-center"><p className="text-sm text-[var(--text-muted)]">Dataset not found</p></div>
  }

  const showSearchResults = activeTab === 'search' && searchQuery.trim().length > 0

  function handleDeleteDoc(docId: string) {
    setDocuments((prev) => prev.filter((d) => d.id !== docId))
    setConfirmDelete({ open: false, docId: '', docName: '' })
    toastSuccess('Document deleted')
  }

  const tabs: Array<{ key: Tab; label: string }> = [
    { key: 'documents', label: t('knowledge.documentList') },
    { key: 'search', label: t('knowledge.search') },
    { key: 'settings', label: 'Settings' },
  ]

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      {/* Back */}
      <Link href="/knowledge/datasets" className="mb-4 inline-flex items-center gap-1 text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)]">
        <ArrowLeft className="h-3 w-3" /> Back to datasets
      </Link>

      {/* Header */}
      <div className="mb-6 flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-[var(--surface-5)]">
            <Database className="h-6 w-6 text-[var(--brand-500)]" />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-[var(--text-primary)]">{dataset.name}</h1>
            <p className="mt-0.5 text-sm text-[var(--text-tertiary)]">{dataset.description}</p>
          </div>
        </div>
        <button
          onClick={() => setShowUpload(true)}
          className="flex shrink-0 items-center gap-2 rounded-lg bg-[var(--brand-500)] px-4 py-2 text-sm font-medium text-white transition-colors hover:opacity-90"
        >
          <Plus className="h-4 w-4" /> Add Documents
        </button>
      </div>

      {/* Stats */}
      <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { icon: FileText, label: 'Documents', value: documents.length },
          { icon: Layers, label: 'Chunks', value: dataset.chunkCount },
          { icon: HardDrive, label: 'Size', value: dataset.size },
          { icon: Cpu, label: 'Model', value: dataset.embeddingModel.split('-').slice(-2).join('-') },
        ].map(({ icon: Icon, label, value }) => (
          <div key={label} className="rounded-xl border border-[var(--border)] bg-[var(--surface-2)] px-4 py-3">
            <div className="flex items-center gap-1.5 text-xs text-[var(--text-muted)]">
              <Icon className="h-3 w-3" /> {label}
            </div>
            <p className="mt-1 text-sm font-semibold text-[var(--text-primary)] truncate">{value}</p>
          </div>
        ))}
      </div>

      {/* Tabs */}
      <div className="mb-4 flex gap-1 rounded-lg bg-[var(--surface-3)] p-1 w-fit">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={cn('rounded-md px-4 py-1.5 text-xs font-medium transition-colors',
              activeTab === tab.key
                ? 'bg-[var(--surface-1)] text-[var(--text-primary)] shadow-sm'
                : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <AnimatePresence mode="wait">
        {/* Documents Tab */}
        {activeTab === 'documents' && (
          <motion.div key="docs" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}>
            <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-2)] overflow-hidden">
              <div className="border-b border-[var(--border)] px-4 py-2.5 flex items-center text-[11px] font-semibold text-[var(--text-muted)] uppercase tracking-wide bg-[var(--surface-3)]">
                <span className="flex-1">Name</span>
                <span className="w-16 text-center">Type</span>
                <span className="w-16 text-center hidden sm:block">Chunks</span>
                <span className="w-16 text-center hidden md:block">Size</span>
                <span className="w-20 text-center hidden lg:block">Added</span>
                <span className="w-10" />
              </div>
              {documents.length > 0 ? (
                <AnimatePresence>
                  {documents.map((doc, i) => (
                    <motion.div
                      key={doc.id}
                      layout
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0, height: 0 }}
                      transition={{ delay: i * 0.03 }}
                      className={cn('group flex items-center px-4 py-2.5 transition-colors hover:bg-[var(--surface-3)]', i < documents.length - 1 && 'border-b border-[var(--border)]')}
                    >
                      <span className="flex-1 flex items-center gap-2 text-sm text-[var(--text-primary)] min-w-0">
                        <FileText className="h-3.5 w-3.5 flex-shrink-0 text-[var(--text-muted)]" />
                        <span className="truncate">{doc.name}</span>
                      </span>
                      <span className="w-16 flex justify-center">
                        <span className={cn('rounded px-1.5 py-0.5 text-[10px] font-medium', FILE_TYPE_STYLES[doc.type] ?? 'text-gray-500 bg-gray-50')}>
                          {doc.type.toUpperCase()}
                        </span>
                      </span>
                      <span className="w-16 text-center text-xs text-[var(--text-muted)] hidden sm:block">{doc.chunks}</span>
                      <span className="w-16 text-center text-xs text-[var(--text-muted)] hidden md:block">{doc.size}</span>
                      <span className="w-20 text-center text-xs text-[var(--text-subtle)] hidden lg:block">{doc.addedAt}</span>
                      <div className="w-10 flex justify-end opacity-0 group-hover:opacity-100 transition-opacity">
                        <button
                          onClick={() => setConfirmDelete({ open: true, docId: doc.id, docName: doc.name })}
                          className="rounded-md p-1 text-[var(--text-subtle)] hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950/30"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </motion.div>
                  ))}
                </AnimatePresence>
              ) : (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <FileText className="h-8 w-8 text-[var(--text-subtle)] mb-3" />
                  <p className="text-sm text-[var(--text-muted)] mb-3">No documents yet</p>
                  <button
                    onClick={() => setShowUpload(true)}
                    className="flex items-center gap-1.5 rounded-lg bg-[var(--brand-500)] px-3 py-1.5 text-xs font-medium text-white hover:opacity-90"
                  >
                    <Plus className="h-3.5 w-3.5" /> Add First Document
                  </button>
                </div>
              )}
            </div>
          </motion.div>
        )}

        {/* Search Tab */}
        {activeTab === 'search' && (
          <motion.div key="search" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}>
            <div className="mb-4 flex items-center gap-2">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--text-subtle)]" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder={t('knowledge.searchPlaceholder')}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface-2)] pl-9 pr-4 py-2.5 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-subtle)] focus:border-[var(--brand-500)] focus:outline-none"
                />
              </div>
              <button className="rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-4 py-2.5 text-sm font-medium text-[var(--text-secondary)] hover:bg-[var(--surface-3)]">
                Search
              </button>
            </div>

            {showSearchResults && (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-semibold text-[var(--text-secondary)]">
                    {t('knowledge.searchResults')} ({mockSearchResults.length})
                  </h3>
                  <span className="text-xs text-[var(--text-subtle)]">Ranked by relevance</span>
                </div>
                {mockSearchResults.map((result, i) => (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.08 }}
                    className="rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-4"
                  >
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2 min-w-0">
                        <FileText className="h-3.5 w-3.5 flex-shrink-0 text-[var(--text-subtle)]" />
                        <span className="text-xs font-medium text-[var(--text-primary)] truncate">{result.documentName}</span>
                        <span className="text-[10px] text-[var(--text-subtle)] flex-shrink-0">Chunk #{result.chunkIndex}</span>
                      </div>
                      <span className="flex-shrink-0 rounded bg-[var(--brand-500)] px-1.5 py-0.5 text-[10px] font-medium text-white">
                        {(result.score * 100).toFixed(0)}%
                      </span>
                    </div>
                    <div className="h-1.5 w-full rounded-full bg-[var(--surface-5)] mb-3">
                      <div className="h-full rounded-full bg-[var(--brand-500)]" style={{ width: `${result.score * 100}%` }} />
                    </div>
                    <p className="text-xs leading-relaxed text-[var(--text-tertiary)]">{result.chunkContent}</p>
                  </motion.div>
                ))}
              </div>
            )}

            {!showSearchResults && (
              <div className="flex flex-col items-center justify-center py-16 text-center">
                <Search className="h-8 w-8 text-[var(--text-subtle)] mb-3" />
                <p className="text-sm text-[var(--text-secondary)] mb-1">Semantic Search</p>
                <p className="text-xs text-[var(--text-muted)]">Enter a query to find relevant chunks using vector similarity</p>
              </div>
            )}
          </motion.div>
        )}

        {/* Settings Tab */}
        {activeTab === 'settings' && (
          <motion.div key="settings" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}>
            <SettingsTab dataset={dataset} />
          </motion.div>
        )}
      </AnimatePresence>

      {/* Upload Modal */}
      <UploadModal
        open={showUpload}
        onClose={() => setShowUpload(false)}
        onUploaded={(doc) => setDocuments((prev) => [...prev, doc])}
      />

      {/* Delete Confirm */}
      <ConfirmDialog
        open={confirmDelete.open}
        title="Delete Document"
        description={`"${confirmDelete.docName}" and its ${Math.floor(Math.random() * 30 + 5)} chunks will be permanently deleted.`}
        onConfirm={() => handleDeleteDoc(confirmDelete.docId)}
        onCancel={() => setConfirmDelete({ open: false, docId: '', docName: '' })}
      />
    </div>
  )
}
