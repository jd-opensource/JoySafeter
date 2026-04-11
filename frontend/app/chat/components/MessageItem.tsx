'use client'

import DOMPurify from 'dompurify'
import { motion } from 'framer-motion'
import type { Variants } from 'framer-motion'
import { User, Bot, AlertCircle } from 'lucide-react'
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
        className="flex w-full gap-3 justify-end"
        variants={messageVariants}
        initial="hidden"
        animate="visible"
      >
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-gray-900 px-4 py-2.5 text-sm leading-relaxed text-white">
          <p className="whitespace-pre-wrap">
            {message.content}
          </p>
        </div>
        <div className="mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-[var(--surface-5)]">
          <User size={14} className="text-[var(--text-secondary)]" />
        </div>
      </motion.div>
    )
  }

  // Assistant Message
  return (
    <motion.div
      className="group flex w-full gap-3 justify-start"
      variants={messageVariants}
      initial="hidden"
      animate="visible"
    >
      <div className="mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-[var(--brand-50)]">
        <Bot size={14} className="text-[var(--brand-500)]" />
      </div>
      <div className="max-w-[85%] rounded-2xl rounded-bl-md border border-[var(--border-muted)] bg-[var(--surface-2)] px-4 py-2.5 text-sm leading-relaxed text-[var(--text-primary)]">
        {/* Tool Calls Area */}
        {message.tool_calls && message.tool_calls.length > 0 && (
          <div className="mb-2 space-y-1">
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

        {/* Error indicator */}
        {message.metadata?.error && (
          <div className="mb-2 flex items-start gap-2 rounded-lg border border-[var(--status-error)] bg-[var(--status-error-bg)] px-3 py-2 text-sm text-[var(--status-error)]">
            <AlertCircle size={16} className="mt-0.5 flex-shrink-0" />
            <span>{message.metadata.error}</span>
          </div>
        )}

        {/* Main Content */}
        <div className="prose prose-sm max-w-none prose-headings:my-2 prose-p:my-1 prose-ol:my-1 prose-ul:my-1 prose-li:my-0.5">
          {sanitizedContent ? (
            <ReactMarkdown components={markdownComponents}>
              {sanitizedContent}
            </ReactMarkdown>
          ) : message.metadata?.error ? null : (
            message.isStreaming && (
              <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse rounded-sm bg-[var(--brand-500)] align-middle" />
            )
          )}
        </div>

        <ActionBar content={message.content} onRetry={onRetry} />
      </div>
    </motion.div>
  )
}
