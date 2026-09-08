'use client'

import { Check, CheckCircle2, ChevronDown, Copy } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

export function QuickstartApiCard({ endpoint, curl }: { endpoint: string; curl: string }) {
  const [copied, setCopied] = useState(false)
  const copiedResetTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(
    () => () => {
      if (copiedResetTimerRef.current) clearTimeout(copiedResetTimerRef.current)
    },
    [],
  )

  const handleCopy = () => {
    navigator.clipboard.writeText(curl)
    if (copiedResetTimerRef.current) clearTimeout(copiedResetTimerRef.current)
    setCopied(true)
    copiedResetTimerRef.current = setTimeout(() => {
      setCopied(false)
      copiedResetTimerRef.current = null
    }, 2000)
  }

  return (
    <div className="rounded-xl border border-border bg-background">
      <div className="flex items-center justify-between border-b border-border px-3 py-2 text-xs">
        <div className="flex items-center gap-2">
          <span className="rounded bg-muted px-1.5 py-0.5 font-semibold text-blue-600 dark:text-blue-400">
            POST
          </span>
          <span className="font-mono text-[12px] text-foreground">{endpoint}</span>
        </div>
        <div className="flex items-center gap-2 text-muted-foreground">
          <span className="flex items-center gap-1">
            cURL
            <ChevronDown className="h-3.5 w-3.5" />
          </span>
          <button
            type="button"
            onClick={handleCopy}
            className="transition-colors hover:text-foreground"
          >
            {copied ? (
              <Check className="h-3.5 w-3.5 text-green-500" />
            ) : (
              <Copy className="h-3.5 w-3.5" />
            )}
          </button>
        </div>
      </div>
      <pre className="max-h-[320px] overflow-auto px-3 py-2 font-mono text-[12px] leading-6 text-foreground/90">
        {curl}
      </pre>
    </div>
  )
}

export function QuickstartNumberedChoiceList({
  question,
  hint,
  choices,
  onSelect,
  onSkip,
}: {
  question: string
  hint?: string
  choices: { num: number; label: string; arrow?: boolean }[]
  onSelect: (num: number) => void
  onSkip?: () => void
}) {
  const { t } = useTranslation()

  return (
    <div className="rounded-xl border border-border bg-background p-4">
      <p className="mb-1 text-[14px] font-semibold text-foreground">{question}</p>
      {hint ? <p className="text-xs leading-5 text-muted-foreground">{hint}</p> : null}
      <div className="mt-2 space-y-0.5">
        {choices.map((choice) => (
          <button
            key={choice.num}
            type="button"
            onClick={() => onSelect(choice.num)}
            className="flex w-full items-center gap-3 rounded-lg px-2 py-2.5 text-left transition-colors hover:bg-muted/50"
          >
            <span
              className={cn(
                'w-5 shrink-0 text-right text-sm',
                choice.num === 0 ? 'italic text-muted-foreground/60' : 'text-muted-foreground',
              )}
            >
              {choice.num}
            </span>
            <span
              className={cn(
                'flex-1 text-[14px]',
                choice.num === 0 ? 'text-muted-foreground' : 'text-foreground',
              )}
            >
              {choice.label}
            </span>
            {choice.arrow ? <span className="text-sm text-muted-foreground">&rarr;</span> : null}
          </button>
        ))}
      </div>
      {onSkip ? (
        <div className="mt-2 flex justify-end">
          <Button
            variant="ghost"
            size="sm"
            className="text-xs text-muted-foreground"
            onClick={onSkip}
          >
            {t('common.skip')}
          </Button>
        </div>
      ) : null}
    </div>
  )
}

export function QuickstartQADisplay({ question, answer }: { question: string; answer: string }) {
  const { t } = useTranslation()

  return (
    <div className="flex justify-end">
      <div className="max-w-[365px] rounded-2xl bg-muted p-4 text-[14px] leading-7 text-foreground/90">
        <div className="whitespace-pre-wrap">
          <span className="font-semibold">{t('managed.quickstart.questionLabel')}:</span> {question}
          {'\n'}
          <span className="font-semibold">{t('managed.quickstart.answerLabel')}:</span> {answer}
        </div>
      </div>
    </div>
  )
}

export function QuickstartStepDoneBadge({
  label,
  curl,
  endpoint,
}: {
  label: string
  curl?: string
  endpoint?: string
}) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="rounded-xl border border-border bg-muted/30 p-3">
      <button
        type="button"
        className="flex w-full items-center gap-2 text-left text-sm"
        onClick={() => setExpanded(!expanded)}
      >
        <CheckCircle2 className="h-4 w-4 shrink-0 text-muted-foreground" />
        <span className="flex-1 font-semibold text-foreground">{label}</span>
        <ChevronDown
          className={cn(
            'h-3.5 w-3.5 text-muted-foreground transition-transform',
            expanded && 'rotate-180',
          )}
        />
      </button>
      {expanded && curl && endpoint ? (
        <div className="mt-3">
          <QuickstartApiCard endpoint={endpoint} curl={curl} />
        </div>
      ) : null}
    </div>
  )
}
