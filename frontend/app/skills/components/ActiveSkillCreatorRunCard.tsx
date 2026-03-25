'use client'

import { ArrowUpRight, Bot, Loader2, Sparkles } from 'lucide-react'
import Link from 'next/link'
import { useEffect, useRef, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useActiveSkillCreatorRun } from '@/hooks/queries/runs'
import { useTranslation } from '@/lib/i18n'
import {
  applyRunEvent,
  applyRunSnapshot,
  applyRunStatus,
  buildRunHref,
  formatRelativeTime,
  formatRunStatus,
} from '@/lib/utils/runHelpers'
import { getRunWsClient } from '@/lib/ws/runs/runWsClient'
import type { RunSummary } from '@/services/runService'

export function ActiveSkillCreatorRunCard() {
  const { data: activeRun, isLoading } = useActiveSkillCreatorRun()
  const { t } = useTranslation()
  const runWsClientRef = useRef(getRunWsClient())
  const [liveRun, setLiveRun] = useState<RunSummary | null>(null)

  // Sync query result into liveRun, preserving WS-updated fields when fresher
  useEffect(() => {
    if (!activeRun) {
      setLiveRun(null)
      return
    }
    setLiveRun((current) => {
      if (!current || current.run_id !== activeRun.run_id) return activeRun
      // Keep WS-updated fields only if they are fresher (higher seq)
      const wsIsFresher = current.last_seq > activeRun.last_seq
      return {
        ...activeRun,
        status: wsIsFresher ? current.status : activeRun.status,
        last_seq: Math.max(current.last_seq, activeRun.last_seq),
        error_code: wsIsFresher ? (current.error_code ?? activeRun.error_code) : activeRun.error_code,
        error_message: wsIsFresher ? (current.error_message ?? activeRun.error_message) : activeRun.error_message,
      }
    })
  }, [activeRun])

  const lastSeqAtSubscribeRef = useRef(0)

  useEffect(() => {
    if (!activeRun?.run_id) {
      return
    }

    lastSeqAtSubscribeRef.current = activeRun.last_seq

    void runWsClientRef.current.subscribe(activeRun.run_id, lastSeqAtSubscribeRef.current, {
      onSnapshot: (frame) => {
        setLiveRun((current) => (current ? applyRunSnapshot(current, frame) : current))
      },
      onEvent: (frame) => {
        setLiveRun((current) => (current ? applyRunEvent(current, frame) : current))
      },
      onStatus: (frame) => {
        setLiveRun((current) => (current ? applyRunStatus(current, frame) : current))
      },
    })

    return () => {
      runWsClientRef.current.unsubscribe(activeRun.run_id)
    }
  }, [activeRun?.run_id])

  if (isLoading) {
    return (
      <div className="mb-4 px-6 pt-4">
        <Card className="border-[var(--border)] bg-[var(--surface-1)] p-4">
          <div className="flex items-center gap-3">
            <Skeleton className="h-10 w-10 rounded-xl" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-3 w-64" />
            </div>
            <Skeleton className="h-8 w-24 rounded-md" />
          </div>
        </Card>
      </div>
    )
  }

  if (!liveRun?.run_id) {
    return null
  }

  const href = buildRunHref(liveRun)

  return (
    <div className="mb-4 px-6 pt-4">
      <Card className="overflow-hidden border-[var(--skill-brand-200)] bg-[linear-gradient(135deg,var(--skill-brand-50),var(--surface-1))] p-4 shadow-sm">
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl border border-[var(--skill-brand-200)] bg-[var(--surface-elevated)] text-[var(--skill-brand-600)]">
              {liveRun.status === 'running' ? <Loader2 className="h-5 w-5 animate-spin" /> : <Bot className="h-5 w-5" />}
            </div>
            <div className="min-w-0">
              <div className="mb-1 flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-[var(--text-primary)]">
                  {t('runs.skillCreatorInProgress', 'Skill Creator in progress')}
                </span>
                <Badge
                  variant="outline"
                  className="border-[var(--skill-brand-200)] bg-[var(--surface-elevated)] text-[10px] text-[var(--skill-brand-700)]"
                >
                  {formatRunStatus(liveRun.status, t)}
                </Badge>
              </div>
              <p className="truncate text-sm text-[var(--text-secondary)]">
                {liveRun.title || t('runs.untitledSkillCreatorRun', 'Untitled Skill Creator run')}
              </p>
              <p className="mt-1 flex items-center gap-1 text-xs text-[var(--text-muted)]">
                <Sparkles className="h-3.5 w-3.5" />
                {t('runs.startedAt', 'Started')} {liveRun.started_at ? formatRelativeTime(liveRun.started_at, t) : ''}
              </p>
            </div>
          </div>

          <Button asChild className="gap-1.5 self-start md:self-center">
            <Link href={href}>
              {t('runs.resume', 'Resume')}
              <ArrowUpRight className="h-4 w-4" />
            </Link>
          </Button>
        </div>
      </Card>
    </div>
  )
}
