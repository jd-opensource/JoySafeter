'use client';

/**
 * ChatPage component
 * Main chat interface page with unified mode entry
 * Migrated from frontend_dynamic/web to Next.js App Router
 */


import { useSearchParams } from 'next/navigation';
import { useEffect } from 'react';

import { ChatWindow, NewConversationView } from '@/components/dynamic/chat';
import { ModeSelectDialog, ModeSwitcher } from '@/components/dynamic/mode';
import { SessionList, NewSessionButton } from '@/components/dynamic/session';
import { useSessions } from '@/hooks/dynamic/useSessions';
import { chatService } from '@/lib/api/dynamic/chatService';
import { useSession } from '@/lib/auth/auth-client';
import { resolveMode } from '@/lib/utils/dynamic/modeResolve';
import { useChatStore } from '@/stores/dynamic/chatStore';
import { useModeStore } from '@/stores/dynamic/modeStore';
import { useSessionStore } from '@/stores/dynamic/sessionStore';
import { useUserStore } from '@/stores/dynamic/userStore';
import { Mode, toMode } from '@/types/dynamic/mode';
import '@/styles/dynamic/chat.css';

export default function ChatPage() {
  const searchParams = useSearchParams();
  const { userId, setUserId } = useUserStore();
  const session = useSession();
  const sessionEmail = session.data?.user?.email ?? null;
  const { currentSession, switchSession } = useSessionStore();
  const { clearMessages, setCurrentSessionId, reset: resetChatStore } = useChatStore();
  const {
    activeMode,
    preferredMode,
    isSelectingMode,
    setActiveMode,
    setPreferredMode,
    openModeSelect,
    closeModeSelect,
    resetActiveMode,
  } = useModeStore();


  // Sidebar now always expanded
  const sidebarCollapsed = false;
  useSessions(userId ?? '');

  // Initialize mode on page load (supports URL parameter 'scene')
  useEffect(() => {
    // Only initialize mode if no active mode and no current session
    // (sessions restore their own mode)
    if (!activeMode && !currentSession) {
      // 1. Check URL parameter 'scene' first (highest priority)
      const sceneParam = searchParams.get('scene');
      if (sceneParam) {
        const modeFromScene = toMode(sceneParam);
        if (modeFromScene) {
          // Valid scene parameter, set mode and preference
          setActiveMode(modeFromScene);
          setPreferredMode(modeFromScene);
          return;
        }
        // Invalid scene parameter, fall through to normal resolution
      }

      // 2. Fall back to normal mode resolution (preference-based)
      const resolution = resolveMode({
        preferredMode,
      });

      if (resolution.requiresSelection) {
        // Mode is ambiguous, prompt user
        openModeSelect();
      } else if (resolution.mode) {
        // Mode resolved from preference
        setActiveMode(resolution.mode);
      }
    }
  }, [activeMode, currentSession, preferredMode, setActiveMode, setPreferredMode, openModeSelect, searchParams]);

  // Handle mode selection from dialog
  const handleModeSelect = (mode: Mode) => {
    setActiveMode(mode);
    setPreferredMode(mode); // Save as preference for future
    closeModeSelect();
  };

  // Handle mode switching (creates new session)
  const handleSwitchMode = () => {
    // Clear current session to show new conversation view
    switchSession('');
    // Clear chat store state to avoid stale history fetches
    resetChatStore();
    // Reset active mode
    resetActiveMode();
    // Prompt for mode selection
    openModeSelect();
  };





  // Load messages and update session ID when switching sessions
  useEffect(() => {
    if (currentSession && currentSession.id && userId) {
      const { messages, currentSessionId } = useChatStore.getState();

      // Restore mode from session when switching to an existing session
      if (currentSession.mode && currentSession.mode !== activeMode) {
        setActiveMode(currentSession.mode);
      }

      // If session ID already set and has messages, it's a newly created session
      // Don't load from backend to avoid 404
      if (currentSessionId === currentSession.id && messages.length > 0) {
        return;
      }

      clearMessages();
      setCurrentSessionId(currentSession.id);

      // Load message history from backend using specific session endpoint
      const loadMessages = async () => {
        try {
          const messages = await chatService.getMessages(
            currentSession.id,
            userId,
            50,
            0
          );
          messages.forEach((msg) => {
            useChatStore.getState().addMessage(msg);
          });
        } catch (error: any) {
          console.error('Failed to load message history:', error);

          // If session not found (404), it might be a newly created session
          // Just log and continue - don't clear the session
          if (error?.response?.status === 404) {
            console.warn(`Session ${currentSession.id} not found in backend yet, starting fresh...`);
            return;
          }

          // If access denied (403), clear the invalid session
          if (error?.response?.status === 403) {
            console.warn(`Access denied to session ${currentSession.id}, clearing...`);
            switchSession(''); // Clear current session to show session list
          }
        }
      };

      loadMessages();
    }
  }, [currentSession, userId, activeMode, setActiveMode, clearMessages, setCurrentSessionId, switchSession]);

  return (
    <div className="chat-container" style={{ height: '100vh' }}>
      {/* Sidebar with session list */}
      <div
        className={`chat-sidebar ${sidebarCollapsed ? 'collapsed' : ''}`}
      >
        {!sidebarCollapsed && (
          <>
            <div className="chat-sidebar-header" style={{ padding: '16px', borderBottom: '1px solid #e0e0e0' }}>
              <h2 style={{ margin: 0, fontSize: '18px', fontWeight: 600 }}>Sessions</h2>
              <ModeSwitcher onSwitchMode={handleSwitchMode} currentMode={activeMode} />
            </div>
            <div className="new-session-wrapper" style={{ padding: '16px 12px' }}>
              <NewSessionButton userId={userId ?? ''} />
            </div>
            <div className="chat-sidebar-content" style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden' }}>
              <SessionList userId={userId ?? ''} />
            </div>
            <div className="chat-sidebar-footer" style={{ padding: '16px', borderTop: '1px solid #e0e0e0' }}>

            </div>
          </>
        )}

      </div>

      {/* Main chat area */}
      <div className="chat-main-area" style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        {!currentSession ? (
          <NewConversationView userId={userId ?? ''} />
        ) : (
          <ChatWindow sessionId={currentSession.id} />
        )}
      </div>

      {/* Mode selection dialog */}
      {isSelectingMode && (
        <ModeSelectDialog
          isOpen={isSelectingMode}
          onSelect={handleModeSelect}
        />
      )}
    </div>
  );
}
