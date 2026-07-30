'use client'

import { useState } from 'react'
import { useTranslation } from '@/lib/i18n'
import { Settings2 } from 'lucide-react'
import { Switch } from '@/components/ui/switch'
import type { AlertConfig } from '@/lib/managed/analytics/types'

interface AlertConfigPanelProps {
  config: AlertConfig
  onChange: (config: AlertConfig) => void
}

export function AlertConfigPanel({ config, onChange }: AlertConfigPanelProps) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)

  const updateRule = (key: keyof AlertConfig, patch: Partial<AlertConfig[keyof AlertConfig]>) => {
    onChange({ ...config, [key]: { ...config[key], ...patch } })
  }

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground"
        aria-label={t('analytics.alertConfig.title')}
      >
        <Settings2 className="h-4 w-4" />
      </button>

      {open && (
        <>
          {/* Backdrop */}
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          {/* Panel */}
          <div className="absolute right-0 top-8 z-50 w-[320px] rounded-lg border border-border bg-card p-4 shadow-lg">
            <h4 className="mb-3 text-sm font-medium text-foreground">
              {t('analytics.alertConfig.title')}
            </h4>
            <p className="mb-4 text-xs text-muted-foreground">
              {t('analytics.alertConfig.description')}
            </p>

            <div className="space-y-4">
              {/* Consecutive failures */}
              <div className="flex items-start gap-3">
                <Switch
                  checked={config.consecutive_failures.enabled}
                  onCheckedChange={(checked) =>
                    updateRule('consecutive_failures', { enabled: checked })
                  }
                />
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-foreground">
                    {t('analytics.alertConfig.consecutiveFailures')}
                  </p>
                  <div className="mt-1 flex items-center gap-2">
                    <span className="text-xs text-muted-foreground">
                      {t('analytics.alertConfig.threshold')}:
                    </span>
                    <input
                      type="number"
                      min={1}
                      max={10}
                      value={config.consecutive_failures.threshold}
                      onChange={(e) =>
                        updateRule('consecutive_failures', {
                          threshold: Number(e.target.value) || 3,
                        })
                      }
                      disabled={!config.consecutive_failures.enabled}
                      className="w-16 rounded-md border border-border bg-background px-2 py-0.5 text-xs disabled:opacity-50"
                    />
                    <span className="text-xs text-muted-foreground">
                      {t('analytics.alertConfig.times')}
                    </span>
                  </div>
                </div>
              </div>

              {/* Slow agent */}
              <div className="flex items-start gap-3">
                <Switch
                  checked={config.slow_agent.enabled}
                  onCheckedChange={(checked) => updateRule('slow_agent', { enabled: checked })}
                />
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-foreground">{t('analytics.alertConfig.slowAgent')}</p>
                  <div className="mt-1 flex items-center gap-2">
                    <span className="text-xs text-muted-foreground">
                      {t('analytics.alertConfig.threshold')}:
                    </span>
                    <input
                      type="number"
                      min={1}
                      max={600}
                      value={config.slow_agent.threshold / 1000}
                      onChange={(e) =>
                        updateRule('slow_agent', {
                          threshold: (Number(e.target.value) || 10) * 1000,
                        })
                      }
                      disabled={!config.slow_agent.enabled}
                      className="w-16 rounded-md border border-border bg-background px-2 py-0.5 text-xs disabled:opacity-50"
                    />
                    <span className="text-xs text-muted-foreground">s</span>
                  </div>
                </div>
              </div>

              {/* Token spike */}
              <div className="flex items-start gap-3">
                <Switch
                  checked={config.token_spike.enabled}
                  onCheckedChange={(checked) => updateRule('token_spike', { enabled: checked })}
                />
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-foreground">{t('analytics.alertConfig.tokenSpike')}</p>
                  <div className="mt-1 flex items-center gap-2">
                    <span className="text-xs text-muted-foreground">
                      {t('analytics.alertConfig.threshold')}:
                    </span>
                    <input
                      type="number"
                      min={5}
                      max={500}
                      value={config.token_spike.threshold}
                      onChange={(e) =>
                        updateRule('token_spike', { threshold: Number(e.target.value) || 30 })
                      }
                      disabled={!config.token_spike.enabled}
                      className="w-16 rounded-md border border-border bg-background px-2 py-0.5 text-xs disabled:opacity-50"
                    />
                    <span className="text-xs text-muted-foreground">%</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
