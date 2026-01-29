/**
 * NewSessionButton component
 * Button to create a new session
 */

import React from 'react';

import { useModeStore } from '@/stores/dynamic/modeStore';
import { useSessionStore } from '@/stores/dynamic/sessionStore';

interface NewSessionButtonProps {
  userId: string;
}

export const NewSessionButton: React.FC<NewSessionButtonProps> = ({
  userId,
}) => {
  const { createSession, sessions } = useSessionStore();
  const { activeMode } = useModeStore();

  const handleNewSession = async () => {
    // Generate unique session title with timestamp
    const now = new Date();
    const dateStr = now.toLocaleDateString();
    const timeStr = now.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });

    // Count sessions created today to add sequence number if needed
    const todaySessions = sessions.filter((s) => {
      const sessionDate = new Date(s.createdAt).toLocaleDateString();
      return sessionDate === dateStr;
    });

    // Generate title with date and time
    const sequenceNum = todaySessions.length + 1;
    const title = `Chat ${dateStr} #${sequenceNum} (${timeStr})`;

    // Create session with active mode (automatically sets as currentSession)
    await createSession(title, userId, activeMode || undefined);
  };

  return (
    <button
      onClick={handleNewSession}
      style={{
        width: '100%',
        padding: '10px 12px',
        backgroundColor: '#3b82f6',
        color: 'white',
        border: 'none',
        borderRadius: '8px',
        fontSize: '14px',
        fontWeight: '600',
        cursor: 'pointer',
        boxShadow: '0 4px 6px rgba(59, 130, 246, 0.3)',
        transition: 'all 0.2s ease',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.backgroundColor = '#2563eb';
        e.currentTarget.style.boxShadow = '0 6px 12px rgba(59, 130, 246, 0.4)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.backgroundColor = '#3b82f6';
        e.currentTarget.style.boxShadow = '0 4px 6px rgba(59, 130, 246, 0.3)';
      }}
    >
      ✨ New Chat
    </button>
  );
};

NewSessionButton.displayName = 'NewSessionButton';
