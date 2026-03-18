'use client'

import { Compass, Globe2, Radar, Sparkles } from 'lucide-react'

import { useTranslation } from '@/lib/i18n'

const discoverySignals = [
  {
    label: 'Threat briefs',
    value: '18',
    detail: 'Curated intelligence cards prepared for leadership review.',
    icon: Globe2,
  },
  {
    label: 'Market motions',
    value: '07',
    detail: 'Ecosystem changes surfaced for strategic prioritization.',
    icon: Radar,
  },
  {
    label: 'Executive notes',
    value: '12',
    detail: 'Saved prompts, references, and decision shortcuts for teams.',
    icon: Sparkles,
  },
]

export default function DiscoverPage() {
  const { t } = useTranslation()

  return (
    <div className="executive-page executive-shell">
      <div className="executive-page-content space-y-6">
        <header className="executive-header">
          <div className="space-y-4">
            <div className="executive-kicker">
              <Compass className="h-3.5 w-3.5" />
              Discovery Desk
            </div>
            <div className="space-y-3">
              <h1 className="max-w-3xl text-4xl font-semibold tracking-[-0.05em] text-[var(--text-primary)]">
                {t('sidebar.discover')}
              </h1>
              <p className="max-w-2xl text-sm leading-6 text-[var(--text-secondary)]">
                A reserved space for strategic feeds, curated briefs, and signal
                tracking designed for leadership teams.
              </p>
            </div>
          </div>
        </header>

        <section className="grid gap-4 lg:grid-cols-[1.45fr_0.95fr]">
          <div className="surface-panel relative overflow-hidden px-6 py-7 sm:px-8">
            <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-[var(--brand-indigo)] to-transparent" />
            <div className="space-y-6">
              <div className="space-y-3">
                <div className="section-label">Editorial Queue</div>
                <div className="executive-rule" />
                <h2 className="max-w-2xl text-3xl font-semibold tracking-[-0.045em] text-[var(--text-primary)]">
                  {t('sidebar.discoverComingSoon')}
                </h2>
                <p className="max-w-xl text-sm leading-6 text-[var(--text-secondary)]">
                  We reserved this surface for curated external intelligence and
                  internal signal synthesis. When enabled, it will read more like
                  an executive briefing than a tool catalog.
                </p>
              </div>

              <div className="grid gap-3 md:grid-cols-3">
                {discoverySignals.map(({ label, value, detail, icon: Icon }) => (
                  <article
                    key={label}
                    className="surface-panel-flat min-h-[172px] space-y-4 px-5 py-5"
                  >
                    <div className="flex items-center justify-between">
                      <div className="quiet-badge">
                        <Icon className="h-3.5 w-3.5" />
                        {label}
                      </div>
                      <span className="text-xs uppercase tracking-[0.18em] text-[var(--text-muted)]">
                        queued
                      </span>
                    </div>
                    <div className="metric-value text-[2.2rem]">{value}</div>
                    <p className="text-sm leading-6 text-[var(--text-secondary)]">
                      {detail}
                    </p>
                  </article>
                ))}
              </div>
            </div>
          </div>

          <aside className="surface-panel px-6 py-7 sm:px-7">
            <div className="space-y-4">
              <div className="section-label">Mandate</div>
              <div className="executive-rule" />
              <p className="text-sm leading-7 text-[var(--text-secondary)]">
                Discovery is being positioned as a quiet reading room for
                decision-makers. The goal is to surface only the information that
                changes a plan, budget, or response posture.
              </p>
              <div className="surface-panel-flat space-y-3 px-5 py-5">
                <div className="quiet-badge">Preview Scope</div>
                <ul className="space-y-3 text-sm leading-6 text-[var(--text-secondary)]">
                  <li>Signal curation for strategic cyber developments.</li>
                  <li>Cross-workspace briefs prepared for leadership review.</li>
                  <li>Shared narrative summaries instead of raw activity feeds.</li>
                </ul>
              </div>
            </div>
          </aside>
        </section>
      </div>
    </div>
  )
}
