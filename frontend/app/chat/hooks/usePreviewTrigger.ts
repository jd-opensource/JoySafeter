'use client'

import React, { useEffect, useRef } from 'react'

import type { ChatState, ChatAction } from './useChatReducer'

export function usePreviewTrigger(
  state: ChatState,
  dispatch: React.Dispatch<ChatAction>,
) {
  const prevFileCountRef = useRef(0)

  // Auto-show when new files appear (unless user dismissed)
  useEffect(() => {
    const currentFileCount = Object.keys(state.preview.fileTree).length
    const isNew = currentFileCount > prevFileCountRef.current

    if (isNew && currentFileCount > 0 && !state.preview.visible && !state.preview.userDismissed) {
      dispatch({ type: 'SHOW_PREVIEW' })
    }

    prevFileCountRef.current = currentFileCount
  }, [state.preview.fileTree, state.preview.visible, state.preview.userDismissed, dispatch])

  // Auto-hide when stream ends with no files
  useEffect(() => {
    if (
      !state.streaming.isProcessing &&
      Object.keys(state.preview.fileTree).length === 0 &&
      state.preview.visible
    ) {
      dispatch({ type: 'HIDE_PREVIEW' })
    }
  }, [state.streaming.isProcessing, state.preview.fileTree, state.preview.visible, dispatch])
}
