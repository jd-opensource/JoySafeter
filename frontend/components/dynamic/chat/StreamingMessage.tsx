/**
 * StreamingMessage component
 * Displays a message that is being streamed in real-time
 */

import React, { useEffect, useState } from 'react';

import { LoadingIndicator } from '@/components/dynamic/ui/LoadingIndicator';

interface StreamingMessageProps {
  content: string;
  isStreaming: boolean;
  role: 'user' | 'assistant';
}

export const StreamingMessage: React.FC<StreamingMessageProps> = ({
  content,
  isStreaming,
  role,
}) => {
  const [displayedContent, setDisplayedContent] = useState('');

  useEffect(() => {
    if (!isStreaming) {
      setDisplayedContent(content);
      return;
    }

    let index = 0;
    const chunkSize = 10; // Process 10 characters per tick

    const interval = setInterval(() => {
      if (index < content.length) {
        const nextIndex = Math.min(index + chunkSize, content.length);
        setDisplayedContent(content.slice(0, nextIndex));
        index = nextIndex;
      } else {
        clearInterval(interval);
      }
    }, 1);

    return () => clearInterval(interval);
  }, [content, isStreaming]);

  return (
    <div className={`message ${role}`}>
      <div className="message-bubble">
        <p>{displayedContent}</p>
        {isStreaming && <LoadingIndicator />}
      </div>
    </div>
  );
};

StreamingMessage.displayName = 'StreamingMessage';
