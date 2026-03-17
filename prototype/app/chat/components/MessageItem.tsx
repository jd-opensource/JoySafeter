'use client'

import DOMPurify from 'dompurify'
import { User, Bot, Search, Check, Loader2, ListTodo, Terminal } from 'lucide-react'
import React from 'react'
import ReactMarkdown from 'react-markdown'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'

import { cn } from '@/lib/core/utils/cn'

import { Message, ToolCall } from '../types'

interface MessageItemProps {
  message: Message
  isLast: boolean
  onToolClick?: (toolCall: ToolCall) => void
}

const ToolCallItem = ({ tool, onClick }: { tool: ToolCall; onClick?: () => void }) => {
  const isCompleted = tool.status === 'completed'
  // Safer rendering of args to avoid Object-as-child errors
  const argsDisplay = React.useMemo(() => {
    try {
      return JSON.stringify(tool.args, null, 1).replace(/[\{\}"]/g, '').slice(0, 100)
    } catch {
      return '...'
    }
  }, [tool.args])

  return (
    <div className="mb-2 group">
      <div
        onClick={onClick}
        className={cn(
          'flex items-center gap-2 text-xs py-1.5 px-3 rounded-lg border w-fit transition-all',
          isCompleted
            ? 'bg-gray-50 border-gray-200 text-gray-600'
            : 'bg-blue-50 border-blue-100 text-blue-700',
          onClick && 'cursor-pointer hover:shadow-sm'
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
        <span className="text-gray-400 hidden group-hover:inline max-w-[200px] truncate ml-1 font-mono">
          {argsDisplay}
        </span>

        <div className="ml-2 pl-2 border-l border-gray-300/50">
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

const MessageItem: React.FC<MessageItemProps> = ({ message, onToolClick }) => {
  const isUser = message.role === 'user'

  if (isUser) {
    return (
      <div className="flex justify-end mb-6 animate-in fade-in duration-200">
        <div className="max-w-[80%] bg-gray-100 text-gray-900 px-5 py-3.5 rounded-2xl rounded-tr-sm shadow-sm">
          <p className="whitespace-pre-wrap text-[15px] leading-relaxed font-normal">
            {message.content}
          </p>
        </div>
        {/* Optional Avatar */}
        <div className="w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center ml-3 flex-shrink-0 mt-1">
          <User size={14} className="text-gray-500" />
        </div>
      </div>
    )
  }

  // Assistant Message
  return (
    <div className="flex justify-start mb-8 group animate-in slide-in-from-bottom-2 fade-in duration-300">
      <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-600 to-purple-600 flex items-center justify-center mr-4 flex-shrink-0 shadow-md mt-0.5">
        <Bot size={16} className="text-white" />
      </div>
      <div className="max-w-[85%] min-w-[50%]">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-[10px] text-gray-400 px-1.5 py-0.5 bg-gray-100 rounded border border-gray-200">
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
        <div className="prose prose-sm prose-gray max-w-none text-gray-800 leading-7">
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
                      className="bg-gray-100 px-1.5 py-0.5 rounded text-gray-800 font-mono text-xs border border-gray-200"
                    >
                      {children}
                    </code>
                  )
                },
              }}
            >
              {DOMPurify.sanitize(message.content, {
                ALLOWED_TAGS: [
                  'p', 'br', 'strong', 'em', 'code', 'pre', 'blockquote',
                  'ul', 'ol', 'li', 'a', 'img', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                  'hr', 'div', 'span', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
                  'details', 'summary', 'sup', 'sub', 'del', 's', 'ins', 'mark',
                  'abbr', 'b', 'i', 'u', 'small', 'tt', 'kbd', 'samp', 'var'
                ],
                ALLOWED_ATTR: [
                  'href', 'src', 'alt', 'title', 'class', 'id', 'width', 'height',
                  'target', 'rel', 'name', 'open'
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
              <span className="inline-block w-1.5 h-4 bg-blue-500 animate-pulse rounded-full align-middle" />
            )
          )}
        </div>
      </div>
    </div>
  )
}

export default MessageItem
