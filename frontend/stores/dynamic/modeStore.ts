/**
 * Mode store for managing active mode and user preferences
 *
 * Manages:
 * - Active mode for the current session
 * - User's last mode preference (persisted in localStorage)
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

import { Mode, toMode } from '@/types/dynamic/mode';

/**
 * Mode store state
 */
export interface ModeState {
  /** Currently active mode for the session */
  activeMode: Mode | null;

  /** User's last selected mode preference */
  preferredMode: Mode | null;

  /** Whether the mode selection dialog is open */
  isSelectingMode: boolean;
}

/**
 * Mode store actions
 */
export interface ModeActions {
  /**
   * Set the active mode for the current session
   * This should be called when:
   * - User selects a mode
   * - Mode is resolved from URL/context
   * - Session is restored with a stored mode
   */
  setActiveMode: (mode: Mode | null) => void;

  /**
   * Set the user's preferred mode
   * This is saved to localStorage and used as a fallback
   * when mode cannot be determined from context
   */
  setPreferredMode: (mode: Mode | null) => void;

  /**
   * Open the mode selection dialog
   */
  openModeSelect: () => void;

  /**
   * Close the mode selection dialog
   */
  closeModeSelect: () => void;

  /**
   * Reset the active mode (for new session)
   */
  resetActiveMode: () => void;
}

/**
 * Complete mode store type
 */
export type ModeStore = ModeState & ModeActions;

/**
 * Mode store with persistence
 *
 * Only preferredMode is persisted to localStorage.
 * activeMode is session-specific and not persisted.
 */
export const useModeStore = create<ModeStore>()(
  persist(
    (set) => ({
      // State
      activeMode: null,
      preferredMode: null,
      isSelectingMode: false,

      // Actions
      setActiveMode: (mode) => set({ activeMode: mode }),

      setPreferredMode: (mode) => set({ preferredMode: mode }),

      openModeSelect: () => set({ isSelectingMode: true }),

      closeModeSelect: () => set({ isSelectingMode: false }),

      resetActiveMode: () => set({ activeMode: null }),
    }),
    {
      name: 'mode-storage', // localStorage key
      partialize: (state) => ({
        // Only persist preferred mode, not active mode
        preferredMode: state.preferredMode,
      }),
      // Custom deserializer to validate mode value
      merge: (persistedState, currentState) => {
        const persisted = persistedState as Partial<ModeState>;
        return {
          ...currentState,
          preferredMode: toMode(persisted.preferredMode) ?? null,
        };
      },
    }
  )
);
