/**
 * Mode resolution utilities for unified mode entry system
 *
 * Resolves mode based on dynamic user input and preferences:
 * 1. Existing session context (when restoring a session)
 * 2. Unambiguous first-message detection (CTF patterns in user input)
 * 3. Saved user preference (from localStorage)
 * 4. Prompt user when ambiguous (show selection dialog)
 *
 * Note: URL-based mode routing is NOT used - mode is determined dynamically
 * based on conversation context and user input patterns.
 */

import { Mode } from '@/types/dynamic/mode';

/**
 * Result of mode resolution
 */
export interface ModeResolution {
  /** Resolved mode, or null if ambiguous and needs user selection */
  mode: Mode | null;
  /** Resolution source for logging/debugging */
  source: 'message_pattern' | 'preference' | 'ambiguous' | 'session';
  /** Whether user selection is required */
  requiresSelection: boolean;
}

/**
 * Detects if a message contains CTF-specific patterns
 *
 * This is used for unambiguous detection when the user's first message
 * clearly indicates CTF mode (e.g., contains flag patterns)
 *
 * @param message - User's message
 * @returns true if CTF patterns detected
 */
export function detectCTFPatterns(message: string): boolean {
  const lowerMessage = message.toLowerCase();

  // Common CTF indicators
  const ctfPatterns = [
    /flag\{[^}]+\}/i,           // flag{...} format
    /ctf\{[^}]+\}/i,            // ctf{...} format
    /picoctf/i,                  // PicoCTF
    /hackthebox/i,               // HackTheBox
    /tryhackme/i,                // TryHackMe
    /overthewire/i,              // OverTheWire
    /\bctf\b.*\bchallenge\b/i,   // "ctf challenge"
    /capture.*the.*flag/i,       // "capture the flag"
  ];

  return ctfPatterns.some(pattern => pattern.test(lowerMessage));
}

/**
 * Resolves mode from current context (NO URL-based detection)
 *
 * Priority order:
 * 1. User preference (from localStorage)
 * 2. Ambiguous (requires user selection via dialog)
 *
 * Note: Session restoration is handled separately by ChatPage.
 * First-message CTF pattern detection should be done when user sends first message.
 *
 * @param options - Resolution options
 * @returns Mode resolution result
 */
export function resolveMode(options: {
  preferredMode?: Mode | null;
}): ModeResolution {
  const { preferredMode } = options;

  // 1. Use user preference if available
  if (preferredMode) {
    return {
      mode: preferredMode,
      source: 'preference',
      requiresSelection: false,
    };
  }

  // 2. Ambiguous - requires user selection
  return {
    mode: null,
    source: 'ambiguous',
    requiresSelection: true,
  };
}

/**
 * Detects mode from a user message
 *
 * @param message - User's first message
 * @returns Detected mode or null if ambiguous
 */
export function detectModeFromMessage(message: string): Mode | null {
  if (detectCTFPatterns(message)) {
    return 'ctf';
  }

  // Default to ctf for non-CTF messages
  // or return null to force user selection
  return null;
}
