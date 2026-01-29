/**
 * ChatWindow component
 * Main chat interface with message list and input
 */

import React, { useEffect, useRef } from 'react';

import { useChatStore } from '@/stores/dynamic/chatStore';

import { MessageInput } from './MessageInput';
import { MessageList } from './MessageList';

interface ChatWindowProps {
  sessionId: string;
}

export const ChatWindow: React.FC<ChatWindowProps> = ({ sessionId }) => {
  const { messages, isLoading } = useChatStore();
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to latest message
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  return (
    <div className="chat-main">
      {/* Chat body with messages */}
      <div className="chat-body">
        <MessageList messages={messages} />
        <div ref={messagesEndRef} />
      </div>

      {/* Message input area */}
      <MessageInput sessionId={sessionId} disabled={isLoading} />
    </div>
  );
};

ChatWindow.displayName = 'ChatWindow';
