'use client'

import { useMemo, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Sparkles, Wrench } from 'lucide-react'

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

  const prompt = useMemo(
    () =>
      [
        `Build a Visual Agent named "${agent.name}".`,
        `Goal: ${goal || 'Not specified'}`,
        `Input: ${input || 'Not specified'}`,
        `Output: ${output || 'Not specified'}`,
        `Tools or Skills: ${tools || 'Not specified'}`,
        `Safety and human confirmation rules: ${constraints || 'Not specified'}`,
        'Create an initial graph, add reasonable nodes and edges, and explain missing configuration.',
      ].join('\n'),
    [agent.name, constraints, goal, input, output, tools],
  )

  const handleGenerate = () => {
    const params = new URLSearchParams(searchParams.toString())
    params.set('stage', 'build')
    params.set('copilotInput', prompt)
    router.replace(`/agents/${agent.id}?${params.toString()}`, { scroll: false })
  }

  return (
    <div className="flex h-full items-start justify-center overflow-y-auto bg-[var(--surface-1)] py-10">
      <div className="w-full max-w-2xl px-6">
        {/* Title */}
        <div className="mb-6 text-center">
          <h2 className="text-xl font-semibold text-[var(--text-primary)]">
            {t('agents.studio.brief.title', { defaultValue: 'Describe your Agent' })}
          </h2>
          <p className="mt-1.5 text-sm text-[var(--text-secondary)]">
            {t('agents.studio.brief.subtitle', {
              defaultValue:
                'Copilot will turn this into a visual workflow, or skip to build manually.',
            })}
          </p>
        </div>

        {/* Form */}
        <div className="space-y-4 rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-5">
          {/* Goal — primary field, larger */}
          <div className="space-y-1.5">
            <Label className="text-xs font-medium text-[var(--text-secondary)]">
              {t('agents.studio.brief.goal', { defaultValue: 'Goal' })} *
            </Label>
            <Textarea
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              rows={3}
              placeholder={t('agents.studio.brief.goalPlaceholder', {
                defaultValue:
                  'What should this agent do? e.g. "Analyze customer feedback and generate weekly reports"',
              })}
              className="resize-none"
            />
          </div>

          {/* Input / Output — side by side */}
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label className="text-xs font-medium text-[var(--text-secondary)]">
                {t('agents.studio.brief.input', { defaultValue: 'Input' })}
              </Label>
              <Input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder={t('agents.studio.brief.inputPlaceholder', {
                  defaultValue: 'e.g. CSV file, API request, user message',
                })}
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs font-medium text-[var(--text-secondary)]">
                {t('agents.studio.brief.output', { defaultValue: 'Output' })}
              </Label>
              <Input
                value={output}
                onChange={(e) => setOutput(e.target.value)}
                placeholder={t('agents.studio.brief.outputPlaceholder', {
                  defaultValue: 'e.g. JSON report, email, Slack message',
                })}
              />
            </div>
          </div>

          {/* Tools */}
          <div className="space-y-1.5">
            <Label className="text-xs font-medium text-[var(--text-secondary)]">
              {t('agents.studio.brief.tools', { defaultValue: 'Tools / Skills' })}
            </Label>
            <Input
              value={tools}
              onChange={(e) => setTools(e.target.value)}
              placeholder={t('agents.studio.brief.toolsPlaceholder', {
                defaultValue: 'e.g. Web search, database query, code execution',
              })}
            />
          </div>

          {/* Constraints */}
          <div className="space-y-1.5">
            <Label className="text-xs font-medium text-[var(--text-secondary)]">
              {t('agents.studio.brief.constraints', { defaultValue: 'Safety / approval rules' })}
            </Label>
            <Input
              value={constraints}
              onChange={(e) => setConstraints(e.target.value)}
              placeholder={t('agents.studio.brief.constraintsPlaceholder', {
                defaultValue: 'e.g. Require human approval before sending emails',
              })}
            />
          </div>
        </div>

        {/* Actions */}
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="outline" onClick={() => navigateToStage('build')} className="gap-1.5">
            <Wrench className="h-3.5 w-3.5" />
            {t('agents.studio.brief.skip', { defaultValue: 'Build manually' })}
          </Button>
          <Button onClick={handleGenerate} disabled={!goal.trim()} className="gap-1.5">
            <Sparkles className="h-3.5 w-3.5" />
            {t('agents.studio.brief.generate', { defaultValue: 'Generate with Copilot' })}
          </Button>
        </div>
      </div>
    </div>
  )
}
