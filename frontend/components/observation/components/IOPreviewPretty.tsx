import { useMemo } from 'react'
import { ChatMessage } from './ChatMessage'
import { PrettyJsonView } from './PrettyJsonView'

interface IOPreviewPrettyProps {
  input: unknown
  output: unknown
  metadata?: Record<string, unknown> | null
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
    Array.isArray((output as Record<string, unknown>).choices)
  ) {
    const msg = ((output as Record<string, unknown>).choices as Record<string, unknown>[])[0]
      ?.message
    if (msg) return { success: true, messages: [msg as ChatMlMessage] }
  }
  if (typeof output === 'string') {
    return { success: true, messages: [{ role: 'assistant', content: output }] }
  }
  return { success: false, messages: [] }
}

export function IOPreviewPretty({ input, output, metadata }: IOPreviewPrettyProps) {
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

  if (canDisplayAsChat) {
    return (
      <div>
        <div className="space-y-3 p-4">
          {messages.map((msg, i) => (
            <ChatMessage key={i} message={msg} />
          ))}
        </div>
        {metadata != null && Object.keys(metadata).length > 0 && (
          <PrettyJsonView data={metadata} title="Metadata" section="metadata" />
        )}
      </div>
    )
  }

  return (
    <div>
      {input != null && (
        <PrettyJsonView data={input} title="Input" section="input" />
      )}
      {output != null && (
        <PrettyJsonView data={output} title="Output" section="output" />
      )}
      {metadata != null && Object.keys(metadata).length > 0 && (
        <PrettyJsonView data={metadata} title="Metadata" section="metadata" />
      )}
    </div>
  )
}
