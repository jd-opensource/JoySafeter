'use client'

import DOMPurify from 'dompurify'
import { User, Bot } from 'lucide-react'
import React from 'react'
import ReactMarkdown from 'react-markdown'

import { ActionBar } from '../shared/ActionBar'
import { CodeBlock } from '../shared/CodeBlock'
import { ToolCallBadge } from '../shared/ToolCallDisplay'
import { Message, ToolCall } from '../types'

interface MessageItemProps {
  message: Message
  isLast: boolean
  onToolClick?: (toolCall: ToolCall) => void
  onRetry?: () => void
}

export default function MessageItem({ message, onToolClick, onRetry }: MessageItemProps) {
  const isUser = message.role === 'user'

  if (isUser) {
    return (
      <div className="mb-6 flex justify-end duration-200 animate-in fade-in">
        <div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-gray-100 px-5 py-3.5 text-gray-900 shadow-sm">
          <p className="whitespace-pre-wrap text-[15px] font-normal leading-relaxed">
            {message.content}
          </p>
        </div>
        {/* Optional Avatar */}
        <div className="ml-3 mt-1 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-gray-200">
          <User size={14} className="text-gray-500" />
        </div>
      </div>
    )
  }

  // Assistant Message
  return (
    <div className="group mb-8 flex justify-start duration-300 animate-in fade-in slide-in-from-bottom-2">
      <div className="mr-4 mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-blue-600 to-purple-600 shadow-md">
        <Bot size={16} className="text-white" />
      </div>
      <div className="min-w-[50%] max-w-[85%]">
        <div className="mb-2 flex items-center gap-2">
          <span className="rounded border border-gray-200 bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-400">
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
        <div className="prose prose-sm prose-gray max-w-none leading-7 text-gray-800">
          {message.content ? (
            <ReactMarkdown
              components={{
                code({ node, inline, className, children, ...props }: any) {
                  const match = /language-(\w+)/.exec(className || '')
                  const content = String(children).replace(/\n$/, '')

                  return !inline && match ? (
                    <CodeBlock language={match[1]} code={content} />
                  ) : (
                    <code
                      {...props}
                      className="rounded border border-gray-200 bg-gray-100 px-1.5 py-0.5 font-mono text-xs text-gray-800"
                    >
                      {children}
                    </code>
                  )
                },
              }}
            >
              {DOMPurify.sanitize(message.content, {
                ALLOWED_TAGS: [
                  'p',
                  'br',
                  'strong',
                  'em',
                  'code',
                  'pre',
                  'blockquote',
                  'ul',
                  'ol',
                  'li',
                  'a',
                  'img',
                  'h1',
                  'h2',
                  'h3',
                  'h4',
                  'h5',
                  'h6',
                  'hr',
                  'div',
                  'span',
                  'table',
                  'thead',
                  'tbody',
                  'tr',
                  'th',
                  'td',
                  'details',
                  'summary',
                  'sup',
                  'sub',
                  'del',
                  's',
                  'ins',
                  'mark',
                  'abbr',
                  'b',
                  'i',
                  'u',
                  'small',
                  'tt',
                  'kbd',
                  'samp',
                  'var',
                ],
                ALLOWED_ATTR: [
                  'href',
                  'src',
                  'alt',
                  'title',
                  'class',
                  'id',
                  'width',
                  'height',
                  'target',
                  'rel',
                  'name',
                  'open',
                ],
                ALLOW_DATA_ATTR: false,
                ALLOW_UNKNOWN_PROTOCOLS: false,
                ADD_ATTR: ['rel'],
                FORBID_TAGS: ['script', 'style', 'iframe', 'form', 'input', 'button'],
                FORBID_ATTR: ['onerror', 'onload', 'onclick', 'onmouseover', 'onfocus', 'onblur'],
              })}
            </ReactMarkdown>
          ) : (
            // Streaming indicator if no content yet but active
            message.isStreaming && (
              <span className="inline-block h-4 w-1.5 animate-pulse rounded-full bg-blue-500 align-middle" />
            )
          )}
        </div>

        <ActionBar content={message.content} onRetry={onRetry} />
      </div>
    </div>
  )
}
