/**
 * Mode types and utilities for unified mode entry system
 *
 * Mode represents the user-facing scenario that drives UX and backend hints:
 * - ctf: CTF/Challenge mode
 */

export type Mode = 'ctf';

export const MODES = {
  CTF: 'ctf' as Mode,
} as const;

/**
 * Mode display configuration
 */
export const MODE_CONFIG = {
  ctf: {
    label: 'CTF Mode',
    description: 'Capture The Flag challenges and competitions',
    icon: '🚩',
  },
} as const;

/**
 * Validates if a string is a valid mode
 */
export function isValidMode(value: unknown): value is Mode {
  return value === 'ctf';
}

/**
 * Safely converts a value to a Mode, returning undefined if invalid
 */
export function toMode(value: unknown): Mode | undefined {
  if (isValidMode(value)) {
    return value;
  }
  return undefined;
}

/**
 * Gets the display config for a mode
 */
export function getModeConfig(mode: Mode) {
  return MODE_CONFIG[mode];
}

/**
 * Converts mode to backend metadata format
 */
export function modeToMetadata(mode: Mode) {
  return {
    mode,
    is_ctf: mode === 'ctf',
    non_ctf_guard: false,
  };
}
