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

      {text && <div className="whitespace-pre-wrap">{text}</div>}

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
