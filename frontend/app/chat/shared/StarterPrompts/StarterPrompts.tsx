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
          className="flex items-center gap-1.5 rounded-full border border-gray-200 bg-white px-3 py-1.5 text-xs text-gray-600 transition-all hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700"
        >
          <Lightbulb size={12} className="flex-shrink-0" />
          <span className="max-w-[250px] truncate">{prompt}</span>
        </button>
      ))}
    </div>
  )
}
