/**
 * Mode Handler Types
 *
 * Defines interfaces and types for mode handlers, used to uniformly handle different chat mode logic
 */

import { LucideIcon } from 'lucide-react'

/**
 * Uploaded file interface
 */
export interface UploadedFile {
  id: string
  filename: string
  path: string
  size: number
}

/**
 * Mode context containing information needed for handler execution
 */
export interface ModeContext {
  /** Workspace data */
  workspaces: Array<{ id: string; type?: string; [key: string]: any }>
  /** List of deployed agents */
  deployedAgents: Array<{ id: string; name: string; [key: string]: any }>
  /** Currently selected agent ID */
  selectedAgentId?: string | null
  /** Personal workspace ID */
  personalWorkspaceId?: string | null
  /** Internationalization translation function */
  t: (key: string, options?: any) => string
  /** Router navigation function */
  router: {
    push: (path: string) => void
  }
  /** Query Client for cache management */
  queryClient: {
    invalidateQueries: (options: { queryKey: any[] }) => void
    refetchQueries?: (options: { queryKey: any[] }) => Promise<any>
    getQueryData?: <T = unknown>(queryKey: any[]) => T | undefined
  }
}

/**
 * Mode selection result
 */
export interface ModeSelectionResult {
  /** Whether the operation was successful */
  success: boolean
  /** Error message (if any) */
  error?: string
  /** State updates to apply */
  stateUpdates?: {
    input?: string
    graphId?: string | null
    mode?: string
  }
}

/**
 * Submit result
 */
export interface SubmitResult {
  /** Whether the operation was successful */
  success: boolean
  /** Error message (if any) */
  error?: string
  /** Processed input */
  processedInput?: string
  /** Graph ID to use */
  graphId?: string | null
  /** Whether redirect is needed */
  shouldRedirect?: boolean
  /** Redirect path */
  redirectPath?: string
}

/**
 * Validation result
 */
export interface ValidationResult {
  /** Whether the input is valid */
  valid: boolean
  /** Error message */
  error?: string
}

/**
 * Mode metadata
 */
export interface ModeMetadata {
  /** Mode ID */
  id: string
  /** Mode label */
  label: string
  /** Mode description */
  description: string
  /** Icon component */
  icon: LucideIcon | React.ComponentType<any>
  /** Mode type */
  type?: 'template' | 'simple' | 'agent'
  /** Template name (for template type) */
  templateName?: string
  /** Template graph name */
  templateGraphName?: string
}

/**
 * Mode Handler Interface
 *
 * All mode handlers must implement this interface to uniformly handle different mode logic
 */
export interface ModeHandler {
  /**
   * Handle mode selection
   * Called when user clicks on a mode card
   */
  onSelect(context: ModeContext): Promise<ModeSelectionResult>

  /**
   * Handle submission
   * Called when user submits chat input
   */
  onSubmit(
    input: string,
    files: UploadedFile[],
    context: ModeContext
  ): Promise<SubmitResult>

  /**
   * Validate input and files
   * Performs validation before submission
   */
  validate?(input: string, files: UploadedFile[]): ValidationResult

  /**
   * Get associated Graph ID
   * Used to determine which Graph to use for processing the request
   */
  getGraphId?(context: ModeContext): Promise<string | null>

  /**
   * Whether file upload is required
   */
  requiresFiles?: boolean

  /**
   * Mode metadata
   */
  metadata: ModeMetadata
}
