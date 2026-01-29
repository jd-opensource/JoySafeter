/**
 * useChatSession Hook
 * 
 * Unified management of chat session state using reducer pattern to ensure consistent state updates
 */

import { useReducer, useCallback, useEffect } from 'react'

import type { UploadedFile } from '../services/modeHandlers/types'

/**
 * Chat session state
 */
export interface ChatSessionState {
  /** Input content */
  input: string
  /** List of uploaded files */
  files: UploadedFile[]
  /** Mode configuration */
  mode: {
    /** Mode type */
    type: string | null
    /** Mode configuration */
    config: Record<string, any>
    /** Associated Graph ID */
    graphId?: string | null
  }
  /** Selected agent ID */
  selectedAgentId: string | null
  /** Whether to auto redirect to Copilot */
  autoRedirect: boolean
  /** Whether redirecting is in progress */
  isRedirecting: boolean
  /** Whether to show case list */
  showCases: boolean
  /** Whether file upload is in progress */
  isUploading: boolean
}

/**
 * Initial state
 */
const initialState: ChatSessionState = {
  input: '',
  files: [],
  mode: {
    type: null,
    config: {},
    graphId: null,
  },
  selectedAgentId: null,
  autoRedirect: false,
  isRedirecting: false,
  showCases: true,
  isUploading: false,
}

/**
 * Action types
 */
type ChatSessionAction =
  | { type: 'SET_INPUT'; payload: string }
  | { type: 'SET_FILES'; payload: UploadedFile[] }
  | { type: 'ADD_FILE'; payload: UploadedFile }
  | { type: 'REMOVE_FILE'; payload: string }
  | { type: 'SET_MODE'; payload: { type: string | null; config?: Record<string, any>; graphId?: string | null } }
  | { type: 'CLEAR_MODE' }
  | { type: 'SET_SELECTED_AGENT_ID'; payload: string | null }
  | { type: 'SET_AUTO_REDIRECT'; payload: boolean }
  | { type: 'SET_IS_REDIRECTING'; payload: boolean }
  | { type: 'SET_SHOW_CASES'; payload: boolean }
  | { type: 'SET_IS_UPLOADING'; payload: boolean }
  | { type: 'RESET' }
  | { type: 'RESET_INPUT' }

/**
 * Reducer function
 */
function chatSessionReducer(
  state: ChatSessionState,
  action: ChatSessionAction
): ChatSessionState {
  switch (action.type) {
    case 'SET_INPUT':
      return { ...state, input: action.payload }

    case 'SET_FILES':
      return { ...state, files: action.payload }

    case 'ADD_FILE':
      return { ...state, files: [...state.files, action.payload] }

    case 'REMOVE_FILE':
      return {
        ...state,
        files: state.files.filter((f) => f.id !== action.payload),
      }

    case 'SET_MODE':
      return {
        ...state,
        mode: {
          type: action.payload.type,
          config: action.payload.config || {},
          graphId: action.payload.graphId ?? state.mode.graphId,
        },
      }

    case 'CLEAR_MODE':
      return {
        ...state,
        mode: {
          type: null,
          config: {},
          graphId: null,
        },
      }

    case 'SET_SELECTED_AGENT_ID':
      return { ...state, selectedAgentId: action.payload }

    case 'SET_AUTO_REDIRECT':
      return { ...state, autoRedirect: action.payload }

    case 'SET_IS_REDIRECTING':
      return { ...state, isRedirecting: action.payload }

    case 'SET_SHOW_CASES':
      return { ...state, showCases: action.payload }

    case 'SET_IS_UPLOADING':
      return { ...state, isUploading: action.payload }

    case 'RESET':
      return initialState

    case 'RESET_INPUT':
      return {
        ...state,
        input: '',
        files: [],
        mode: {
          type: null,
          config: {},
          graphId: null,
        },
      }

    default:
      return state
  }
}

/**
 * Local storage key
 */
const AUTO_REDIRECT_KEY = 'chat_auto_redirect_to_copilot'

/**
 * useChatSession Hook
 * 
 * Provides unified state management and operation methods
 */
export function useChatSession() {
  const [state, dispatch] = useReducer(chatSessionReducer, initialState)

  // Load autoRedirect setting from local storage
  useEffect(() => {
    const saved = localStorage.getItem(AUTO_REDIRECT_KEY)
    if (saved === 'true') {
      dispatch({ type: 'SET_AUTO_REDIRECT', payload: true })
    }
  }, [])

  // Actions
  const setInput = useCallback((input: string) => {
    dispatch({ type: 'SET_INPUT', payload: input })
  }, [])

  const setFiles = useCallback((files: UploadedFile[]) => {
    dispatch({ type: 'SET_FILES', payload: files })
  }, [])

  const addFile = useCallback((file: UploadedFile) => {
    dispatch({ type: 'ADD_FILE', payload: file })
  }, [])

  const removeFile = useCallback((fileId: string) => {
    dispatch({ type: 'REMOVE_FILE', payload: fileId })
  }, [])

  const setMode = useCallback(
    (mode: {
      type: string | null
      config?: Record<string, any>
      graphId?: string | null
    }) => {
      dispatch({ type: 'SET_MODE', payload: mode })
    },
    []
  )

  const clearMode = useCallback(() => {
    dispatch({ type: 'CLEAR_MODE' })
  }, [])

  const setSelectedAgentId = useCallback((agentId: string | null) => {
    dispatch({ type: 'SET_SELECTED_AGENT_ID', payload: agentId })
  }, [])

  const setAutoRedirect = useCallback(
    (enabled: boolean) => {
      dispatch({ type: 'SET_AUTO_REDIRECT', payload: enabled })
      localStorage.setItem(AUTO_REDIRECT_KEY, enabled.toString())
      if (enabled) {
        dispatch({ type: 'SET_SELECTED_AGENT_ID', payload: null })
      }
    },
    []
  )

  const setIsRedirecting = useCallback((isRedirecting: boolean) => {
    dispatch({ type: 'SET_IS_REDIRECTING', payload: isRedirecting })
  }, [])

  const setShowCases = useCallback((showCases: boolean) => {
    dispatch({ type: 'SET_SHOW_CASES', payload: showCases })
  }, [])

  const setIsUploading = useCallback((isUploading: boolean) => {
    dispatch({ type: 'SET_IS_UPLOADING', payload: isUploading })
  }, [])

  const reset = useCallback(() => {
    dispatch({ type: 'RESET' })
  }, [])

  const resetInput = useCallback(() => {
    dispatch({ type: 'RESET_INPUT' })
  }, [])

  return {
    // State
    state,
    // Actions
    setInput,
    setFiles,
    addFile,
    removeFile,
    setMode,
    clearMode,
    setSelectedAgentId,
    setAutoRedirect,
    setIsRedirecting,
    setShowCases,
    setIsUploading,
    reset,
    resetInput,
  }
}

