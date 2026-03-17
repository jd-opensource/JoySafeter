'use client'

import { AnimatePresence, motion } from 'framer-motion'
import {
  Bot,
  Database,
  Play,
  Pause,
  Square,
  Trash2,
  Download,
  Eye,
  Plus,
  X,
  ChevronRight,
  BarChart3,
  Clock,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Ban,
} from 'lucide-react'
import Link from 'next/link'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import CountUp from 'react-countup'

import { cn } from '@/lib/core/utils/cn'
import { toastSuccess, toastError, toastInfo } from '@/lib/utils/toast'
import { evaluationTasks as initialTasks, type EvaluationTask, type EvalStatus } from '@/mocks/evaluations'
import { mockAgents } from '@/mocks/agents'
import { datasets } from '@/mocks/datasets'

// ==================== Status config ====================

const STATUS_CONFIG: Record<EvalStatus, { label: string; icon: React.ComponentType<{ className?: string }>; pill: string }> = {
  pending: { label: 'Pending', icon: Clock, pill: 'text-yellow-700 bg-yellow-50 dark:text-yellow-300 dark:bg-yellow-950/30' },
  running: { label: 'Running', icon: Play, pill: 'text-blue-700 bg-blue-50 dark:text-blue-300 dark:bg-blue-950/30' },
  paused: { label: 'Paused', icon: Pause, pill: 'text-orange-700 bg-orange-50 dark:text-orange-300 dark:bg-orange-950/30' },
  completed: { label: 'Completed', icon: CheckCircle2, pill: 'text-green-700 bg-green-50 dark:text-green-300 dark:bg-green-950/30' },
  failed: { label: 'Failed', icon: XCircle, pill: 'text-red-700 bg-red-50 dark:text-red-300 dark:bg-red-950/30' },
  cancelled: { label: 'Cancelled', icon: Ban, pill: 'text-gray-600 bg-gray-100 dark:text-gray-400 dark:bg-gray-800/50' },
}

const FILTER_TABS: Array<{ value: '' | EvalStatus; label: string }> = [
  { value: '', label: 'All' },
  { value: 'pending', label: 'Pending' },
  { value: 'running', label: 'Running' },
  { value: 'paused', label: 'Paused' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
  { value: 'cancelled', label: 'Cancelled' },
]

function formatDate(ts: string) {
  return new Date(ts).toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

// ==================== Confirmation Dialog ====================

function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  variant,
  onConfirm,
  onCancel,
}: {
  open: boolean
  title: string
  description: string
  confirmLabel: string
  variant: 'danger' | 'warning'
  onConfirm: () => void
  onCancel: () => void
}) {
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onCancel} />
          <motion.div
            initial={{ scale: 0.95, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.95, opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="relative z-10 w-full max-w-sm rounded-2xl border border-[var(--border)] bg-[var(--surface-1)] p-6 shadow-xl"
          >
            <div className={cn('mb-4 flex h-10 w-10 items-center justify-center rounded-full', variant === 'danger' ? 'bg-red-100 dark:bg-red-950/30' : 'bg-orange-100 dark:bg-orange-950/30')}>
              <AlertCircle className={cn('h-5 w-5', variant === 'danger' ? 'text-red-600' : 'text-orange-600')} />
            </div>
            <h3 className="mb-1 text-base font-semibold text-[var(--text-primary)]">{title}</h3>
            <p className="mb-6 text-sm text-[var(--text-muted)]">{description}</p>
            <div className="flex gap-3">
              <button
                onClick={onCancel}
                className="flex-1 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-4 py-2 text-sm font-medium text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-3)]"
              >
                Cancel
              </button>
              <button
                onClick={onConfirm}
                className={cn(
                  'flex-1 rounded-lg px-4 py-2 text-sm font-medium text-white transition-colors',
                  variant === 'danger' ? 'bg-red-600 hover:bg-red-700' : 'bg-orange-500 hover:bg-orange-600'
                )}
              >
                {confirmLabel}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

// ==================== Create Evaluation Drawer ====================

function CreateDrawer({ open, onClose, onCreate }: {
  open: boolean
  onClose: () => void
  onCreate: (task: EvaluationTask) => void
}) {
  const [step, setStep] = useState(1)
  const [name, setName] = useState('')
  const [agentId, setAgentId] = useState(mockAgents[0]?.id ?? '')
  const [datasetId, setDatasetId] = useState(datasets[0]?.id ?? '')
  const [sampleLimit, setSampleLimit] = useState(500)
  const [concurrent, setConcurrent] = useState(2)

  const selectedAgent = mockAgents.find(a => a.id === agentId)
  const selectedDataset = datasets.find(d => d.id === datasetId)

  function handleCreate() {
    if (!name.trim()) return
    const now = new Date().toISOString()
    const task: EvaluationTask = {
      id: `eval-${Date.now()}`,
      name: name.trim(),
      agentName: selectedAgent?.name ?? 'Unknown Agent',
      dataset: selectedDataset?.name ?? 'Unknown Dataset',
      status: 'pending',
      progress: 0,
      totalSamples: sampleLimit,
      completedSamples: 0,
      accuracy: null,
      createdAt: now,
      startedAt: null,
      completedAt: null,
    }
    onCreate(task)
    setStep(1)
    setName('')
    setAgentId(mockAgents[0]?.id ?? '')
    setDatasetId(datasets[0]?.id ?? '')
    setSampleLimit(500)
    setConcurrent(2)
    onClose()
    toastSuccess('Evaluation task created successfully')
  }

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            className="fixed inset-0 z-40 bg-black/30 backdrop-blur-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />
          <motion.div
            className="fixed right-0 top-0 z-50 h-full w-[480px] border-l border-[var(--border)] bg-[var(--surface-1)] shadow-2xl"
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ type: 'spring', stiffness: 320, damping: 32 }}
          >
            {/* Header */}
            <div className="flex items-center justify-between border-b border-[var(--border)] px-6 py-4">
              <div>
                <h2 className="text-base font-semibold text-[var(--text-primary)]">New Evaluation Task</h2>
                <p className="mt-0.5 text-xs text-[var(--text-muted)]">Step {step} of 2</p>
              </div>
              <button onClick={onClose} className="rounded-lg p-1.5 text-[var(--text-muted)] hover:bg-[var(--surface-3)] hover:text-[var(--text-primary)]">
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* Step indicators */}
            <div className="flex items-center gap-0 border-b border-[var(--border)] px-6 py-3">
              {[1, 2].map((s) => (
                <div key={s} className="flex items-center gap-2">
                  <div className={cn('flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold', s === step ? 'bg-[var(--brand-500)] text-white' : s < step ? 'bg-[var(--status-healthy)] text-white' : 'bg-[var(--surface-5)] text-[var(--text-muted)]')}>
                    {s < step ? <CheckCircle2 className="h-3.5 w-3.5" /> : s}
                  </div>
                  <span className={cn('text-xs', s === step ? 'font-medium text-[var(--text-primary)]' : 'text-[var(--text-muted)]')}>
                    {s === 1 ? 'Basic Info' : 'Configuration'}
                  </span>
                  {s < 2 && <ChevronRight className="mx-2 h-3 w-3 text-[var(--text-subtle)]" />}
                </div>
              ))}
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto px-6 py-5">
              <AnimatePresence mode="wait">
                {step === 1 && (
                  <motion.div
                    key="step1"
                    initial={{ opacity: 0, x: 20 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: -20 }}
                    className="space-y-5"
                  >
                    <div>
                      <label className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]">Task Name *</label>
                      <input
                        type="text"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        placeholder="e.g. Prompt Injection Resistance Test"
                        className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-subtle)] focus:border-[var(--brand-500)] focus:outline-none focus:ring-2 focus:ring-[var(--brand-500)]/20"
                      />
                    </div>

                    <div>
                      <label className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]">Agent</label>
                      <div className="space-y-2">
                        {mockAgents.slice(0, 4).map((agent) => (
                          <label
                            key={agent.id}
                            className={cn(
                              'flex cursor-pointer items-center gap-3 rounded-lg border p-3 transition-colors',
                              agentId === agent.id
                                ? 'border-[var(--brand-500)] bg-[var(--brand-500)]/5'
                                : 'border-[var(--border)] hover:bg-[var(--surface-3)]'
                            )}
                          >
                            <input type="radio" name="agent" value={agent.id} checked={agentId === agent.id} onChange={() => setAgentId(agent.id)} className="sr-only" />
                            <div className="flex h-7 w-7 items-center justify-center rounded-md bg-[var(--surface-5)]">
                              <Bot className="h-3.5 w-3.5 text-[var(--text-tertiary)]" />
                            </div>
                            <div className="flex-1 min-w-0">
                              <p className="text-sm font-medium text-[var(--text-primary)]">{agent.name}</p>
                              <p className="text-xs text-[var(--text-muted)] truncate">{agent.description}</p>
                            </div>
                            {agentId === agent.id && <CheckCircle2 className="h-4 w-4 text-[var(--brand-500)]" />}
                          </label>
                        ))}
                      </div>
                    </div>

                    <div>
                      <label className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]">Dataset</label>
                      <select
                        value={datasetId}
                        onChange={(e) => setDatasetId(e.target.value)}
                        className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 text-sm text-[var(--text-primary)] focus:border-[var(--brand-500)] focus:outline-none"
                      >
                        {datasets.filter(d => d.status === 'ready').map((d) => (
                          <option key={d.id} value={d.id}>{d.name} ({d.documentCount} docs)</option>
                        ))}
                      </select>
                    </div>
                  </motion.div>
                )}

                {step === 2 && (
                  <motion.div
                    key="step2"
                    initial={{ opacity: 0, x: 20 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: -20 }}
                    className="space-y-6"
                  >
                    {/* Summary */}
                    <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-4 space-y-2">
                      <p className="text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wide">Summary</p>
                      <div className="flex items-center gap-2 text-sm">
                        <span className="text-[var(--text-muted)]">Task:</span>
                        <span className="font-medium text-[var(--text-primary)]">{name}</span>
                      </div>
                      <div className="flex items-center gap-2 text-sm">
                        <span className="text-[var(--text-muted)]">Agent:</span>
                        <span className="text-[var(--text-primary)]">{selectedAgent?.name}</span>
                      </div>
                      <div className="flex items-center gap-2 text-sm">
                        <span className="text-[var(--text-muted)]">Dataset:</span>
                        <span className="text-[var(--text-primary)]">{selectedDataset?.name}</span>
                      </div>
                    </div>

                    <div>
                      <label className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]">
                        Sample Limit: <span className="text-[var(--brand-500)] font-semibold">{sampleLimit}</span>
                      </label>
                      <input
                        type="range"
                        min={100}
                        max={5000}
                        step={100}
                        value={sampleLimit}
                        onChange={(e) => setSampleLimit(Number(e.target.value))}
                        className="w-full accent-[var(--brand-500)]"
                      />
                      <div className="mt-1 flex justify-between text-[10px] text-[var(--text-subtle)]">
                        <span>100</span><span>5,000</span>
                      </div>
                    </div>

                    <div>
                      <label className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]">
                        Concurrent Workers: <span className="text-[var(--brand-500)] font-semibold">{concurrent}</span>
                      </label>
                      <input
                        type="range"
                        min={1}
                        max={8}
                        step={1}
                        value={concurrent}
                        onChange={(e) => setConcurrent(Number(e.target.value))}
                        className="w-full accent-[var(--brand-500)]"
                      />
                      <div className="mt-1 flex justify-between text-[10px] text-[var(--text-subtle)]">
                        <span>1</span><span>8</span>
                      </div>
                    </div>

                    <div className="rounded-xl border border-dashed border-[var(--brand-500)]/30 bg-[var(--brand-500)]/5 p-4">
                      <p className="text-xs text-[var(--brand-500)]">
                        Estimated completion: ~{Math.ceil(sampleLimit / (concurrent * 60))} min
                      </p>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>

            {/* Footer */}
            <div className="border-t border-[var(--border)] px-6 py-4 flex gap-3">
              {step > 1 && (
                <button
                  onClick={() => setStep(step - 1)}
                  className="flex-1 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-4 py-2 text-sm font-medium text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-3)]"
                >
                  Back
                </button>
              )}
              {step < 2 ? (
                <button
                  onClick={() => name.trim() && setStep(2)}
                  disabled={!name.trim()}
                  className={cn(
                    'flex-1 rounded-lg px-4 py-2 text-sm font-medium text-white transition-colors',
                    name.trim() ? 'bg-[var(--brand-500)] hover:opacity-90' : 'bg-[var(--surface-5)] cursor-not-allowed text-[var(--text-muted)]'
                  )}
                >
                  Next
                </button>
              ) : (
                <button
                  onClick={handleCreate}
                  className="flex-1 rounded-lg bg-[var(--brand-500)] px-4 py-2 text-sm font-medium text-white transition-colors hover:opacity-90"
                >
                  Create Task
                </button>
              )}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}

// ==================== Row Action Buttons ====================

function TaskActions({
  task,
  onStart,
  onPause,
  onResume,
  onCancel,
  onDelete,
  onDownload,
}: {
  task: EvaluationTask
  onStart: () => void
  onPause: () => void
  onResume: () => void
  onCancel: () => void
  onDelete: () => void
  onDownload: () => void
}) {
  const btnBase = 'rounded-md p-1.5 transition-colors'
  return (
    <div className="flex items-center gap-1">
      {task.status === 'pending' && (
        <>
          <button onClick={onStart} title="Start" className={cn(btnBase, 'text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-950/30')}>
            <Play className="h-3.5 w-3.5" />
          </button>
          <button onClick={onDelete} title="Delete" className={cn(btnBase, 'text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30')}>
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </>
      )}
      {task.status === 'running' && (
        <>
          <button onClick={onPause} title="Pause" className={cn(btnBase, 'text-orange-600 hover:bg-orange-50 dark:hover:bg-orange-950/30')}>
            <Pause className="h-3.5 w-3.5" />
          </button>
          <button onClick={onCancel} title="Cancel" className={cn(btnBase, 'text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30')}>
            <Square className="h-3.5 w-3.5" />
          </button>
        </>
      )}
      {task.status === 'paused' && (
        <>
          <button onClick={onResume} title="Resume" className={cn(btnBase, 'text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-950/30')}>
            <Play className="h-3.5 w-3.5" />
          </button>
          <button onClick={onCancel} title="Cancel" className={cn(btnBase, 'text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30')}>
            <Square className="h-3.5 w-3.5" />
          </button>
          <button onClick={onDelete} title="Delete" className={cn(btnBase, 'text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30')}>
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </>
      )}
      {(task.status === 'completed' || task.status === 'failed' || task.status === 'cancelled') && (
        <>
          <Link href={`/evaluate/${task.id}`} title="View Details" className={cn(btnBase, 'text-[var(--brand-500)] hover:bg-[var(--brand-500)]/10')}>
            <Eye className="h-3.5 w-3.5" />
          </Link>
          {task.status === 'completed' && (
            <button onClick={onDownload} title="Download Results" className={cn(btnBase, 'text-green-600 hover:bg-green-50 dark:hover:bg-green-950/30')}>
              <Download className="h-3.5 w-3.5" />
            </button>
          )}
          <button onClick={onDelete} title="Delete" className={cn(btnBase, 'text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30')}>
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </>
      )}
    </div>
  )
}

// ==================== Main Page ====================

export default function EvaluatePage() {
  const { t } = useTranslation()
  const [tasks, setTasks] = useState<EvaluationTask[]>(initialTasks)
  const [statusFilter, setStatusFilter] = useState<'' | EvalStatus>('')
  const [showCreate, setShowCreate] = useState(false)
  const [confirmState, setConfirmState] = useState<{
    open: boolean
    title: string
    description: string
    confirmLabel: string
    variant: 'danger' | 'warning'
    onConfirm: () => void
  }>({ open: false, title: '', description: '', confirmLabel: '', variant: 'danger', onConfirm: () => {} })

  // Auto-advance running tasks every 3s
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  useEffect(() => {
    timerRef.current = setInterval(() => {
      setTasks((prev) =>
        prev.map((t) => {
          if (t.status !== 'running') return t
          const newProgress = Math.min(t.progress + Math.random() * 3 + 1, 100)
          const newCompleted = Math.round((newProgress / 100) * t.totalSamples)
          if (newProgress >= 100) {
            return { ...t, progress: 100, completedSamples: t.totalSamples, status: 'completed', accuracy: 90 + Math.random() * 8, completedAt: new Date().toISOString() }
          }
          return { ...t, progress: Math.round(newProgress * 10) / 10, completedSamples: newCompleted }
        })
      )
    }, 3000)
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [])

  const filteredTasks = statusFilter ? tasks.filter((t) => t.status === statusFilter) : tasks

  const counts = {
    pending: tasks.filter((t) => t.status === 'pending').length,
    running: tasks.filter((t) => t.status === 'running').length,
    paused: tasks.filter((t) => t.status === 'paused').length,
    completed: tasks.filter((t) => t.status === 'completed').length,
    failed: tasks.filter((t) => t.status === 'failed').length,
    cancelled: tasks.filter((t) => t.status === 'cancelled').length,
  }

  function updateTask(id: string, updates: Partial<EvaluationTask>) {
    setTasks((prev) => prev.map((t) => (t.id === id ? { ...t, ...updates } : t)))
  }

  function handleStart(id: string) {
    updateTask(id, { status: 'running', startedAt: new Date().toISOString() })
    toastSuccess('Evaluation task started')
  }

  function handlePause(id: string) {
    updateTask(id, { status: 'paused' })
    toastInfo('Evaluation task paused')
  }

  function handleResume(id: string) {
    updateTask(id, { status: 'running' })
    toastSuccess('Evaluation task resumed')
  }

  function handleCancel(id: string) {
    setConfirmState({
      open: true,
      title: 'Cancel Evaluation',
      description: 'This will stop the evaluation and it cannot be resumed. Are you sure?',
      confirmLabel: 'Cancel Task',
      variant: 'warning',
      onConfirm: () => {
        updateTask(id, { status: 'cancelled', completedAt: new Date().toISOString() })
        setConfirmState((prev) => ({ ...prev, open: false }))
        toastInfo('Evaluation task cancelled')
      },
    })
  }

  function handleDelete(id: string) {
    setConfirmState({
      open: true,
      title: 'Delete Evaluation',
      description: 'This will permanently delete the evaluation task and all its data. This cannot be undone.',
      confirmLabel: 'Delete',
      variant: 'danger',
      onConfirm: () => {
        setTasks((prev) => prev.filter((t) => t.id !== id))
        setConfirmState((prev) => ({ ...prev, open: false }))
        toastSuccess('Evaluation task deleted')
      },
    })
  }

  function handleDownload(task: EvaluationTask) {
    toastSuccess(`Downloading results for "${task.name}"`)
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-[var(--text-primary)]">{t('evaluate.title')}</h1>
          <p className="mt-1 text-sm text-[var(--text-tertiary)]">{t('evaluate.subtitle')}</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 rounded-lg bg-[var(--brand-500)] px-4 py-2 text-sm font-medium text-white transition-colors hover:opacity-90"
        >
          <Plus className="h-4 w-4" />
          {t('evaluate.newEvaluation')}
        </button>
      </div>

      {/* Stat Cards */}
      <div className="mb-6 grid grid-cols-3 gap-3 sm:grid-cols-6">
        {([
          { key: 'pending', color: 'text-yellow-600', icon: Clock },
          { key: 'running', color: 'text-blue-600', icon: Play },
          { key: 'paused', color: 'text-orange-600', icon: Pause },
          { key: 'completed', color: 'text-green-600', icon: CheckCircle2 },
          { key: 'failed', color: 'text-red-600', icon: XCircle },
          { key: 'cancelled', color: 'text-gray-500', icon: Ban },
        ] as const).map((s, i) => {
          const Icon = s.icon
          return (
            <motion.button
              key={s.key}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.05 }}
              onClick={() => setStatusFilter(statusFilter === s.key ? '' : s.key)}
              className={cn(
                'rounded-xl border p-3 text-left transition-all',
                statusFilter === s.key
                  ? 'border-[var(--brand-500)] bg-[var(--brand-500)]/5'
                  : 'border-[var(--border)] bg-[var(--surface-2)] hover:border-[var(--brand-500)]/50'
              )}
            >
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-medium text-[var(--text-muted)] capitalize">{s.key}</span>
                <Icon className={cn('h-3.5 w-3.5', s.color)} />
              </div>
              <div className={cn('mt-1.5 text-xl font-bold', s.color)}>
                <CountUp end={counts[s.key]} duration={1} />
              </div>
            </motion.button>
          )
        })}
      </div>

      {/* Filter Tabs */}
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-1 rounded-lg bg-[var(--surface-3)] p-1">
          {FILTER_TABS.map((tab) => (
            <button
              key={tab.value}
              onClick={() => setStatusFilter(tab.value)}
              className={cn(
                'rounded-md px-3 py-1 text-xs font-medium transition-colors',
                statusFilter === tab.value
                  ? 'bg-[var(--surface-1)] text-[var(--text-primary)] shadow-sm'
                  : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
              )}
            >
              {tab.label}
              {tab.value !== '' && counts[tab.value] > 0 && (
                <span className="ml-1.5 rounded-full bg-[var(--surface-5)] px-1.5 py-0.5 text-[10px]">
                  {counts[tab.value]}
                </span>
              )}
            </button>
          ))}
        </div>
        <p className="text-xs text-[var(--text-muted)]">{filteredTasks.length} tasks</p>
      </div>

      {/* Tasks Table */}
      <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-2)] overflow-hidden">
        {/* Header */}
        <div className="border-b border-[var(--border)] px-4 py-2.5 flex items-center text-[11px] font-semibold text-[var(--text-muted)] uppercase tracking-wide bg-[var(--surface-3)]">
          <span className="flex-1 min-w-0">Task</span>
          <span className="w-36 hidden sm:block">Agent / Dataset</span>
          <span className="w-28 text-center hidden md:block">Started</span>
          <span className="w-24 text-center">Progress</span>
          <span className="w-20 text-center">Accuracy</span>
          <span className="w-24 text-center">Status</span>
          <span className="w-24 text-right">Actions</span>
        </div>

        <AnimatePresence initial={false}>
          {filteredTasks.length === 0 ? (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="flex flex-col items-center justify-center py-16 text-center"
            >
              <BarChart3 className="h-8 w-8 text-[var(--text-subtle)] mb-3" />
              <p className="text-sm text-[var(--text-muted)]">No evaluation tasks found</p>
            </motion.div>
          ) : (
            filteredTasks.map((task, i) => {
              const cfg = STATUS_CONFIG[task.status]
              const Icon = cfg.icon
              return (
                <motion.div
                  key={task.id}
                  layout
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ delay: i * 0.02 }}
                  className={cn(
                    'flex items-center px-4 py-3 transition-colors hover:bg-[var(--surface-3)]',
                    i < filteredTasks.length - 1 && 'border-b border-[var(--border)]'
                  )}
                >
                  <div className="flex-1 min-w-0 pr-3">
                    <Link href={`/evaluate/${task.id}`} className="hover:underline">
                      <p className="text-sm font-medium text-[var(--text-primary)] truncate">{task.name}</p>
                    </Link>
                    <p className="mt-0.5 text-[10px] text-[var(--text-subtle)]">{task.totalSamples} samples</p>
                  </div>

                  <div className="w-36 hidden sm:block min-w-0 pr-2">
                    <p className="flex items-center gap-1 text-xs text-[var(--text-muted)] truncate">
                      <Bot className="h-3 w-3 flex-shrink-0" /> {task.agentName}
                    </p>
                    <p className="flex items-center gap-1 text-[10px] text-[var(--text-subtle)] truncate">
                      <Database className="h-2.5 w-2.5 flex-shrink-0" /> {task.dataset}
                    </p>
                  </div>

                  <div className="w-28 text-center hidden md:block">
                    <span className="text-xs text-[var(--text-subtle)]">
                      {task.startedAt ? formatDate(task.startedAt) : '—'}
                    </span>
                  </div>

                  <div className="w-24 flex items-center justify-center gap-2">
                    <div className="h-1.5 w-14 rounded-full bg-[var(--surface-5)] overflow-hidden">
                      <motion.div
                        className="h-full rounded-full"
                        style={{ backgroundColor: task.status === 'failed' ? 'var(--status-offline)' : task.status === 'cancelled' ? 'var(--text-subtle)' : 'var(--brand-500)' }}
                        initial={{ width: 0 }}
                        animate={{ width: `${task.progress}%` }}
                        transition={{ duration: 0.5 }}
                      />
                    </div>
                    <span className="text-[10px] text-[var(--text-subtle)] w-7">{Math.round(task.progress)}%</span>
                  </div>

                  <span className="w-20 text-center text-xs font-medium text-[var(--text-primary)]">
                    {task.accuracy !== null ? `${task.accuracy.toFixed(1)}%` : '—'}
                  </span>

                  <div className="w-24 flex items-center justify-center">
                    <span className={cn('flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium', cfg.pill)}>
                      <Icon className="h-2.5 w-2.5" />
                      {cfg.label}
                    </span>
                  </div>

                  <div className="w-24 flex justify-end">
                    <TaskActions
                      task={task}
                      onStart={() => handleStart(task.id)}
                      onPause={() => handlePause(task.id)}
                      onResume={() => handleResume(task.id)}
                      onCancel={() => handleCancel(task.id)}
                      onDelete={() => handleDelete(task.id)}
                      onDownload={() => handleDownload(task)}
                    />
                  </div>
                </motion.div>
              )
            })
          )}
        </AnimatePresence>
      </div>

      {/* Create Drawer */}
      <CreateDrawer
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onCreate={(task) => setTasks((prev) => [task, ...prev])}
      />

      {/* Confirm Dialog */}
      <ConfirmDialog
        open={confirmState.open}
        title={confirmState.title}
        description={confirmState.description}
        confirmLabel={confirmState.confirmLabel}
        variant={confirmState.variant}
        onConfirm={confirmState.onConfirm}
        onCancel={() => setConfirmState((prev) => ({ ...prev, open: false }))}
      />
    </div>
  )
}
