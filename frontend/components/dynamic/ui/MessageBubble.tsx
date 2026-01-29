/**
 * MessageBubble component
 * Displays a single message in the chat
 */

import clsx from 'clsx';
import React from 'react';

import { useUserStore } from '@/stores/dynamic/userStore';

import { MarkdownContent } from './MarkdownContent';


interface MessageBubbleProps {
  content: string;
  role: 'user' | 'assistant' | 'system';
  timestamp?: number;
  taskId?: string;
  sessionId?: string;
  isStreaming?: boolean;
}

export const MessageBubble: React.FC<MessageBubbleProps> = ({
  content,
  role,
  timestamp,
  taskId,
  sessionId,
  isStreaming = false,
}) => {
  const isUser = role === 'user';
  const { userId } = useUserStore();

  // Navigate to task visualization in new tab
  const handleViewExecution = (e: React.MouseEvent) => {
    e.preventDefault();
    const params = new URLSearchParams();
    if (userId) params.set('userId', userId);
    if (sessionId) params.set('sessionId', sessionId);
    if (taskId) params.set('taskId', taskId);
    const url = `/dynamic/visualization?${params.toString()}`;
    window.open(url, '_blank');
  };

  return (
    <div className={clsx('message', role)}>
      <div className="message-bubble">
        <div className="message-bubble-content" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            {role === 'assistant' ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                {isStreaming && (
                  <div className="loading-spinner" style={{ flexShrink: 0, marginRight: '4px' }}>
                    <div className="spinner-ring"></div>
                  </div>
                )}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <MarkdownContent content={content} />
                </div>
              </div>
            ) : (
              <p>{content}</p>
            )}
          </div>
          {isUser && taskId ? (
            <div style={{ position: 'relative', flexShrink: 0 }}>
              <button
                onClick={handleViewExecution}
                className="task-link"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: '14px',
                  textDecoration: 'none',
                  width: '24px',
                  height: '24px',
                  borderRadius: '4px',
                  background: '#e5e7eb',
                  boxShadow: '0 1px 3px rgba(0, 0, 0, 0.1)',
                  transition: 'all 0.2s ease',
                  cursor: 'pointer',
                  border: 'none',
                  padding: 0,
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.boxShadow = '0 2px 8px rgba(0, 0, 0, 0.15)';
                  e.currentTarget.style.transform = 'translateY(-1px) scale(1.15)';
                  // Show tooltip
                  const tooltip = e.currentTarget.nextElementSibling as HTMLElement;
                  if (tooltip) tooltip.style.opacity = '1';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.boxShadow = '0 1px 3px rgba(0, 0, 0, 0.1)';
                  e.currentTarget.style.transform = 'translateY(0) scale(1)';
                  // Hide tooltip
                  const tooltip = e.currentTarget.nextElementSibling as HTMLElement;
                  if (tooltip) tooltip.style.opacity = '0';
                }}
              >
                🔍
              </button>
              <div
                style={{
                  position: 'absolute',
                  top: '100%',
                  right: '0',
                  marginTop: '8px',
                  padding: '6px 10px',
                  backgroundColor: '#1f2937',
                  color: 'white',
                  fontSize: '12px',
                  borderRadius: '4px',
                  whiteSpace: 'nowrap',
                  opacity: '0',
                  transition: 'opacity 0.2s ease',
                  pointerEvents: 'none',
                  zIndex: 10,
                }}
              >
                View task execution
              </div>
            </div>
          ) : null}
        </div>
        {timestamp && role === 'assistant' ? (
          <div className="tooltip">
            <div className="tooltip-text">
              {new Date(timestamp).toLocaleTimeString()}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
};

MessageBubble.displayName = 'MessageBubble';
