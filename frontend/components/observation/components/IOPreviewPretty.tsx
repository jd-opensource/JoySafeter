import { useMemo } from 'react'
import { ChatMessage } from './ChatMessage'

interface IOPreviewPrettyProps {
  input: unknown
  output: unknown
  observationName?: string
}

interface ChatMlMessage {
  role: string
  content?: string | Array<{ type: string; text?: string }>
  tool_calls?: Array<{ id: string; function: { name: string; arguments: string } }>
  thinking?: Array<{ type: string; thinking: string }>
}

function normalizeInput(input: unknown): { success: boolean; messages: ChatMlMessage[] } {
  if (!input) return { success: false, messages: [] }
  if (Array.isArray(input) && input.length > 0 && input[0]?.role) {
    return { success: true, messages: input as ChatMlMessage[] }
  }
  if (typeof input === 'object' && input !== null && 'messages' in input) {
    const msgs = (input as { messages: unknown }).messages
    if (Array.isArray(msgs)) return { success: true, messages: msgs as ChatMlMessage[] }
  }
  return { success: false, messages: [] }
}

function normalizeOutput(output: unknown): { success: boolean; messages: ChatMlMessage[] } {
  if (!output) return { success: false, messages: [] }
  if (typeof output === 'object' && output !== null && 'role' in output) {
    return { success: true, messages: [output as ChatMlMessage] }
  }
  if (
    typeof output === 'object' &&
    output !== null &&
    'choices' in output &&
    Array.isArray((output as any).choices)
  ) {
    const msg = (output as any).choices[0]?.message
    if (msg) return { success: true, messages: [msg as ChatMlMessage] }
  }
  if (typeof output === 'string') {
    return { success: true, messages: [{ role: 'assistant', content: output }] }
  }
  return { success: false, messages: [] }
}

export function IOPreviewPretty({ input, output, observationName }: IOPreviewPrettyProps) {
  const { canDisplayAsChat, messages } = useMemo(() => {
    const inResult = normalizeInput(input)
    const outResult = normalizeOutput(output)
    const allMessages = [...inResult.messages, ...outResult.messages]
    return {
      canDisplayAsChat:
        (inResult.success || outResult.success) && allMessages.length > 0,
      messages: allMessages,
    }
  }, [input, output])

  if (!canDisplayAsChat) {
    return (
      <div className="space-y-4 p-4">
        {input != null && (
          <div>
            <div className="mb-1 text-xs font-medium text-muted-foreground">Input</div>
            <pre className="overflow-auto rounded bg-muted p-2 text-xs">
              {JSON.stringify(input, null, 2)}
            </pre>
          </div>
        )}
        {output != null && (
          <div>
            <div className="mb-1 text-xs font-medium text-muted-foreground">Output</div>
            <pre className="overflow-auto rounded bg-muted p-2 text-xs">
              {JSON.stringify(output, null, 2)}
            </pre>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-3 p-4">
      {messages.map((msg, i) => (
        <ChatMessage key={i} message={msg} />
      ))}
    </div>
  )
}
