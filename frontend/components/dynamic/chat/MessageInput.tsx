/**
 * MessageInput component
 * Input field for sending messages
 */

import React, { useState } from 'react';

import { chatService } from '@/lib/api/dynamic/chatService';
import { useSession } from '@/lib/auth/auth-client';
import { useChatStore } from '@/stores/dynamic/chatStore';
import { useModeStore } from '@/stores/dynamic/modeStore';
import { useUserStore } from '@/stores/dynamic/userStore';
import type { Mode } from '@/types/dynamic/mode';

interface MessageInputProps {
  sessionId: string;
  disabled?: boolean;
}

export const MessageInput: React.FC<MessageInputProps> = ({
  sessionId,
  disabled = false,
}) => {
  const [input, setInput] = useState('');
  const { addMessage, updateMessage, removeMessage, setLoading, setError } = useChatStore();
  const { userId } = useUserStore();
  const session = useSession();
  const { activeMode, setActiveMode, setPreferredMode } = useModeStore();

  const handleSendMessage = async () => {
    if (!input.trim()) return;
    // Ensure userId is available (fallback to session email if dynamic store not synced yet)
    const effectiveUserId = userId || session.data?.user?.email;

    if (!effectiveUserId) {
      setError('Not signed in yet. Please wait and try again.');
      return;
    }

    if (!userId) {
      // Sync into dynamic store for subsequent calls
      useUserStore.getState().setUserId(effectiveUserId);
    }

    setError(null);

    // Detect mode from first message if no active mode
    let modeToUse: Mode | null = activeMode;
    if (!modeToUse) {
      try {
        const detection = await chatService.detectMode(input);
        modeToUse = detection.mode;
        setActiveMode(modeToUse);
        // Save as preference if high confidence
        if (detection.confidence === 'high') {
          setPreferredMode(modeToUse);
        }
      } catch (error) {
        console.error('Failed to detect mode:', error);
        // Continue without mode (backend will handle)
      }
    }

    const userMessage = {
      id: `msg_${Date.now()}`,
      sessionId,
      role: 'user' as const,
      content: input,
      timestamp: Date.now(),
      taskId: undefined, // Will be updated when task_created event is received
    };

    addMessage(userMessage);
    setInput('');
    setLoading(true);

    // Declare loadingInterval outside try block so it's accessible in catch/finally
    let loadingInterval: NodeJS.Timeout | null = null;

    try {
      // Stream response from backend
      let assistantContent = '';
      let intermediateContent = '';
      const assistantMessageId = `msg_${Date.now()}_response`;
      const intermediateMessageId = `${assistantMessageId}_intermediate`;

      let intermediateMessageAdded = false;
      let assistantMessageAdded = false;

      // Add initial "Task is creating ..." message
      const loadingMessage = {
        id: intermediateMessageId,
        sessionId,
        role: 'assistant' as const,
        content: 'Task is creating ...',
        timestamp: Date.now(),
        isStreaming: true,
      };
      addMessage(loadingMessage);
      intermediateMessageAdded = true;

      // Start a rolling animation for "Task is creating ..."
      let loadingIndex = 0;
      const loadingMessages = [
        'Task is creating ...',
        'Task is creating .',
        'Task is creating ..',
      ];
      loadingInterval = setInterval(() => {
        // Only animate if we're still in loading state (no intermediate or final content yet)
        if (intermediateMessageAdded && !assistantMessageAdded && intermediateContent === '') {
          loadingIndex = (loadingIndex + 1) % loadingMessages.length;
          updateMessage(intermediateMessageId, {
            content: loadingMessages[loadingIndex],
          });
        }
      }, 2000) as unknown as NodeJS.Timeout;

      for await (const event of chatService.sendMessage(sessionId, input, effectiveUserId, modeToUse)) {
        if (event.type === 'task_created') {
          // Update user message with real task ID from backend
          updateMessage(userMessage.id, {
            taskId: event.data as string,
          });
        } else if (event.type === 'intermediate') {
          // Stop the loading animation
          if (loadingInterval) clearInterval(loadingInterval);

          // Show intermediate results - OVERWRITE (not append)
          const intermediateText = event.data as string;

          // Clear previous intermediate content and show new content with typewriter effect
          const chunkSize = 20; // Process 20 characters per tick
          for (let i = 0; i <= intermediateText.length; i += chunkSize) {
            const displayContent = intermediateText.slice(0, Math.min(i + chunkSize, intermediateText.length));
            updateMessage(intermediateMessageId, {
              content: displayContent,
              isStreaming: true,
            });
            // Minimal delay for streaming effect
            await new Promise(resolve => setTimeout(resolve, 1));
          }
          // Reset intermediateContent to empty (not used for display anymore)
          intermediateContent = '';
        } else if (event.type === 'message_chunk') {
          // Stop the loading animation
          if (loadingInterval) clearInterval(loadingInterval);

          // Remove intermediate message bubble when final content starts
          if (intermediateMessageAdded) {
            removeMessage(intermediateMessageId);
            intermediateMessageAdded = false;
          }

          // Accumulate final response chunks
          assistantContent += event.data;

          if (!assistantMessageAdded) {
            // Add final message first time
            const assistantMessage = {
              id: assistantMessageId,
              sessionId,
              role: 'assistant' as const,
              content: assistantContent,
              timestamp: Date.now(),
              isStreaming: true,
            };
            addMessage(assistantMessage);
            assistantMessageAdded = true;
          } else {
            // Update final message immediately (no delay for streaming)
            updateMessage(assistantMessageId, {
              content: assistantContent,
              isStreaming: true
            });
          }
        } else if (event.type === 'complete') {
          // Stop the loading animation
          if (loadingInterval) clearInterval(loadingInterval);
          // Remove intermediate message bubble on completion
          if (intermediateMessageAdded) {
            removeMessage(intermediateMessageId);
            intermediateMessageAdded = false;
          }
          break;
        }
      }

      // Stop the loading animation
      if (loadingInterval) clearInterval(loadingInterval);

      // Mark streaming as complete
      if (assistantMessageAdded) {
        updateMessage(assistantMessageId, { isStreaming: false });
      }
    } catch (error) {
      // Clear loading interval on error
      if (loadingInterval) clearInterval(loadingInterval);
      setError(error instanceof Error ? error.message : 'Failed to send message');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="message-input-area">
      <div className="message-input">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              handleSendMessage();
            }
          }}
          placeholder="Type your message, press Enter to send..."
          disabled={disabled}
        />
      </div>
    </div>
  );
};

MessageInput.displayName = 'MessageInput';
