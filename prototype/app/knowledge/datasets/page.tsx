'use client'

import { motion } from 'framer-motion'
import { Database, FileText, Layers, Clock, Plus, Search } from 'lucide-react'
import Link from 'next/link'
import { useTranslation } from 'react-i18next'

import { cn } from '@/lib/core/utils/cn'
import { datasets, type Dataset } from '@/mocks/datasets'

const statusConfig = {
  ready: { label: 'Ready', color: 'bg-[var(--status-healthy)] text-white' },
  indexing: { label: 'Indexing', color: 'bg-[var(--status-running)] text-white animate-pulse' },
  error: { label: 'Error', color: 'bg-[var(--status-offline)] text-white' },
} as const

function formatDate(ts: string): string {
  return new Date(ts).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

export default function DatasetsPage() {
  const { t } = useTranslation()

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-[var(--text-primary)]">{t('knowledge.title')}</h1>
          <p className="mt-1 text-sm text-[var(--text-tertiary)]">{t('knowledge.subtitle')}</p>
        </div>
        <button className="flex items-center gap-2 rounded-lg bg-[var(--brand-500)] px-4 py-2 text-sm font-medium text-white transition-colors hover:opacity-90">
          <Plus className="h-4 w-4" />
          {t('knowledge.addDocuments')}
        </button>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {datasets.map((ds, i) => {
          const status = statusConfig[ds.status]
          return (
            <motion.div
              key={ds.id}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.06 }}
            >
              <Link href={`/knowledge/datasets/${ds.id}`}>
                <div className="group rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-5 transition-all hover:-translate-y-0.5 hover:shadow-lg hover:border-[var(--brand-500)]">
                  <div className="flex items-start justify-between">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[var(--surface-5)]">
                      <Database className="h-5 w-5 text-[var(--brand-500)]" />
                    </div>
                    <span className={cn('rounded-full px-2 py-0.5 text-[10px] font-medium', status.color)}>
                      {t(`knowledge.${ds.status}`)}
                    </span>
                  </div>

                  <h3 className="mt-3 text-sm font-semibold text-[var(--text-primary)]">{ds.name}</h3>
                  <p className="mt-1 text-xs text-[var(--text-muted)] line-clamp-2">{ds.description}</p>

                  <div className="mt-4 flex items-center gap-4 text-[11px] text-[var(--text-subtle)]">
                    <span className="flex items-center gap-1">
                      <FileText className="h-3 w-3" /> {ds.documentCount} docs
                    </span>
                    <span className="flex items-center gap-1">
                      <Layers className="h-3 w-3" /> {ds.chunkCount} chunks
                    </span>
                  </div>
                  <div className="mt-2 flex items-center gap-1 text-[10px] text-[var(--text-subtle)]">
                    <Clock className="h-3 w-3" /> {formatDate(ds.lastUpdated)}
                  </div>
                </div>
              </Link>
            </motion.div>
          )
        })}
      </div>
    </div>
  )
}
