'use client'

import { Check, Clock } from 'lucide-react'
import { useMemo, useState } from 'react'

import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { SearchableSelect } from '@/components/managed/schedules/searchable-select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useTranslation } from '@/lib/i18n'
import {
  CRON_PRESETS,
  COMMON_TIMEZONES,
  describeCron,
  isValidCron,
  nextRuns,
} from '@/lib/managed/cron'

interface CronEditorProps {
  value: string
  timezone: string
  onChange: (expr: string) => void
  onTimezoneChange: (tz: string) => void
  locale?: 'en' | 'zh'
}

type Frequency = 'minutely' | 'hourly' | 'daily' | 'weekly' | 'monthly'

const WEEKDAYS = [
  { value: 1, labelKey: 'managed.schedules.cron.weekday.mon' },
  { value: 2, labelKey: 'managed.schedules.cron.weekday.tue' },
  { value: 3, labelKey: 'managed.schedules.cron.weekday.wed' },
  { value: 4, labelKey: 'managed.schedules.cron.weekday.thu' },
  { value: 5, labelKey: 'managed.schedules.cron.weekday.fri' },
  { value: 6, labelKey: 'managed.schedules.cron.weekday.sat' },
  { value: 0, labelKey: 'managed.schedules.cron.weekday.sun' },
]

const pad = (n: number) => String(n).padStart(2, '0')
const range = (n: number) => Array.from({ length: n }, (_, i) => i)

/**
 * Rich cron editor: Presets / visual Builder / Advanced raw — three modes over
 * one cron string. Live human-readable description, next-N timezone-aware
 * preview, and inline validation on every mode.
 */
export function CronEditor({
  value,
  timezone,
  onChange,
  onTimezoneChange,
  locale = 'en',
}: CronEditorProps) {
  const { t } = useTranslation()

  // Builder state (used to synthesize a cron string in Builder mode).
  const [frequency, setFrequency] = useState<Frequency>('daily')
  const [everyN, setEveryN] = useState(5)
  const [minute, setMinute] = useState(0)
  const [hour, setHour] = useState(9)
  const [dom, setDom] = useState(1)
  const [weekdays, setWeekdays] = useState<number[]>([1, 2, 3, 4, 5])

  const valid = isValidCron(value)
  const description = useMemo(() => describeCron(value, locale), [value, locale])
  const previews = useMemo(() => nextRuns(value, timezone, 5), [value, timezone])
  const clearSearchLabel = t('managed.schedules.clearSearch')
  const noCronOptionMatch = t('managed.schedules.cron.noOptionMatch')
  const frequencyOptions = useMemo(
    () =>
      (['minutely', 'hourly', 'daily', 'weekly', 'monthly'] as Frequency[]).map((item) => ({
        value: item,
        label: t(`managed.schedules.cron.freq.${item}`),
        searchText: t(`managed.schedules.cron.freq.${item}`),
      })),
    [t],
  )

  const applyBuilder = (next: Partial<Record<string, unknown>>) => {
    const f = (next.frequency as Frequency) ?? frequency
    const n = (next.everyN as number) ?? everyN
    const mm = (next.minute as number) ?? minute
    const hh = (next.hour as number) ?? hour
    const d = (next.dom as number) ?? dom
    const wd = (next.weekdays as number[]) ?? weekdays
    let expr = '* * * * *'
    if (f === 'minutely') expr = `*/${Math.max(1, n)} * * * *`
    else if (f === 'hourly') expr = `${mm} * * * *`
    else if (f === 'daily') expr = `${mm} ${hh} * * *`
    else if (f === 'weekly')
      expr = `${mm} ${hh} * * ${(wd.length ? [...wd].sort((a, b) => a - b) : [1]).join(',')}`
    else if (f === 'monthly') expr = `${mm} ${hh} ${d} * *`
    onChange(expr)
  }

  const toggleWeekday = (day: number) => {
    const nextWd = weekdays.includes(day) ? weekdays.filter((w) => w !== day) : [...weekdays, day]
    setWeekdays(nextWd)
    applyBuilder({ weekdays: nextWd })
  }

  return (
    <div className="space-y-3">
      <Tabs defaultValue="builder">
        <TabsList className="grid w-full grid-cols-3">
          <TabsTrigger value="presets">{t('managed.schedules.cron.tabPresets')}</TabsTrigger>
          <TabsTrigger value="builder">{t('managed.schedules.cron.tabBuilder')}</TabsTrigger>
          <TabsTrigger value="advanced">{t('managed.schedules.cron.tabAdvanced')}</TabsTrigger>
        </TabsList>

        {/* Presets */}
        <TabsContent value="presets" className="mt-3">
          <div className="grid grid-cols-2 gap-2">
            {CRON_PRESETS.map((preset) => {
              const active = preset.expr === value
              return (
                <button
                  key={preset.expr}
                  type="button"
                  onClick={() => onChange(preset.expr)}
                  className={`flex items-center justify-between rounded-md border px-3 py-2 text-left text-sm transition-colors ${
                    active
                      ? 'border-primary bg-primary/5 text-foreground'
                      : 'border-border hover:bg-muted/50'
                  }`}
                >
                  <span>{t(preset.labelKey)}</span>
                  {active && <Check className="h-4 w-4 text-primary" />}
                </button>
              )
            })}
          </div>
        </TabsContent>

        {/* Visual builder */}
        <TabsContent value="builder" className="mt-3 space-y-3">
          <div className="space-y-1.5">
            <Label>{t('managed.schedules.cron.frequency')}</Label>
            <SearchableSelect
              value={frequency}
              onChange={(v) => {
                setFrequency(v as Frequency)
                applyBuilder({ frequency: v })
              }}
              options={frequencyOptions}
              searchPlaceholder={t('managed.schedules.cron.searchFrequency')}
              emptyText={noCronOptionMatch}
              clearSearchLabel={clearSearchLabel}
            />
          </div>

          {frequency === 'minutely' && (
            <div className="space-y-1.5">
              <Label>{t('managed.schedules.cron.everyNMinutes')}</Label>
              <SearchableSelect
                value={String(everyN)}
                onChange={(v) => {
                  setEveryN(Number(v))
                  applyBuilder({ everyN: Number(v) })
                }}
                options={[1, 2, 5, 10, 15, 20, 30].map((n) => ({ value: String(n), label: String(n), searchText: String(n) }))}
                searchPlaceholder={t('managed.schedules.cron.searchMinuteInterval')}
                emptyText={noCronOptionMatch}
                clearSearchLabel={clearSearchLabel}
              />
            </div>
          )}

          {frequency === 'hourly' && (
            <div className="space-y-1.5">
              <Label>{t('managed.schedules.cron.atMinute')}</Label>
              <MinuteSelect
                value={minute}
                searchPlaceholder={t('managed.schedules.cron.searchMinute')}
                emptyText={noCronOptionMatch}
                clearSearchLabel={clearSearchLabel}
                onChange={(m) => {
                  setMinute(m)
                  applyBuilder({ minute: m })
                }}
              />
            </div>
          )}

          {(frequency === 'daily' || frequency === 'weekly' || frequency === 'monthly') && (
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1.5">
                <Label>{t('managed.schedules.cron.hour')}</Label>
                <SearchableSelect
                  value={String(hour)}
                  onChange={(v) => {
                    setHour(Number(v))
                    applyBuilder({ hour: Number(v) })
                  }}
                  options={range(24).map((h) => ({ value: String(h), label: pad(h), searchText: `${h} ${pad(h)}` }))}
                  searchPlaceholder={t('managed.schedules.cron.searchHour')}
                  emptyText={noCronOptionMatch}
                  clearSearchLabel={clearSearchLabel}
                />
              </div>
              <div className="space-y-1.5">
                <Label>{t('managed.schedules.cron.minute')}</Label>
                <MinuteSelect
                  value={minute}
                  searchPlaceholder={t('managed.schedules.cron.searchMinute')}
                  emptyText={noCronOptionMatch}
                  clearSearchLabel={clearSearchLabel}
                  onChange={(m) => {
                    setMinute(m)
                    applyBuilder({ minute: m })
                  }}
                />
              </div>
            </div>
          )}

          {frequency === 'weekly' && (
            <div className="space-y-1.5">
              <Label>{t('managed.schedules.cron.onDays')}</Label>
              <div className="flex flex-wrap gap-1.5">
                {WEEKDAYS.map((d) => {
                  const active = weekdays.includes(d.value)
                  return (
                    <button
                      key={d.value}
                      type="button"
                      onClick={() => toggleWeekday(d.value)}
                      className={`rounded-md border px-2.5 py-1 text-xs transition-colors ${
                        active
                          ? 'border-primary bg-primary/10 text-foreground'
                          : 'border-border hover:bg-muted/50'
                      }`}
                    >
                      {t(d.labelKey)}
                    </button>
                  )
                })}
              </div>
            </div>
          )}

          {frequency === 'monthly' && (
            <div className="space-y-1.5">
              <Label>{t('managed.schedules.cron.dayOfMonth')}</Label>
              <SearchableSelect
                value={String(dom)}
                onChange={(v) => {
                  setDom(Number(v))
                  applyBuilder({ dom: Number(v) })
                }}
                options={range(31).map((d) => ({ value: String(d + 1), label: String(d + 1), searchText: String(d + 1) }))}
                searchPlaceholder={t('managed.schedules.cron.searchDayOfMonth')}
                emptyText={noCronOptionMatch}
                clearSearchLabel={clearSearchLabel}
              />
            </div>
          )}
        </TabsContent>

        {/* Advanced raw */}
        <TabsContent value="advanced" className="mt-3 space-y-1.5">
          <Label htmlFor="cron-expr">{t('managed.schedules.cron.expression')}</Label>
          <Input
            id="cron-expr"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder="*/5 * * * *"
            className="font-mono"
            aria-invalid={!valid}
          />
          <p className="text-xs text-muted-foreground">
            {t('managed.schedules.cron.advancedHint')}
          </p>
        </TabsContent>
      </Tabs>

      {/* Timezone */}
      <div className="space-y-1.5">
        <Label>{t('managed.schedules.cron.timezone')}</Label>
        <SearchableSelect
          value={timezone}
          onChange={onTimezoneChange}
          options={COMMON_TIMEZONES.map((tz) => ({ value: tz, label: tz, searchText: tz }))}
          searchPlaceholder={t('managed.schedules.cron.searchTimezone')}
          emptyText={noCronOptionMatch}
          clearSearchLabel={clearSearchLabel}
        />
      </div>

      {/* Live feedback: validity, description, next-N preview */}
      <div className="rounded-md border bg-muted/30 p-3 text-sm">
        {!valid ? (
          <p className="text-destructive">{t('managed.schedules.cron.invalid')}</p>
        ) : (
          <>
            <p className="font-medium text-foreground">{description}</p>
            {previews.length > 0 && (
              <div className="mt-2 space-y-1">
                <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Clock className="h-3 w-3" />
                  {t('managed.schedules.cron.nextRuns')}
                </p>
                <ul className="space-y-0.5 text-xs text-muted-foreground">
                  {previews.map((d, i) => (
                    <li key={i} className="font-mono">
                      {d.toLocaleString(undefined, { timeZone: timezone, hour12: false })}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function MinuteSelect({
  value,
  onChange,
  searchPlaceholder,
  emptyText,
  clearSearchLabel,
}: {
  value: number
  onChange: (m: number) => void
  searchPlaceholder: string
  emptyText: string
  clearSearchLabel: string
}) {
  return (
    <SearchableSelect
      value={String(value)}
      onChange={(v) => onChange(Number(v))}
      options={range(60).map((m) => ({ value: String(m), label: pad(m), searchText: `${m} ${pad(m)}` }))}
      searchPlaceholder={searchPlaceholder}
      emptyText={emptyText}
      clearSearchLabel={clearSearchLabel}
    />
  )
}
