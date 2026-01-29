/**
 * Mode Switcher Component
 *
 * Displays the current mode and allows switching to a different mode.
 * Switching modes creates a new session (old session remains viewable).
 */

import React from 'react';

import { Mode, getModeConfig } from '@/types/dynamic/mode';

export interface ModeSwitcherProps {
  /** Current active mode */
  currentMode: Mode | null;
  /** Callback when user requests to switch mode */
  onSwitchMode: () => void;
  /** Whether switching is allowed (e.g., disabled during message sending) */
  disabled?: boolean;
}

/**
 * Mode indicator and switcher component
 */
export const ModeSwitcher: React.FC<ModeSwitcherProps> = ({
  currentMode,
  onSwitchMode,
  disabled = false,
}) => {
  if (!currentMode) {
    return null;
  }

  const config = getModeConfig(currentMode);

  return (
    <div className="flex items-center gap-2">
      {/* Mode Indicator */}
      <div className="flex items-center gap-2 px-3 py-1.5 bg-gray-100 dark:bg-gray-700 rounded-lg">
        <span className="text-lg">{config.icon}</span>
        <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
          {config.label}
        </span>
      </div>

      {/* Switch Button */}
      <button
        onClick={onSwitchMode}
        disabled={disabled}
        className="px-3 py-1.5 text-sm font-medium text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        title="Switch mode (creates a new session)"
      >
        Switch Mode
      </button>
    </div>
  );
};

export default ModeSwitcher;
