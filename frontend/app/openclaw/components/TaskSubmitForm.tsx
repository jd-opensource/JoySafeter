'use client'

import { Loader2, Send } from 'lucide-react'
import { useCallback, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { apiPost } from '@/lib/api-client'

interface Props {
  onSubmitted: () => void
}

export function TaskSubmitForm({ onSubmitted }: Props) {
  const [title, setTitle] = useState('')
  const [input, setInput] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault()
      if (!title.trim()) return

      setSubmitting(true)
      setError(null)
      try {
        let inputData: Record<string, unknown> = {}
        if (input.trim()) {
          try {
            inputData = JSON.parse(input)
          } catch {
            inputData = { prompt: input }
          }
        }
        await apiPost('openclaw/tasks', {
          title: title.trim(),
          input_data: inputData,
        })
        setTitle('')
        setInput('')
        onSubmitted()
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : 'Unknown error')
      } finally {
        setSubmitting(false)
      }
    },
    [title, input, onSubmitted],
  )

  return (
    <Card>
      <CardHeader className="p-4 pb-2">
        <CardTitle className="text-sm font-medium">Submit Task</CardTitle>
      </CardHeader>
      <CardContent className="p-4 pt-2">
        <form onSubmit={handleSubmit} className="space-y-3">
          <input
            type="text"
            placeholder="Task title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="w-full rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:outline-none focus:ring-2 focus:ring-primary/40"
          />
          <textarea
            placeholder="Instructions or JSON payload..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            rows={4}
            className="w-full resize-none rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2 font-mono text-xs text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:outline-none focus:ring-2 focus:ring-primary/40"
          />
          {error && <p className="text-xs text-red-600">{error}</p>}
          <Button type="submit" size="sm" disabled={submitting || !title.trim()}>
            {submitting ? (
              <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Send className="mr-1 h-3.5 w-3.5" />
            )}
            Submit
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}
