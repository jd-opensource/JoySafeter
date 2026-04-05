'use client'

import { Loader2, Send } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { apiStream } from '@/lib/api-client'
import { cn } from '@/lib/utils'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
}

export function OpenClawChat() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    const el = scrollRef.current
    if (el) {
      el.scrollTop = el.scrollHeight
    }
  }, [messages])

  const handleSend = useCallback(async () => {
    const text = input.trim()
    if (!text || isStreaming) return

    setInput('')

    const userMsg: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: text,
    }
    const assistantMsg: Message = {
      id: `asst-${Date.now()}`,
      role: 'assistant',
      content: '',
    }

    setMessages((prev) => [...prev, userMsg, assistantMsg])
    setIsStreaming(true)

    const allMessages = [...messages, userMsg].map((m) => ({
      role: m.role,
      content: m.content,
    }))

    const controller = new AbortController()
    abortRef.current = controller

    try {
      const response = await apiStream(
        'openclaw/chat',
        { messages: allMessages, model: 'openclaw:main', stream: true },
        { signal: controller.signal },
      )

      const reader = response.body?.getReader()
      if (!reader) return

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const dataStr = line.slice(6).trim()
          if (dataStr === '[DONE]') continue

          try {
            const data = JSON.parse(dataStr)
            const choices = data.choices ?? []
            const delta = choices[0]?.delta
            const content = delta?.content
            if (content) {
              setMessages((prev) => {
                const updated = [...prev]
                const last = updated[updated.length - 1]
                if (last?.role === 'assistant') {
                  updated[updated.length - 1] = { ...last, content: last.content + content }
                }
                return updated
              })
            }
          } catch {
            // ignore parse errors
          }
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') return
      setMessages((prev) => {
        const updated = [...prev]
        const last = updated[updated.length - 1]
        if (last?.role === 'assistant' && !last.content) {
          updated[updated.length - 1] = {
            ...last,
            content: `[Error] ${err instanceof Error ? err.message : 'Request failed'}`,
          }
        }
        return updated
      })
    } finally {
      setIsStreaming(false)
      abortRef.current = null
    }
  }, [input, isStreaming, messages])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        handleSend()
      }
    },
    [handleSend],
  )

  return (
    <Card className="flex h-full flex-col overflow-hidden">
      <CardHeader className="p-4 pb-2">
        <CardTitle className="text-sm font-medium">OpenClaw Chat</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col overflow-hidden p-0">
        <div ref={scrollRef} className="flex-1 overflow-auto px-4 py-3">
          {messages.length === 0 ? (
            <div className="flex h-full items-center justify-center text-sm text-[var(--text-tertiary)]">
              Send a message to start chatting with OpenClaw Agent
            </div>
          ) : (
            <div className="space-y-4">
              {messages.map((m) => (
                <div
                  key={m.id}
                  className={cn('flex', m.role === 'user' ? 'justify-end' : 'justify-start')}
                >
                  <div
                    className={cn(
                      'max-w-[80%] rounded-lg px-3 py-2 text-sm',
                      m.role === 'user'
                        ? 'bg-primary text-primary-foreground'
                        : 'bg-[var(--surface-3)] text-[var(--text-primary)]',
                    )}
                  >
                    <pre className="whitespace-pre-wrap break-words font-sans">
                      {m.content || (isStreaming && m.role === 'assistant' ? '...' : '')}
                    </pre>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="border-t border-[var(--border)] p-3">
          <div className="flex gap-2">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Type a message..."
              rows={1}
              className="flex-1 resize-none rounded-md border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:outline-none focus:ring-2 focus:ring-primary/40"
            />
            <Button
              onClick={handleSend}
              disabled={isStreaming || !input.trim()}
              size="sm"
              className="self-end"
            >
              {isStreaming ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
