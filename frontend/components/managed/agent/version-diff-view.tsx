'use client'

import { useMemo } from 'react'

import { Badge } from '@/components/ui/badge'
import { useTranslation } from '@/lib/i18n'
import {
  diffAgents,
  type ArrayFieldDiff,
  type ObjectFieldDiff,
  type ScalarFieldDiff,
  type TextFieldDiff,
} from '@/lib/managed/agent-diff'
import type { Agent } from '@/types/managed'

const ENGINE_KIND_LABELS: Record<string, string> = {
  claude: 'Claude Code',
  claude_code: 'Claude Code',
  codex: 'Codex',
  native: 'Native',
}

interface Props {
  base: Agent | null | undefined
  target: Agent | null | undefined
  baseVersion: number
  targetVersion: number
}

export function VersionDiffView({ base, target, baseVersion, targetVersion }: Props) {
  const { t } = useTranslation()
  const d = useMemo(() => diffAgents(base, target), [base, target])

  return (
    <div className="mt-4 space-y-6">
      {/* Summary bar */}
      <div className="flex items-center gap-3 rounded-lg border bg-muted/40 px-4 py-2 text-sm">
        <span className="font-mono">v{baseVersion}</span>
        <span className="text-muted-foreground">→</span>
        <span className="font-mono">v{targetVersion}</span>
        <span className="ml-auto text-muted-foreground">
          {d.changedCount === 0
            ? t('managed.agents.detail.noChanges')
            : t('managed.agents.detail.changedCount', { count: d.changedCount })}
        </span>
      </div>

      <FieldSection
        title={t('managed.agents.engineKind')}
        diff={d.engine_kind}
        format={(v) => ENGINE_KIND_LABELS[v] || v || '-'}
      />
      <FieldSection title={t('managed.agents.description')} diff={d.description} />

      <ObjectFieldSection title={t('managed.agents.model')} diff={d.model} />

      <TextFieldSection title={t('managed.agents.systemPrompt')} diff={d.system} />

      <ArrayFieldSection
        title={t('managed.agents.tools')}
        diff={d.tools}
        renderItem={(item) =>
          (item as { name?: string; type?: string }).name || (item as { type?: string }).type || '-'
        }
      />
      <ArrayFieldSection
        title={t('managed.agents.mcpServers')}
        diff={d.mcp_servers}
        renderItem={(item) => {
          const m = item as { name?: string; url?: string }
          return m.url ? `${m.name || '?'} — ${m.url}` : m.name || '-'
        }}
      />
      <ArrayFieldSection
        title={t('managed.agents.skills')}
        diff={d.skills}
        renderItem={(item) => {
          const s = item as { skill_id?: string; version?: string; name?: string }
          const id = s.skill_id || s.name || '-'
          return s.version ? `${id} @ ${s.version}` : id
        }}
      />
    </div>
  )
}

// ---------- Field section components ----------

function UnchangedLabel() {
  const { t } = useTranslation()
  return (
    <span className="text-xs text-muted-foreground">{t('managed.agents.detail.unchanged')}</span>
  )
}

function FieldSection({
  title,
  diff,
  format,
}: {
  title: string
  diff: ScalarFieldDiff
  format?: (v: string) => string
}) {
  const fmt = format ?? ((v: string) => v || '-')
  return (
    <section>
      <h3 className="mb-1 flex items-center gap-2 text-sm font-medium text-foreground">
        {title}
        {!diff.changed && <UnchangedLabel />}
      </h3>
      {diff.changed ? (
        <div className="space-x-2 font-mono text-sm">
          <span className="text-red-700 line-through opacity-70 dark:text-red-400">
            {fmt(diff.before)}
          </span>
          <span className="text-muted-foreground">→</span>
          <span className="text-green-700 dark:text-green-400">{fmt(diff.after)}</span>
        </div>
      ) : (
        <p className="font-mono text-sm text-muted-foreground">{fmt(diff.before)}</p>
      )}
    </section>
  )
}

function ObjectFieldSection({ title, diff }: { title: string; diff: ObjectFieldDiff }) {
  const formatValue = (value: Record<string, unknown> | null) =>
    value == null ? '-' : JSON.stringify(value, null, 2)

  return (
    <section>
      <h3 className="mb-2 flex items-center gap-2 text-sm font-medium text-foreground">
        {title}
        {!diff.changed && <UnchangedLabel />}
      </h3>
      {diff.changed ? (
        <div className="grid grid-cols-2 gap-3 text-xs">
          <pre className="overflow-x-auto whitespace-pre-wrap rounded border border-red-500/20 bg-red-500/5 p-3 font-mono">
            {formatValue(diff.before)}
          </pre>
          <pre className="overflow-x-auto whitespace-pre-wrap rounded border border-green-500/20 bg-green-500/5 p-3 font-mono">
            {formatValue(diff.after)}
          </pre>
        </div>
      ) : (
        <pre className="overflow-x-auto whitespace-pre-wrap rounded-lg bg-muted p-3 font-mono text-xs">
          {formatValue(diff.before ?? diff.after)}
        </pre>
      )}
    </section>
  )
}

function TextFieldSection({ title, diff }: { title: string; diff: TextFieldDiff }) {
  if (!diff.changed && diff.lines.length === 0) {
    return (
      <section>
        <h3 className="mb-2 flex items-center gap-2 text-sm font-medium text-foreground">
          {title} <UnchangedLabel />
        </h3>
      </section>
    )
  }
  return (
    <section>
      <h3 className="mb-2 text-sm font-medium text-foreground">{title}</h3>
      <pre className="max-h-[400px] overflow-x-auto overflow-y-auto rounded-lg bg-muted p-0 font-mono text-xs leading-relaxed">
        {diff.lines.map((ln, i) => {
          const cls =
            ln.type === 'add'
              ? 'bg-green-500/10 text-green-700 dark:text-green-300'
              : ln.type === 'remove'
                ? 'bg-red-500/10 text-red-700 dark:text-red-300'
                : 'text-muted-foreground'
          const prefix = ln.type === 'add' ? '+ ' : ln.type === 'remove' ? '- ' : '  '
          return (
            <div key={i} className={`${cls} whitespace-pre-wrap px-3 py-0.5`}>
              {prefix}
              {ln.value}
            </div>
          )
        })}
      </pre>
    </section>
  )
}

function ArrayFieldSection<T>({
  title,
  diff,
  renderItem,
}: {
  title: string
  diff: ArrayFieldDiff<T>
  renderItem: (item: T) => string
}) {
  const { t } = useTranslation()
  return (
    <section>
      <h3 className="mb-2 flex items-center gap-2 text-sm font-medium text-foreground">
        {title}
        {!diff.changed && <UnchangedLabel />}
      </h3>
      {diff.changed ? (
        <ul className="space-y-1 text-sm">
          {diff.items
            .filter((i) => i.status !== 'unchanged')
            .map((item) => {
              const variant: 'default' | 'secondary' | 'destructive' | 'outline' =
                item.status === 'added'
                  ? 'default'
                  : item.status === 'removed'
                    ? 'destructive'
                    : 'secondary'
              const label =
                item.status === 'added'
                  ? t('managed.agents.detail.added')
                  : item.status === 'removed'
                    ? t('managed.agents.detail.removed')
                    : t('managed.agents.detail.modified')
              const display =
                item.status === 'modified'
                  ? `${renderItem(item.before as T)} → ${renderItem(item.after as T)}`
                  : renderItem((item.after || item.before) as T)
              return (
                <li key={item.key} className="flex items-center gap-2 font-mono text-xs">
                  <Badge variant={variant} className="shrink-0">
                    {label}
                  </Badge>
                  <span>{display}</span>
                </li>
              )
            })}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">
          {diff.items.length === 0
            ? '-'
            : diff.items.map((i) => renderItem((i.after || i.before) as T)).join(', ')}
        </p>
      )}
    </section>
  )
}
