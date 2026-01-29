/**
 * SessionItem component
 * Displays a single session in the list
 */

import React from 'react';

import type { Session } from '@/types/dynamic/session';

interface SessionItemProps {
  session: Session;
  isActive: boolean;
  onSelect: () => void;
  onDelete?: () => void;
}

export const SessionItem: React.FC<SessionItemProps> = ({
  session,
  isActive,
  onSelect,
  onDelete,
}) => {
  return (
    <div
      className={`session-item ${isActive ? 'active' : 'inactive'}`}
      onClick={onSelect}
      title={session.title}
    >
      <div className="session-item-title">{session.title}</div>
      <div className="session-item-count">
        {session.messageCount} msg
      </div>
      
      {/* Tooltip on hover */}
      <div className="session-item-tooltip">
        {session.title}
      </div>
      
      {onDelete && (
        <button
          className={`text-xs mt-1 transition-opacity ${
            isActive
              ? 'opacity-70 hover:opacity-100'
              : 'opacity-50 hover:opacity-80'
          }`}
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
        >
          Delete
        </button>
      )}
    </div>
  );
};

SessionItem.displayName = 'SessionItem';
