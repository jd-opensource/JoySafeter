'use client'

import { Lightbulb } from 'lucide-react'

interface StarterPromptsProps {
  prompts: string[]
  onSelect: (prompt: string) => void
}

export function StarterPrompts({ prompts, onSelect }: StarterPromptsProps) {
  if (prompts.length === 0) return null

  return (
    <div className="flex flex-wrap gap-2">
      {prompts.map((prompt) => (
        <button
          key={prompt}
          onClick={() => onSelect(prompt)}
          className="flex items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--surface-elevated)] px-3 py-1.5 text-xs text-[var(--text-secondary)] transition-all hover:border-primary/30 hover:bg-[var(--brand-50)] hover:text-[var(--brand-700)]"
        >
          <Lightbulb size={12} className="flex-shrink-0" />
          <span className="max-w-[250px] truncate">{prompt}</span>
        </button>
      ))}
    </div>
  )
}
