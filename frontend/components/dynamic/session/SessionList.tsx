/**
 * SessionList component
 * Displays list of conversation sessions
 */

import React, { useEffect } from 'react';

import { useSessionStore } from '@/stores/dynamic/sessionStore';

import { SessionItem } from './SessionItem';


interface SessionListProps {
  userId: string;
}

export const SessionList: React.FC<SessionListProps> = ({ userId }) => {
  const { sessions, currentSession, searchQuery, loadSessions, switchSession } =
    useSessionStore();

  useEffect(() => {
    loadSessions(userId);
  }, [userId, loadSessions]);

  // Filter sessions by search queryx
  const filteredSessions = sessions.filter((session) =>
    session.title.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <>


      <div className="flex-1 overflow-y-auto overflow-x-hidden">
        {filteredSessions.length === 0 ? (
          <div className="p-4 text-center text-gray-500 text-sm">
            {searchQuery ? 'No sessions found' : 'No sessions yet'}
          </div>
        ) : (
          <div className="space-y-2 px-2 py-2">
            {filteredSessions.map((session, idx) => (
              <SessionItem
                key={`${session.id}-${idx}`}
                session={session}
                isActive={currentSession?.id === session.id}
                onSelect={() => switchSession(session.id)}
              />
            ))}
          </div>
        )}
      </div>
    </>
  );
};

SessionList.displayName = 'SessionList';
