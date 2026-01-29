/**
 * MessageList component
 * Displays list of messages in conversation
 */

import React from 'react';

import { MessageBubble } from '@/components/dynamic/ui/MessageBubble';
import type { Message } from '@/types/dynamic/chat';

interface MessageListProps {
  messages: Message[];
}

export const MessageList: React.FC<MessageListProps> = ({ messages }) => {
  // Filter out empty messages (like intermediate messages that were cleared)
  const validMessages = messages.filter(msg => msg.content && msg.content.trim().length > 0);

  return (
    <div className="message-list">
      {validMessages.length === 0 ? (
        <div className="flex items-center justify-center h-full text-gray-500">
          <p>No messages yet. Start a conversation!</p>
        </div>
      ) : (
        validMessages.map((message, index) => (
          <MessageBubble
            key={`${message.id}-${message.timestamp}-${index}`}
            content={message.content}
            role={message.role}
            timestamp={message.timestamp}
            taskId={message.taskId}
            sessionId={message.sessionId}
            isStreaming={message.isStreaming}
          />
        ))
      )}
    </div>
  );
};

MessageList.displayName = 'MessageList';
