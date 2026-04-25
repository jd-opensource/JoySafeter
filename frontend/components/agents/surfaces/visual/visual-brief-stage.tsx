'use client'

import { useMemo, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { useTranslation } from '@/lib/i18n'
import type { StageProps } from '@/components/agents/agent-build/agent-build-types'

export function VisualBriefStage({ agent, navigateToStage }: StageProps) {
  const { t } = useTranslation()
  const router = useRouter()
  const searchParams = useSearchParams()

  const [goal, setGoal] = useState(agent.description || '')
  const [input, setInput] = useState('')
  const [output, setOutput] = useState('')
  const [tools, setTools] = useState('')
  const [constraints, setConstraints] = useState('')
  const [scenario, setScenario] = useState('')

  const prompt = useMemo(
    () =>
      [
        `Build a Visual Agent named "${agent.name}".`,
        `Goal: ${goal || 'Not specified'}`,
        `Input: ${input || 'Not specified'}`,
        `Output: ${output || 'Not specified'}`,
        `Tools or Skills: ${tools || 'Not specified'}`,
        `Safety and human confirmation rules: ${constraints || 'Not specified'}`,
        `Business usage scenario: ${scenario || 'Not specified'}`,
        'Create an initial graph, add reasonable nodes and edges, and explain missing configuration.',
      ].join('\n'),
    [agent.name, constraints, goal, input, output, scenario, tools],
  )

  const handleGenerate = () => {
    const params = new URLSearchParams(searchParams.toString())
    params.set('stage', 'build')
    params.set('copilotInput', prompt)
    router.replace(`/agents/${agent.id}?${params.toString()}`, { scroll: false })
  }

  return (
    <div className="h-full overflow-y-auto bg-[var(--surface-1)]">
      <div className="mx-auto max-w-3xl px-8 py-8">
        <div className="mb-8">
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-[var(--text-muted)]">
            {t('agents.studio.brief.kicker', { defaultValue: 'First build step' })}
          </p>
          <h2 className="mt-2 text-3xl font-semibold text-[var(--text-primary)]">
            {t('agents.studio.brief.title', { defaultValue: 'Describe the Agent you want to build' })}
          </h2>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-[var(--text-secondary)]">
            {t('agents.studio.brief.subtitle', {
              defaultValue:
                'Copilot will turn this brief into an editable visual workflow. You can still skip and build manually on the canvas.',
            })}
          </p>
        </div>

        <div className="grid gap-5 rounded-2xl border border-[var(--border)] bg-[var(--surface-2)] p-5 shadow-sm">
          <div className="space-y-2">
            <Label>{t('agents.studio.brief.goal', { defaultValue: 'Goal' })}</Label>
            <Textarea value={goal} onChange={(e) => setGoal(e.target.value)} rows={3} />
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label>{t('agents.studio.brief.input', { defaultValue: 'Input' })}</Label>
              <Input value={input} onChange={(e) => setInput(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>{t('agents.studio.brief.output', { defaultValue: 'Output' })}</Label>
              <Input value={output} onChange={(e) => setOutput(e.target.value)} />
            </div>
          </div>
          <div className="space-y-2">
            <Label>{t('agents.studio.brief.tools', { defaultValue: 'Tools / Skills' })}</Label>
            <Input value={tools} onChange={(e) => setTools(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label>{t('agents.studio.brief.constraints', { defaultValue: 'Safety / approval rules' })}</Label>
            <Textarea value={constraints} onChange={(e) => setConstraints(e.target.value)} rows={2} />
          </div>
          <div className="space-y-2">
            <Label>{t('agents.studio.brief.scenario', { defaultValue: 'Business scenario' })}</Label>
            <Input value={scenario} onChange={(e) => setScenario(e.target.value)} />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => navigateToStage('build')}>
              {t('agents.studio.brief.skip', { defaultValue: 'Build manually' })}
            </Button>
            <Button onClick={handleGenerate} disabled={!goal.trim()}>
              {t('agents.studio.brief.generate', { defaultValue: 'Generate with Copilot' })}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
