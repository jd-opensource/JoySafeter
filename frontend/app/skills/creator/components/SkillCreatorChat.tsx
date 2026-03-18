'use client'

import { ArrowRight, Square, Loader2, Wand2, Bot, User } from 'lucide-react'
import React, { useRef, useEffect, useState, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'

import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/core/utils/cn'

import type { Message } from '@/app/chat/types'

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

const MessageBubble: React.FC<{ message: Message }> = ({ message }) => {
  const isUser = message.role === 'user'

  return (
    <div className={cn('flex gap-3 w-full', isUser ? 'justify-end' : 'justify-start')}>
      {/* Avatar */}
      {!isUser && (
        <div className="w-7 h-7 rounded-full bg-emerald-100 flex items-center justify-center flex-shrink-0 mt-0.5">
          <Bot size={14} className="text-emerald-600" />
        </div>
      )}

      {/* Content */}
      <div
        className={cn(
          'max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed',
          isUser
            ? 'bg-gray-900 text-white rounded-br-md'
            : 'bg-gray-50 text-gray-800 border border-gray-100 rounded-bl-md'
        )}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap">{message.content}</p>
        ) : (
          <div className="prose prose-sm max-w-none prose-p:my-1 prose-headings:my-2 prose-ul:my-1 prose-ol:my-1 prose-li:my-0.5">
            <ReactMarkdown>{message.content || (message.isStreaming ? '' : '...')}</ReactMarkdown>
            {message.isStreaming && (
              <span className="inline-block w-1.5 h-4 bg-emerald-500 rounded-sm animate-pulse ml-0.5 align-middle" />
            )}
          </div>
        )}

        {/* Tool calls indicator */}
        {message.tool_calls && message.tool_calls.length > 0 && (
          <div className="mt-2 space-y-1">
            {message.tool_calls.map((tc) => {
              const detail = tc.args?._detail as string | undefined
              return (
                <div
                  key={tc.id}
                  className={cn(
                    'text-[10px] px-2 py-1 rounded-md flex items-center gap-1.5',
                    tc.status === 'running'
                      ? 'bg-amber-50 text-amber-700 border border-amber-200'
                      : tc.status === 'completed'
                        ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                        : 'bg-red-50 text-red-600 border border-red-200'
                  )}
                >
                  {tc.status === 'running' && <Loader2 size={10} className="animate-spin" />}
                  <span className="font-medium">{tc.name}</span>
                  {detail && <span className="text-gray-400 font-mono truncate max-w-[180px]">{detail}</span>}
                  {tc.status === 'completed' && <span className="text-emerald-500 ml-auto">done</span>}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* User avatar */}
      {isUser && (
        <div className="w-7 h-7 rounded-full bg-gray-200 flex items-center justify-center flex-shrink-0 mt-0.5">
          <User size={14} className="text-gray-600" />
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

const SkillCreatorChat: React.FC<SkillCreatorChatProps> = ({
  messages,
  isProcessing,
  onSendMessage,
  onStop,
}) => {
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
    <div className="flex flex-col h-full">
      {/* Messages area */}
      <div className="flex-1 overflow-y-auto">
        {!hasMessages ? (
          /* Empty state */
          <div className="flex flex-col items-center justify-center h-full text-center px-8">
            <div className="w-14 h-14 rounded-2xl bg-emerald-50 flex items-center justify-center mb-4">
              <Wand2 size={24} className="text-emerald-500" />
            </div>
            <h3 className="text-lg font-semibold text-gray-800 mb-2">Skill Creator</h3>
            <p className="text-sm text-gray-500 max-w-md leading-relaxed">
              Describe the skill you want to create and the AI will generate the files for you.
              You can iterate on the result by continuing the conversation.
            </p>
            <div className="mt-6 flex flex-wrap gap-2 justify-center">
              {STARTER_PROMPTS.map((prompt, i) => (
                <button
                  key={i}
                  onClick={() => {
                    setInput(prompt.text)
                    textareaRef.current?.focus()
                  }}
                  className="text-xs px-3 py-1.5 rounded-full border border-gray-200 text-gray-600 hover:bg-gray-50 hover:border-gray-300 transition-colors"
                >
                  {prompt.label}
                </button>
              ))}
            </div>
          </div>
        ) : (
          /* Messages list */
          <div className="p-4 space-y-4">
            {messages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} />
            ))}
            <div ref={scrollEndRef} />
          </div>
        )}
      </div>

      {/* Input area */}
      <div className="border-t border-gray-100 bg-white p-4">
        <div className="flex items-end gap-2 bg-gray-50 border border-gray-200 rounded-2xl px-4 py-3">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Describe the skill you want to create..."
            className="flex-1 bg-transparent border-none shadow-none focus:outline-none resize-none text-sm placeholder:text-gray-400 min-h-[24px] max-h-[160px]"
            rows={1}
            disabled={isProcessing}
          />
          {isProcessing ? (
            <Button
              onClick={onStop}
              size="sm"
              className="w-8 h-8 rounded-full p-0 bg-red-500 hover:bg-red-600 flex-shrink-0"
              title="Stop"
            >
              <Square size={12} className="text-white fill-white" />
            </Button>
          ) : (
            <Button
              onClick={handleSubmit}
              disabled={!input.trim()}
              size="sm"
              className={cn(
                'w-8 h-8 rounded-full p-0 flex-shrink-0 transition-colors',
                input.trim()
                  ? 'bg-emerald-600 hover:bg-emerald-700'
                  : 'bg-gray-200 cursor-not-allowed'
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

export default SkillCreatorChat
