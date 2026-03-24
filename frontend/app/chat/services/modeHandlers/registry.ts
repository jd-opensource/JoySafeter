import type { ModeHandler } from './types'

class ModeHandlerRegistry {
  private handlers = new Map<string, ModeHandler>()

  register(modeId: string, handler: ModeHandler): void {
    if (this.handlers.has(modeId)) {
      console.warn(`Mode handler for "${modeId}" is already registered. Overwriting...`)
    }
    this.handlers.set(modeId, handler)
  }

  get(modeId: string): ModeHandler | undefined {
    return this.handlers.get(modeId)
  }
}

export const modeHandlerRegistry = new ModeHandlerRegistry()
