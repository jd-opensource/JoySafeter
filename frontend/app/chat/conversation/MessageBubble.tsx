'use client'

import DOMPurify from 'dompurify'
import { User, Bot, Search, Check, Loader2, ListTodo, Terminal } from 'lucide-react'
import React from 'react'
import ReactMarkdown from 'react-markdown'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'

import { cn } from '@/lib/utils'

import { Message, ToolCall } from '../types'

interface MessageBubbleProps {
  message: Message
  isLast: boolean
  onToolClick?: (toolCall: ToolCall) => void
}

const ToolCallItem = ({ tool, onClick }: { tool: ToolCall; onClick?: () => void }) => {
  const isCompleted = tool.status === 'completed'
  // Safer rendering of args to avoid Object-as-child errors
  const argsDisplay = React.useMemo(() => {
    try {
      return JSON.stringify(tool.args, null, 1)
        .replace(/[\{\}"]/g, '')
        .slice(0, 100)
    } catch {
      return '...'
    }
  }, [tool.args])

  return (
    <div className="group mb-2">
      <div
        onClick={onClick}
        className={cn(
          'flex w-fit items-center gap-2 rounded-lg border px-3 py-1.5 text-xs transition-all',
          isCompleted
            ? 'border-gray-200 bg-gray-50 text-gray-600'
            : 'border-blue-100 bg-blue-50 text-blue-700',
          onClick && 'cursor-pointer hover:shadow-sm',
        )}
      >
        {tool.name === 'web_search' ? (
          <Search size={12} />
        ) : tool.name === 'planner' ? (
          <ListTodo size={12} />
        ) : (
          <Terminal size={12} />
        )}

        <span className="font-medium capitalize">{tool.name.replace(/_/g, ' ')}</span>

        {/* Args Preview */}
        <span className="ml-1 hidden max-w-[200px] truncate font-mono text-gray-400 group-hover:inline">
          {argsDisplay}
        </span>

        <div className="ml-2 border-l border-gray-300/50 pl-2">
          {isCompleted ? (
            <Check size={12} className="text-green-500" />
          ) : (
            <Loader2 size={12} className="animate-spin text-blue-500" />
          )}
        </div>
      </div>
    </div>
  )
}

export default function MessageBubble({ message, onToolClick }: MessageBubbleProps) {
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
              <ToolCallItem
                key={tool.id}
                tool={tool}
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
                  // Ensure children is a string to prevent "Object as Child" errors
                  const content = String(children).replace(/\n$/, '')

                  return !inline && match ? (
                    <SyntaxHighlighter
                      style={oneLight}
                      language={match[1]}
                      PreTag="div"
                      customStyle={{
                        background: '#f9fafb',
                        border: '1px solid #e5e7eb',
                        borderRadius: '0.5rem',
                        fontSize: '13px',
                        margin: '1em 0',
                      }}
                    >
                      {content}
                    </SyntaxHighlighter>
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
      </div>
    </div>
  )
}
