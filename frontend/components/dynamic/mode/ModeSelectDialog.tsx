/**
 * Mode Selection Dialog
 *
 * Prompts the user to choose between CTF Mode, Enterprise Scan Mode, and Whitebox Scanner
 * when the mode cannot be determined from context.
 */

import { useRouter } from 'next/navigation';
import React from 'react';

import { Mode, MODE_CONFIG, MODES } from '@/types/dynamic/mode';

export interface ModeSelectDialogProps {
  /** Whether the dialog is open */
  isOpen: boolean;
  /** Callback when a mode is selected */
  onSelect: (mode: Mode) => void;
  /** Callback when dialog is dismissed without selection (optional) */
  onCancel?: () => void;
  /** Callback when dialog is closed */
  onClose?: () => void;
  /** Current active mode */
  currentMode?: Mode | null;
  /** Whether to allow cancellation (default: false for forced selection) */
  allowCancel?: boolean;
}

/**
 * Mode selection dialog component
 */
export const ModeSelectDialog: React.FC<ModeSelectDialogProps> = ({
  isOpen,
  onSelect,
  onCancel,
  onClose,
  allowCancel = false,
}) => {
  const router = useRouter();

  if (!isOpen) {
    return null;
  }

  const handleModeClick = (mode: Mode) => {
    onSelect(mode);
  };

  const handleWhiteboxClick = () => {
    router.push('/whitebox-scan');
    if (onClose) {
      onClose();
    }
  };

  const handleCancel = () => {
    if (allowCancel && onCancel) {
      onCancel();
    }
    if (onClose) {
      onClose();
    }
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl max-w-2xl w-full mx-4 p-6">
        <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-4">
          Choose Your Mode
        </h2>
        <p className="text-gray-600 dark:text-gray-300 mb-6">
          Select the mode that best fits your current task
        </p>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginBottom: '24px' }}>
          {/* CTF Mode Card */}
          <button
            onClick={() => handleModeClick(MODES.CTF)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '16px',
              padding: '16px',
              border: '2px solid #d1d5db',
              borderRadius: '8px',
              textAlign: 'left',
              width: '100%',
              minHeight: '72px',
              cursor: 'pointer',
              backgroundColor: 'transparent',
              transition: 'border-color 0.2s, background-color 0.2s',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.borderColor = '#3b82f6';
              e.currentTarget.style.backgroundColor = '#eff6ff';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.borderColor = '#d1d5db';
              e.currentTarget.style.backgroundColor = 'transparent';
            }}
          >
            <div style={{ fontSize: '28px', flexShrink: 0, width: '40px', textAlign: 'center' }}>{MODE_CONFIG.ctf.icon}</div>
            <div style={{ flex: 1 }}>
              <h3 style={{ fontSize: '18px', fontWeight: 600, color: '#111827', margin: 0 }}>
                {MODE_CONFIG.ctf.label}
              </h3>
              <p style={{ fontSize: '14px', color: '#6b7280', margin: '4px 0 0 0' }}>
                {MODE_CONFIG.ctf.description}
              </p>
            </div>
          </button>

          {/* Whitebox Scanner Card */}
          <button
            onClick={handleWhiteboxClick}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '16px',
              padding: '16px',
              border: '2px solid #d1d5db',
              borderRadius: '8px',
              textAlign: 'left',
              width: '100%',
              minHeight: '72px',
              cursor: 'pointer',
              backgroundColor: 'transparent',
              transition: 'border-color 0.2s, background-color 0.2s',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.borderColor = '#a855f7';
              e.currentTarget.style.backgroundColor = '#faf5ff';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.borderColor = '#d1d5db';
              e.currentTarget.style.backgroundColor = 'transparent';
            }}
          >
            <div style={{ fontSize: '28px', flexShrink: 0, width: '40px', textAlign: 'center' }}>✓</div>
            <div style={{ flex: 1 }}>
              <h3 style={{ fontSize: '18px', fontWeight: 600, color: '#111827', margin: 0 }}>
                Whitebox Scanner
              </h3>
              <p style={{ fontSize: '14px', color: '#6b7280', margin: '4px 0 0 0' }}>
                Scan source code for vulnerabilities
              </p>
            </div>
          </button>
        </div>

        {allowCancel && (
          <div className="flex justify-end">
            <button
              onClick={handleCancel}
              className="px-4 py-2 text-gray-600 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200 transition-colors"
            >
              Cancel
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default ModeSelectDialog;
