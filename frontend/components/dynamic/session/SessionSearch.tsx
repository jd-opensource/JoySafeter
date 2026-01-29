/**
 * SessionSearch component
 * Search sessions by title or content
 */

import React from 'react';

import { useSessionStore } from '@/stores/dynamic/sessionStore';

export const SessionSearch: React.FC = () => {
  const { searchQuery, searchSessions } = useSessionStore();

  return (
    <div className="p-3 border-b">
      <input
        type="text"
        placeholder="Search sessions..."
        value={searchQuery}
        onChange={(e) => searchSessions(e.target.value)}
        className="w-full px-3 py-2 border rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
    </div>
  );
};

SessionSearch.displayName = 'SessionSearch';
