'use client'

import { ArrowRight, Square, Wand2, Bot, User } from 'lucide-react'
import React, { useRef, useEffect, useState, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'

import { ToolCallBadge } from '@/app/chat/shared/ToolCallDisplay'
import type { Message } from '@/app/chat/types'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'


// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface SkillCreatorChatProps {
  messages: Message[]
  isProcessing: boolean
  isSubmitting?: boolean
  inputDisabled?: boolean
  onSendMessage: (text: string) => Promise<boolean>
  onStop: () => void
}

function summarizeToolResult(rawName: string, result: unknown): string | null {
  if (rawName !== 'preview_skill' || result == null) return null

  try {
    const parsed = typeof result === 'string' ? JSON.parse(result) : result
    if (!parsed || typeof parsed !== 'object') return 'Preview completed'

    const preview = parsed as {
      files?: Array<unknown>
      validation?: { valid?: boolean; errors?: Array<unknown> }
    }
    const fileCount = Array.isArray(preview.files) ? preview.files.length : 0
    const errorCount = Array.isArray(preview.validation?.errors) ? preview.validation.errors.length : 0

    if (preview.validation?.valid === true) {
      return `Preview ready: ${fileCount} file${fileCount === 1 ? '' : 's'}, validation passed`
    }
    if (preview.validation?.valid === false) {
      return `Preview failed: ${errorCount} validation error${errorCount === 1 ? '' : 's'}`
    }
  } catch {
    return 'Preview completed'
  }

  return 'Preview completed'
}

// ---------------------------------------------------------------------------
// Message bubble
// ---------------------------------------------------------------------------

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user'

  return (
    <div className={cn('flex w-full gap-3', isUser ? 'justify-end' : 'justify-start')}>
      {/* Avatar */}
      {!isUser && (
        <div className="mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-[var(--skill-brand-100)]">
          <Bot size={14} className="text-[var(--skill-brand-600)]" />
        </div>
      )}

      {/* Content */}
      <div
        className={cn(
          'max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed',
          isUser
            ? 'rounded-br-md bg-gray-900 text-white'
            : 'rounded-bl-md border border-[var(--border-muted)] bg-[var(--surface-2)] text-[var(--text-primary)]',
        )}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap">{message.content}</p>
        ) : (
          <div className="prose prose-sm max-w-none prose-headings:my-2 prose-p:my-1 prose-ol:my-1 prose-ul:my-1 prose-li:my-0.5">
            <ReactMarkdown>{message.content || (message.isStreaming ? '' : '...')}</ReactMarkdown>
            {message.isStreaming && (
              <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse rounded-sm bg-[var(--skill-brand)] align-middle" />
            )}
          </div>
        )}

        {/* Tool calls indicator */}
        {message.tool_calls && message.tool_calls.length > 0 && (
          <div className="mt-2 space-y-1">
            {message.tool_calls.map((tc) => {
              const rawName = (tc.args?._rawName as string) || tc.name
              const summary = summarizeToolResult(rawName, tc.result)

              return (
                <div key={tc.id}>
                  <ToolCallBadge
                    name={rawName}
                    args={tc.args as Record<string, any> || {}}
                    status={tc.status}
                  />
                  {summary && (
                    <p className="mt-1 text-xs text-[var(--text-tertiary)]">
                      {summary}
                    </p>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* User avatar */}
      {isUser && (
        <div className="mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-[var(--surface-5)]">
          <User size={14} className="text-[var(--text-secondary)]" />
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function SkillCreatorChat({
  messages,
  isProcessing,
  isSubmitting = false,
  inputDisabled = false,
  onSendMessage,
  onStop,
}: SkillCreatorChatProps) {
  const [input, setInput] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const scrollEndRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    scrollEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 160)}px`
    }
  }, [input])

  const handleSubmit = useCallback(async () => {
    const text = input.trim()
    if (!text || isProcessing || isSubmitting || inputDisabled) return
    const sent = await onSendMessage(text)
    if (sent) {
      setInput('')
    }
  }, [input, inputDisabled, isProcessing, isSubmitting, onSendMessage])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void handleSubmit()
    }
  }

  const hasMessages = messages.length > 0

  return (
    <div className="flex h-full flex-col">
      {/* Messages area */}
      <div className="flex-1 overflow-y-auto">
        {!hasMessages ? (
          /* Empty state */
          <div className="flex h-full flex-col items-center justify-center px-8 text-center">
            <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-[var(--skill-brand-50)]">
              <Wand2 size={24} className="text-[var(--skill-brand)]" />
            </div>
            <h3 className="mb-2 text-lg font-semibold text-[var(--text-primary)]">Skill Creator</h3>
            <p className="max-w-md text-sm leading-relaxed text-[var(--text-tertiary)]">
              Describe the skill you want to create and the AI will generate the files for you. You
              can iterate on the result by continuing the conversation.
            </p>
            <div className="mt-6 flex flex-wrap justify-center gap-2">
              {STARTER_PROMPTS.map((prompt, i) => (
                <button
                  key={i}
                  onClick={() => {
                    setInput(prompt.text)
                    textareaRef.current?.focus()
                  }}
                  className="rounded-full border border-[var(--border)] px-3 py-1.5 text-xs text-[var(--text-secondary)] transition-colors hover:border-[var(--border-strong)] hover:bg-[var(--surface-2)]"
                >
                  {prompt.label}
                </button>
              ))}
            </div>
          </div>
        ) : (
          /* Messages list */
          <div className="space-y-4 p-4">
            {messages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} />
            ))}
            <div ref={scrollEndRef} />
          </div>
        )}
      </div>

      {/* Input area */}
      <div className="border-t border-[var(--border-muted)] bg-[var(--surface-elevated)] p-4">
        <div className="flex items-end gap-2 rounded-2xl border border-[var(--border)] bg-[var(--surface-2)] px-4 py-3">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={inputDisabled ? 'Initializing Skill Creator...' : 'Describe the skill you want to create...'}
            className="max-h-[160px] min-h-[24px] flex-1 resize-none border-none bg-transparent text-sm shadow-none placeholder:text-[var(--text-muted)] focus:outline-none"
            rows={1}
            disabled={isProcessing || isSubmitting || inputDisabled}
          />
          {isProcessing ? (
            <Button
              onClick={onStop}
              size="sm"
              className="h-8 w-8 flex-shrink-0 rounded-full bg-red-500 p-0 hover:bg-red-600"
              title="Stop"
            >
              <Square size={12} className="fill-white text-white" />
            </Button>
          ) : (
            <Button
              onClick={() => {
                void handleSubmit()
              }}
              disabled={!input.trim() || inputDisabled || isSubmitting}
              size="sm"
              className={cn(
                'h-8 w-8 flex-shrink-0 rounded-full p-0 transition-colors',
                input.trim() && !inputDisabled
                  ? 'bg-[var(--skill-brand-600)] hover:bg-[var(--skill-brand-700)]'
                  : 'cursor-not-allowed bg-[var(--surface-5)]',
              )}
            >
              <ArrowRight size={14} className={input.trim() ? 'text-white' : 'text-[var(--text-muted)]'} />
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Starter prompts
// ---------------------------------------------------------------------------

const STARTER_PROMPTS = [
  {
    label: 'Code review skill',
    text: 'Create a skill that performs thorough code review, checking for security issues, performance problems, and best practices.',
  },
  {
    label: 'API tester',
    text: 'Create a skill that tests REST APIs by sending requests and validating responses against expected schemas.',
  },
  {
    label: 'Log analyzer',
    text: 'Create a skill that analyzes application logs to identify errors, patterns, and anomalies.',
  },
]
