import { memo, type FC } from 'react'
import ReactMarkdown, { type Options } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { cn } from '@/lib/utils'

interface ChatMessageProps {
  message: {
    role: string
    content?: string | Array<{ type: string; text?: string }>
    tool_calls?: Array<{
      id: string
      function: { name: string; arguments: string }
    }>
    thinking?: Array<{ type: string; thinking: string }>
  }
}

function renderContent(
  content: string | Array<{ type: string; text?: string }> | undefined,
): string {
  if (!content) return ''
  if (typeof content === 'string') return content
  return content
    .filter((c) => c.type === 'text' && c.text)
    .map((c) => c.text!)
    .join('\n')
}

const MemoizedReactMarkdown: FC<Options> = memo(ReactMarkdown)

function MarkdownContent({ text }: { text: string }) {
  return (
    <div className="space-y-2 overflow-x-auto text-sm break-words">
      <MemoizedReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p({ children }) {
            return (
              <p className="mb-2 whitespace-pre-wrap last:mb-0">{children}</p>
            )
          },
          a({ children, href }) {
            return (
              <a
                href={href ?? undefined}
                className="underline"
                target="_blank"
                rel="noopener noreferrer"
              >
                {children}
              </a>
            )
          },
          ul({ children }) {
            return <ul className="list-inside list-disc">{children}</ul>
          },
          ol({ children }) {
            return <ol className="list-inside list-decimal">{children}</ol>
          },
          li({ children }) {
            return (
              <li className="mt-1 [&>ol]:pl-4 [&>ul]:pl-4">{children}</li>
            )
          },
          pre({ children }) {
            return <pre className="overflow-auto rounded bg-black/10 p-2 text-xs dark:bg-white/10">{children}</pre>
          },
          h1({ children }) {
            return <h1 className="text-2xl font-bold">{children}</h1>
          },
          h2({ children }) {
            return <h2 className="text-xl font-bold">{children}</h2>
          },
          h3({ children }) {
            return <h3 className="text-lg font-bold">{children}</h3>
          },
          h4({ children }) {
            return <h4 className="text-base font-bold">{children}</h4>
          },
          h5({ children }) {
            return <h5 className="text-sm font-bold">{children}</h5>
          },
          h6({ children }) {
            return <h6 className="text-xs font-bold">{children}</h6>
          },
          code({ children, className }) {
            const isBlock = /language-(\w+)/.test(className || '')
            if (isBlock) {
              return (
                <code className={cn('block', className)}>
                  {children}
                </code>
              )
            }
            return (
              <code className="rounded border bg-muted px-1 py-0.5 text-xs">
                {children}
              </code>
            )
          },
          blockquote({ children }) {
            return (
              <blockquote className="border-l-4 pl-4 italic">
                {children}
              </blockquote>
            )
          },
          hr() {
            return <hr className="my-4" />
          },
          table({ children }) {
            return (
              <div className="overflow-x-auto rounded border text-xs">
                <table className="min-w-full divide-y">{children}</table>
              </div>
            )
          },
          thead({ children }) {
            return <thead>{children}</thead>
          },
          tbody({ children }) {
            return <tbody className="divide-y">{children}</tbody>
          },
          tr({ children }) {
            return <tr>{children}</tr>
          },
          th({ children }) {
            return (
              <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider">
                {children}
              </th>
            )
          },
          td({ children }) {
            return <td className="whitespace-nowrap px-4 py-2">{children}</td>
          },
        }}
      >
        {text}
      </MemoizedReactMarkdown>
    </div>
  )
}

export function ChatMessage({ message }: ChatMessageProps) {
  const { role } = message
  const text = renderContent(message.content)

  return (
    <div
      className={cn(
        'rounded-lg px-3 py-2 text-sm',
        role === 'system' && 'bg-muted text-muted-foreground',
        role === 'user' && 'ml-auto max-w-[80%] bg-primary text-primary-foreground',
        role === 'assistant' && 'mr-auto max-w-[80%] bg-muted',
        role === 'tool' && 'border bg-card text-card-foreground',
      )}
    >
      <div className="mb-1 text-xs font-medium opacity-70">{role}</div>

      {message.thinking?.map((t, i) => (
        <details key={i} className="mb-2">
          <summary className="cursor-pointer text-xs text-muted-foreground">
            Thinking...
          </summary>
          <pre className="mt-1 whitespace-pre-wrap text-xs opacity-70">
            {t.thinking}
          </pre>
        </details>
      ))}

      {text && <MarkdownContent text={text} />}

      {message.tool_calls?.map((tc) => (
        <div key={tc.id} className="mt-2 rounded border bg-card p-2">
          <div className="text-xs font-medium">{tc.function.name}</div>
          <pre className="mt-1 overflow-auto text-xs">
            {tc.function.arguments}
          </pre>
        </div>
      ))}
    </div>
  )
}
