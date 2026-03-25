'use client'

import DOMPurify from 'dompurify'
import { motion } from 'framer-motion'
import type { Variants } from 'framer-motion'
import { User, Bot } from 'lucide-react'
import React, { useMemo } from 'react'
import ReactMarkdown from 'react-markdown'

import { ActionBar } from '../shared/ActionBar'
import { CodeBlock } from '../shared/CodeBlock'
import { ToolCallBadge } from '../shared/ToolCallDisplay'
import { Message, ToolCall } from '../types'

// ─── Hoisted constants (stable references, no per-render allocation) ─────────

const SANITIZE_CONFIG = {
  ALLOWED_TAGS: [
    'p', 'br', 'strong', 'em', 'code', 'pre', 'blockquote',
    'ul', 'ol', 'li', 'a', 'img',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr',
    'div', 'span', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'details', 'summary', 'sup', 'sub', 'del', 's', 'ins', 'mark',
    'abbr', 'b', 'i', 'u', 'small', 'tt', 'kbd', 'samp', 'var',
  ],
  ALLOWED_ATTR: [
    'href', 'src', 'alt', 'title', 'class', 'id',
    'width', 'height', 'target', 'rel', 'name', 'open',
  ],
  ALLOW_DATA_ATTR: false,
  ALLOW_UNKNOWN_PROTOCOLS: false,
  ADD_ATTR: ['rel'],
  FORBID_TAGS: ['script', 'style', 'iframe', 'form', 'input', 'button'],
  FORBID_ATTR: ['onerror', 'onload', 'onclick', 'onmouseover', 'onfocus', 'onblur'],
}

const markdownComponents = {
  code({ node: _node, inline, className, children, ...props }: any) {
    const match = /language-(\w+)/.exec(className || '')
    const content = String(children).replace(/\n$/, '')

    return !inline && match ? (
      <CodeBlock language={match[1]} code={content} />
    ) : (
      <code
        {...props}
        className="rounded border border-[var(--border)] bg-[var(--surface-3)] px-1.5 py-0.5 font-mono text-xs text-[var(--text-primary)]"
      >
        {children}
      </code>
    )
  },
}

const messageVariants: Variants = {
  hidden: { opacity: 0, y: 8 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.2, ease: 'easeOut' } },
}

// ─── Component ───────────────────────────────────────────────────────────────

interface MessageItemProps {
  message: Message
  onToolClick?: (toolCall: ToolCall) => void
  onRetry?: () => void
}

export default function MessageItem({ message, onToolClick, onRetry }: MessageItemProps) {
  const isUser = message.role === 'user'

  const sanitizedContent = useMemo(
    () => (message.content ? DOMPurify.sanitize(message.content, SANITIZE_CONFIG) : ''),
    [message.content],
  )

  if (isUser) {
    return (
      <motion.div
        className="mb-6 flex justify-end"
        variants={messageVariants}
        initial="hidden"
        animate="visible"
      >
        <div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-[var(--surface-12)] px-5 py-3.5 text-white shadow-sm">
          <p className="whitespace-pre-wrap text-[15px] font-normal leading-relaxed">
            {message.content}
          </p>
        </div>
        <div className="ml-3 mt-1 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-[var(--surface-4)]">
          <User size={14} className="text-[var(--text-muted)]" />
        </div>
      </motion.div>
    )
  }

  // Assistant Message
  return (
    <motion.div
      className="group mb-8 flex justify-start"
      variants={messageVariants}
      initial="hidden"
      animate="visible"
    >
      <div className="mr-4 mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-[var(--brand-500)] to-[var(--brand-700)] shadow-md">
        <Bot size={16} className="text-white" />
      </div>
      <div className="min-w-[50%] max-w-[85%] rounded-2xl border border-[var(--border)] bg-[var(--surface-1)] shadow-sm">
        <div className="mb-2 flex items-center gap-2">
          <span className="rounded border border-[var(--brand-200)] bg-[var(--brand-50)] px-1.5 py-0.5 text-[10px] text-[var(--brand-500)]">
            AI
          </span>
        </div>

        {/* Tool Calls Area */}
        {message.tool_calls && message.tool_calls.length > 0 && (
          <div className="mb-4">
            {message.tool_calls.map((tool) => (
              <ToolCallBadge
                key={tool.id}
                name={tool.name}
                args={tool.args}
                status={tool.status}
                onClick={onToolClick ? () => onToolClick(tool) : undefined}
              />
            ))}
          </div>
        )}

        {/* Main Content */}
        <div className="prose prose-sm max-w-none leading-7 text-[var(--text-primary)]">
          {sanitizedContent ? (
            <ReactMarkdown components={markdownComponents}>
              {sanitizedContent}
            </ReactMarkdown>
          ) : (
            message.isStreaming && (
              <span className="inline-block h-4 w-1.5 animate-pulse rounded-full bg-[var(--brand-500)] align-middle" />
            )
          )}
        </div>

        <ActionBar content={message.content} onRetry={onRetry} />
      </div>
    </motion.div>
  )
}
