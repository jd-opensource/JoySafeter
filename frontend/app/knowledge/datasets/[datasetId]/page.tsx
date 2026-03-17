'use client'

import { motion } from 'framer-motion'
import {
  ArrowLeft,
  FileText,
  Layers,
  Search,
  Clock,
  Database,
  Cpu,
  HardDrive,
} from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { cn } from '@/lib/core/utils/cn'
import { datasets, datasetDocuments, mockSearchResults } from '@/mocks/datasets'

const fileTypeColors: Record<string, string> = {
  pdf: 'text-red-500 bg-red-50 dark:bg-red-950/20',
  md: 'text-blue-500 bg-blue-50 dark:bg-blue-950/20',
  txt: 'text-gray-500 bg-gray-50 dark:bg-gray-950/20',
  html: 'text-orange-500 bg-orange-50 dark:bg-orange-950/20',
  json: 'text-green-500 bg-green-50 dark:bg-green-950/20',
}

export default function DatasetDetailPage() {
  const { t } = useTranslation()
  const params = useParams<{ datasetId: string }>()
  const [searchQuery, setSearchQuery] = useState('')
  const [activeTab, setActiveTab] = useState<'documents' | 'search'>('documents')

  const dataset = datasets.find((d) => d.id === params.datasetId)
  const documents = datasetDocuments[params.datasetId] || []

  if (!dataset) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-[var(--text-muted)]">Dataset not found</p>
      </div>
    )
  }

  const showSearchResults = activeTab === 'search' && searchQuery.trim().length > 0

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      {/* Header */}
      <div className="mb-6">
        <Link
          href="/knowledge/datasets"
          className="mb-4 inline-flex items-center gap-1 text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)]"
        >
          <ArrowLeft className="h-3 w-3" /> Back to datasets
        </Link>

        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-[var(--surface-5)]">
              <Database className="h-6 w-6 text-[var(--brand-500)]" />
            </div>
            <div>
              <h1 className="text-xl font-semibold text-[var(--text-primary)]">{dataset.name}</h1>
              <p className="mt-0.5 text-sm text-[var(--text-tertiary)]">{dataset.description}</p>
            </div>
          </div>
        </div>

        {/* Stats */}
        <div className="mt-4 flex items-center gap-6 text-xs text-[var(--text-muted)]">
          <span className="flex items-center gap-1.5">
            <FileText className="h-3.5 w-3.5" /> {dataset.documentCount} documents
          </span>
          <span className="flex items-center gap-1.5">
            <Layers className="h-3.5 w-3.5" /> {dataset.chunkCount} chunks
          </span>
          <span className="flex items-center gap-1.5">
            <HardDrive className="h-3.5 w-3.5" /> {dataset.size}
          </span>
          <span className="flex items-center gap-1.5">
            <Cpu className="h-3.5 w-3.5" /> {dataset.embeddingModel}
          </span>
        </div>
      </div>

      {/* Tabs */}
      <div className="mb-4 flex gap-1 rounded-lg bg-[var(--surface-3)] p-1 w-fit">
        {(['documents', 'search'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={cn(
              'rounded-md px-4 py-1.5 text-xs font-medium transition-colors',
              activeTab === tab
                ? 'bg-[var(--surface-elevated)] text-[var(--text-primary)] shadow-sm'
                : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
            )}
          >
            {tab === 'documents' ? t('knowledge.documentList') : t('knowledge.search')}
          </button>
        ))}
      </div>

      {/* Documents Tab */}
      {activeTab === 'documents' && (
        <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-2)]">
          <div className="border-b border-[var(--border)] px-4 py-2 flex items-center text-[11px] font-medium text-[var(--text-muted)]">
            <span className="flex-1">Name</span>
            <span className="w-20 text-center">Type</span>
            <span className="w-20 text-center">Chunks</span>
            <span className="w-20 text-center">Size</span>
            <span className="w-24 text-center">Added</span>
          </div>
          {documents.length > 0 ? (
            documents.map((doc, i) => (
              <motion.div
                key={doc.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: i * 0.03 }}
                className={cn(
                  'flex items-center px-4 py-2.5 transition-colors hover:bg-[var(--surface-3)]',
                  i < documents.length - 1 && 'border-b border-[var(--border)]'
                )}
              >
                <span className="flex-1 flex items-center gap-2 text-sm text-[var(--text-primary)]">
                  <FileText className="h-3.5 w-3.5 text-[var(--text-muted)]" />
                  {doc.name}
                </span>
                <span className="w-20 text-center">
                  <span className={cn('rounded px-1.5 py-0.5 text-[10px] font-medium', fileTypeColors[doc.type])}>
                    {doc.type.toUpperCase()}
                  </span>
                </span>
                <span className="w-20 text-center text-xs text-[var(--text-muted)]">{doc.chunks}</span>
                <span className="w-20 text-center text-xs text-[var(--text-muted)]">{doc.size}</span>
                <span className="w-24 text-center text-xs text-[var(--text-subtle)]">{doc.addedAt}</span>
              </motion.div>
            ))
          ) : (
            <div className="px-4 py-8 text-center text-sm text-[var(--text-muted)]">
              No documents in this dataset. Sample data available for dataset ds-001.
            </div>
          )}
        </div>
      )}

      {/* Search Tab */}
      {activeTab === 'search' && (
        <div>
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
          </div>

          {showSearchResults && (
            <div className="space-y-3">
              <h3 className="text-xs font-semibold text-[var(--text-secondary)]">
                {t('knowledge.searchResults')} ({mockSearchResults.length})
              </h3>
              {mockSearchResults.map((result, i) => (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.08 }}
                  className="rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-4"
                >
                  <div className="mb-2 flex items-center justify-between">
                    <span className="text-xs font-medium text-[var(--text-primary)]">{result.documentName}</span>
                    <div className="flex items-center gap-3 text-[10px] text-[var(--text-muted)]">
                      <span>{t('knowledge.chunkIndex')}{result.chunkIndex}</span>
                      <span className="rounded bg-[var(--brand-500)] px-1.5 py-0.5 text-white font-medium">
                        {t('knowledge.score')}: {result.score.toFixed(2)}
                      </span>
                    </div>
                  </div>
                  <p className="text-xs leading-relaxed text-[var(--text-tertiary)]">{result.chunkContent}</p>
                </motion.div>
              ))}
            </div>
          )}

          {activeTab === 'search' && !showSearchResults && (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <Search className="h-8 w-8 text-[var(--text-subtle)] mb-3" />
              <p className="text-sm text-[var(--text-muted)]">{t('knowledge.searchPlaceholder')}</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
