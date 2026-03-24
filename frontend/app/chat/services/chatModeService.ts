import { modeHandlerRegistry } from './modeHandlers/registry'
import type { ModeHandler } from './modeHandlers/types'

class ChatModeService {
  getHandler(modeId: string): ModeHandler | undefined {
    return modeHandlerRegistry.get(modeId)
  }
}

export const chatModeService = new ChatModeService()
