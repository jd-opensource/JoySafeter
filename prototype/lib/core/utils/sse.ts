/**
 * Server-Sent Events utilities
 */

export interface SSEEvent {
  event?: string
  data: unknown
  id?: string
  retry?: number
}

export function encodeSSE(event: SSEEvent): Uint8Array {
  let message = ''

  if (event.event) {
    message += `event: ${event.event}\n`
  }

  if (event.id) {
    message += `id: ${event.id}\n`
  }

  if (event.retry) {
    message += `retry: ${event.retry}\n`
  }

  const data = typeof event.data === 'string'
    ? event.data
    : JSON.stringify(event.data)

  message += `data: ${data}\n\n`

  return new TextEncoder().encode(message)
}

export function decodeSSE(message: string): SSEEvent | null {
  const lines = message.split('\n')
  const event: Partial<SSEEvent> = {}

  for (const line of lines) {
    if (line.startsWith('event:')) {
      event.event = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      const data = line.slice(5).trim()
      try {
        event.data = JSON.parse(data)
      } catch {
        event.data = data
      }
    } else if (line.startsWith('id:')) {
      event.id = line.slice(3).trim()
    } else if (line.startsWith('retry:')) {
      event.retry = parseInt(line.slice(6).trim(), 10)
    }
  }

  return event.data !== undefined ? (event as SSEEvent) : null
}

export function createSSEStream() {
  const encoder = new TextEncoder()
  let controller: ReadableStreamDefaultController<Uint8Array> | null = null

  const stream = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c
    },
  })

  return {
    stream,
    send: (event: SSEEvent) => {
      if (controller) {
        controller.enqueue(encodeSSE(event))
      }
    },
    close: () => {
      if (controller) {
        controller.close()
      }
    },
  }
}
