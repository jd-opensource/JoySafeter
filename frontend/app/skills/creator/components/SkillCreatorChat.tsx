'use client'

import { ArrowRight, Square, Wand2, Bot, User } from 'lucide-react'
import React, { useRef, useEffect, useState, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

import type { Message } from '@/app/chat/types'
import { ToolCallBadge } from '@/app/chat/shared/ToolCallDisplay'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface SkillCreatorChatProps {
  messages: Message[]
  isProcessing: boolean
  onSendMessage: (text: string) => void
  onStop: () => void
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
        <div className="mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-emerald-100">
          <Bot size={14} className="text-emerald-600" />
        </div>
      )}

      {/* Content */}
      <div
        className={cn(
          'max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed',
          isUser
            ? 'rounded-br-md bg-gray-900 text-white'
            : 'rounded-bl-md border border-gray-100 bg-gray-50 text-gray-800',
        )}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap">{message.content}</p>
        ) : (
          <div className="prose prose-sm max-w-none prose-headings:my-2 prose-p:my-1 prose-ol:my-1 prose-ul:my-1 prose-li:my-0.5">
            <ReactMarkdown>{message.content || (message.isStreaming ? '' : '...')}</ReactMarkdown>
            {message.isStreaming && (
              <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse rounded-sm bg-emerald-500 align-middle" />
            )}
          </div>
        )}

        {/* Tool calls indicator */}
        {message.tool_calls && message.tool_calls.length > 0 && (
          <div className="mt-2 space-y-1">
            {message.tool_calls.map((tc) => (
              <ToolCallBadge
                key={tc.id}
                name={tc.args?._rawName || tc.name}
                args={tc.args || {}}
                status={tc.status}
              />
            ))}
          </div>
        )}
      </div>

      {/* User avatar */}
      {isUser && (
        <div className="mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-gray-200">
          <User size={14} className="text-gray-600" />
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

  const handleSubmit = useCallback(() => {
    const text = input.trim()
    if (!text || isProcessing) return
    onSendMessage(text)
    setInput('')
  }, [input, isProcessing, onSendMessage])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
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
            <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-50">
              <Wand2 size={24} className="text-emerald-500" />
            </div>
            <h3 className="mb-2 text-lg font-semibold text-gray-800">Skill Creator</h3>
            <p className="max-w-md text-sm leading-relaxed text-gray-500">
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
                  className="rounded-full border border-gray-200 px-3 py-1.5 text-xs text-gray-600 transition-colors hover:border-gray-300 hover:bg-gray-50"
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
      <div className="border-t border-gray-100 bg-white p-4">
        <div className="flex items-end gap-2 rounded-2xl border border-gray-200 bg-gray-50 px-4 py-3">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Describe the skill you want to create..."
            className="max-h-[160px] min-h-[24px] flex-1 resize-none border-none bg-transparent text-sm shadow-none placeholder:text-gray-400 focus:outline-none"
            rows={1}
            disabled={isProcessing}
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
              onClick={handleSubmit}
              disabled={!input.trim()}
              size="sm"
              className={cn(
                'h-8 w-8 flex-shrink-0 rounded-full p-0 transition-colors',
                input.trim()
                  ? 'bg-emerald-600 hover:bg-emerald-700'
                  : 'cursor-not-allowed bg-gray-200',
              )}
            >
              <ArrowRight size={14} className={input.trim() ? 'text-white' : 'text-gray-400'} />
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
